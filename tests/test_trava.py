"""Lock por clone entre processos (decisão 032)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from motor.errors import ErroDeEntrada, RepoOcupado
from motor.trava import caminho_trava, caminho_trava_inscricoes, travar, travar_arquivo

RAIZ = Path(__file__).resolve().parents[1]
NOME_TRAVA = "trava de teste"
PRAZO_PARA_SOLTAR_S = 10
INTERVALO_DE_ESPERA_S = 0.05


@pytest.fixture
def clone(tmp_path) -> str:
    caminho = tmp_path / "clone"
    caminho.mkdir()
    return str(caminho)


def test_segundo_travar_no_mesmo_clone_e_recusado_com_pid(clone):
    with travar("r", clone), pytest.raises(RepoOcupado) as erro:
        travar("r", clone)
    assert isinstance(erro.value, ErroDeEntrada)
    assert erro.value.pid == os.getpid()
    assert str(erro.value) == f"repo r ocupado por outra operação (pid {os.getpid()})"


def test_nomes_diferentes_com_o_mesmo_caminho_se_bloqueiam(clone, tmp_path):
    outro = tmp_path / "outro"
    outro.mkdir()
    with travar("a", clone):
        with pytest.raises(RepoOcupado):
            travar("b", clone + "/")
        with travar("c", str(outro)):
            pass


def test_pid_ilegivel_recusa_sem_pid(clone):
    with travar("r", clone):
        caminho_trava(clone).write_text("xx")
        with pytest.raises(RepoOcupado) as erro:
            travar("r", clone)
    assert erro.value.pid is None
    assert "pid" not in str(erro.value)


def test_trava_solta_ao_sair_com_erro(clone):
    with pytest.raises(RuntimeError), travar("r", clone):
        raise RuntimeError("falhou")
    with travar("r", clone):
        pass


def test_soltar_e_idempotente(clone):
    trava = travar("r", clone)
    trava.soltar()
    trava.soltar()
    with travar("r", clone):
        pass


_SEGURA_E_DORME = """
import os, sys, time
from pathlib import Path
import motor.trava
motor.trava.diretorio_travas = lambda: Path(sys.argv[1])
trava = motor.trava.travar("r", sys.argv[2])
print(os.getpid(), flush=True)
time.sleep(60)
"""


def test_processo_morto_com_sigkill_nao_deixa_o_repo_travado(clone, tmp_path):
    filho = subprocess.Popen(
        [sys.executable, "-c", _SEGURA_E_DORME, str(tmp_path / "travas"), clone],
        cwd=RAIZ,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert filho.stdout is not None
        # O pid que o filho informa, não `filho.pid`: no Windows o python do
        # venv é um lançador, e o interpretador que trava é processo neto.
        pid = int(filho.stdout.readline())
        with pytest.raises(RepoOcupado) as erro:
            travar("r", clone)
        assert erro.value.pid == pid
    finally:
        filho.kill()
        filho.wait()
        if filho.stdout is not None:
            filho.stdout.close()
    # No Windows o `wait()` é do lançador do venv: o neto que segura a trava
    # morre depois, então a trava solta com algum atraso.
    prazo = time.monotonic() + PRAZO_PARA_SOLTAR_S
    while True:
        try:
            with travar("r", clone):
                break
        except RepoOcupado:
            if time.monotonic() > prazo:
                raise
            time.sleep(INTERVALO_DE_ESPERA_S)


_SEGURA_ARQUIVO = """
import sys
from pathlib import Path
from motor.trava import travar_arquivo
trava = travar_arquivo(sys.argv[2], Path(sys.argv[1]))
print("pronto", flush=True)
sys.stdin.read()
"""


def test_travar_arquivo_exclui_outro_processo():
    caminho = caminho_trava_inscricoes()
    filho = subprocess.Popen(
        [sys.executable, "-c", _SEGURA_ARQUIVO, str(caminho), NOME_TRAVA],
        cwd=RAIZ,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    # Saída pelo stdin, não `kill()`: no Windows o kill mata só o lançador do venv,
    # e o neto que segura a trava morre depois, sem o `wait()` esperar por ele.
    try:
        assert filho.stdout is not None
        filho.stdout.readline()
        with pytest.raises(RepoOcupado):
            travar_arquivo(NOME_TRAVA, caminho)
    finally:
        filho.communicate(timeout=30)
    with travar_arquivo(NOME_TRAVA, caminho):
        pass
