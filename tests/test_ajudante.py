from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from motor import ajudante, servico
from motor.agendador import (
    FLAG_ATIVAR_SCHTASKS,
    FLAG_DESATIVAR_SCHTASKS,
    FLAG_TAREFA,
    SCHTASKS,
    AcaoSchtasks,
)
from motor.ajudante import (
    ARQUIVO_ANTES,
    ARQUIVO_COMANDO,
    ARQUIVO_RESULTADO,
    ARQUIVO_SCRIPT,
    CODIFICACAO,
    PASTA_REINSTALACAO,
    POLITICA_BYPASS,
    POWERSHELL,
    PRAZO_PROCESSOS_S,
    VAR_ESTADO,
    ArgPowershell,
    entregar,
    pasta_reinstalacao,
)
from motor.cli_instalacao import COMANDO_POS_REINSTALAR
from motor.errors import CodigoSaida, ErroDeEntrada
from motor.inscricoes import NOME_TRAVA_INSCRICOES
from motor.instalacao import (
    PACOTE_MOTOR,
    UV,
    ArgUv,
    Registro,
    Requisito,
    registro_de_json,
)
from motor.servico import NOME_TAREFA_PROCESSO, NOME_TAREFA_SERVE
from motor.trava import caminho_trava_inscricoes, travar_arquivo
from tests.plataforma import PLATAFORMA_WINDOWS
from tests.tarefas_falsas import EstadoTarefa, com_tarefas

ANTES = Registro(Requisito(PACOTE_MOTOR), ())
CMD = [UV, ArgUv.TOOL, ArgUv.INSTALL, ArgUv.REINSTALL, PACOTE_MOTOR]
PID_AJUDANTE = 4321
CONTEUDO_VELHO = "1"
RESULTADO_OK = "0"
RESULTADO_FALHA = "1"
CODIGO_FALHA_UV = 1
MOTOR_FALSO = "motor"
PYTHON_DO_VENV = Path("Scripts", "python.exe")
VAR_PATH = "PATH"
PASTA_FALSOS = "falsos"
PASTA_BIN = "bin"
PASTA_AMBIENTE = "ambiente"
PASTA_VENV = "venv"
ARQUIVO_LOG = "log.txt"
ARQUIVO_ESTADO = "estado"
PRAZO_CURTO_S = 2
# Bem maior que a espera do PID: a ordem no log não depende da velocidade do runner.
PRAZO_LONGO_S = 60
LIMITE_TESTE_S = 120
ESPERA_DO_PID_S = 3
MARCA_PID = "pid encerrado"
PROCESSO_DE_TESTE_S = 60
ARG_PYTHON_CODIGO = "-c"
# Frase do ajudante_windows.ps1, que não tem como importar.
AVISO_UV_FALHOU = "A reinstalação falhou"
PASTA_BIN_DO_UV = "bin-do-uv"
PASTA_MODULOS = "modulos"


class Disparo:
    def __init__(self) -> None:
        self.linhas: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> int:
        self.linhas.append(cmd)
        return PID_AJUDANTE


def test_entregar_recusa_com_inscricao_em_andamento() -> None:
    disparo = Disparo()
    with (
        travar_arquivo(NOME_TRAVA_INSCRICOES, caminho_trava_inscricoes()),
        pytest.raises(ErroDeEntrada),
    ):
        entregar(ANTES, CMD, disparo)
    assert disparo.linhas == []
    assert not pasta_reinstalacao().exists()


def _uv_falso(monkeypatch: pytest.MonkeyPatch, bin_uv: Path | None) -> None:
    """`uv tool dir --bin` responde `bin_uv`, ou falha quando é None."""

    def rodar(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        assert cmd == [UV, ArgUv.TOOL, ArgUv.DIR, ArgUv.BIN]
        if bin_uv is None:
            raise FileNotFoundError(UV)
        return subprocess.CompletedProcess(cmd, CodigoSaida.OK, stdout=f"{bin_uv}\n")

    monkeypatch.setattr(subprocess, "run", rodar)


@pytest.mark.parametrize("uv_responde", [True, False])
def test_entregar_grava_o_estado_e_dispara(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uv_responde: bool
) -> None:
    pasta = pasta_reinstalacao()
    pasta.mkdir(parents=True)
    (pasta / ARQUIVO_RESULTADO).write_text(CONTEUDO_VELHO)
    bin_which = tmp_path / PASTA_BIN
    monkeypatch.setattr(
        shutil,
        "which",
        lambda nome: str(bin_which / nome) if nome == PACOTE_MOTOR else None,
    )
    bin_uv = tmp_path / PASTA_BIN_DO_UV if uv_responde else bin_which
    _uv_falso(monkeypatch, bin_uv if uv_responde else None)
    estado = tmp_path / ARQUIVO_ESTADO
    monkeypatch.setenv(VAR_ESTADO, str(estado))
    disparo = Disparo()

    entregar(ANTES, CMD, disparo)

    assert not (pasta / ARQUIVO_RESULTADO).exists()
    assert registro_de_json((pasta / ARQUIVO_ANTES).read_text()) == ANTES
    assert json.loads((pasta / ARQUIVO_COMANDO).read_text()) == CMD
    original = Path(ajudante.__file__).with_name(ARQUIVO_SCRIPT)
    assert (pasta / ARQUIVO_SCRIPT).read_bytes() == original.read_bytes()
    assert disparo.linhas == [
        [
            POWERSHELL,
            ArgPowershell.NO_PROFILE,
            ArgPowershell.EXECUTION_POLICY,
            POLITICA_BYPASS,
            ArgPowershell.FILE,
            str(pasta / ARQUIVO_SCRIPT),
            ArgPowershell.PASTA,
            str(pasta),
            ArgPowershell.MOTOR,
            servico.executavel_motor(),
            ArgPowershell.AMBIENTE,
            sys.prefix,
            ArgPowershell.BIN,
            str(bin_uv),
            ArgPowershell.PIDS,
            f"{os.getpid()},{os.getppid()}",
            ArgPowershell.PRAZO_PROCESSOS,
            str(PRAZO_PROCESSOS_S),
        ]
    ]
    assert estado.read_text() == str(PID_AJUDANTE)


# --- O `.ps1` de verdade, só no Windows ---

so_windows = pytest.mark.skipif(
    sys.platform != PLATAFORMA_WINDOWS, reason="o ajudante é PowerShell do Windows"
)


def _falso(pasta: Path, nome: str, log: Path, codigo: int = 0) -> Path:
    """Um `.cmd` que registra o nome e os argumentos em `log` e sai com `codigo`."""
    arquivo = pasta / f"{nome}.cmd"
    arquivo.write_text(f'@echo off\r\n>>"{log}" echo {nome} %*\r\nexit /b {codigo}\r\n')
    return arquivo


def _pid_encerrado() -> int:
    processo = subprocess.Popen([sys.executable, ARG_PYTHON_CODIGO, ""])
    processo.wait()
    return processo.pid


def _rodar(
    tmp_path: Path,
    *,
    pids: str,
    codigo_uv: int = 0,
    ambiente: Path | None = None,
    prazo_s: int = PRAZO_CURTO_S,
    tarefa: EstadoTarefa | None = EstadoTarefa.ATIVADA,
    legada: EstadoTarefa | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str], Path]:
    falsos = tmp_path / PASTA_FALSOS
    falsos.mkdir()
    log = tmp_path / ARQUIVO_LOG
    _falso(falsos, UV, log, codigo_uv)
    _falso(falsos, SCHTASKS, log)
    motor = _falso(falsos, MOTOR_FALSO, log)
    pasta = tmp_path / PASTA_REINSTALACAO
    pasta.mkdir()
    (pasta / ARQUIVO_COMANDO).write_text(json.dumps(CMD))
    bin_uv = tmp_path / PASTA_BIN
    bin_uv.mkdir()
    if ambiente is None:
        ambiente = tmp_path / PASTA_AMBIENTE
        ambiente.mkdir()
    script = Path(ajudante.__file__).with_name(ARQUIVO_SCRIPT)
    env = {**os.environ, VAR_PATH: f"{falsos}{os.pathsep}{os.environ[VAR_PATH]}"}
    tarefas = {
        nome: estado
        for nome, estado in (
            (NOME_TAREFA_PROCESSO, tarefa),
            (NOME_TAREFA_SERVE, legada),
        )
        if estado is not None
    }
    saida = subprocess.run(
        [
            POWERSHELL,
            ArgPowershell.NO_PROFILE,
            ArgPowershell.EXECUTION_POLICY,
            POLITICA_BYPASS,
            ArgPowershell.FILE,
            str(script),
            ArgPowershell.PASTA,
            str(pasta),
            ArgPowershell.MOTOR,
            str(motor),
            ArgPowershell.AMBIENTE,
            str(ambiente),
            ArgPowershell.BIN,
            str(bin_uv),
            ArgPowershell.PIDS,
            pids,
            ArgPowershell.PRAZO_PROCESSOS,
            str(prazo_s),
        ],
        capture_output=True,
        encoding=CODIFICACAO,
        env=com_tarefas(tmp_path / PASTA_MODULOS, env, tarefas),
        timeout=LIMITE_TESTE_S,
        check=False,
    )
    linhas = log.read_text().splitlines() if log.exists() else []
    return saida, [linha.strip() for linha in linhas], pasta


def _schtasks(acao: AcaoSchtasks, *resto: str, nome: str = NOME_TAREFA_PROCESSO) -> str:
    return " ".join([SCHTASKS, acao, FLAG_TAREFA, nome, *resto])


DESATIVAR = _schtasks(AcaoSchtasks.CHANGE, FLAG_DESATIVAR_SCHTASKS)
ATIVAR = _schtasks(AcaoSchtasks.CHANGE, FLAG_ATIVAR_SCHTASKS)


@so_windows
def test_ajudante_espera_os_pids_roda_o_uv_e_sobe_o_servico(tmp_path: Path) -> None:
    log = tmp_path / ARQUIVO_LOG
    lento = subprocess.Popen(
        [
            sys.executable,
            ARG_PYTHON_CODIGO,
            f"import time; time.sleep({ESPERA_DO_PID_S}); "
            f"open({str(log)!r}, 'a').write({MARCA_PID!r} + '\\n')",
        ]
    )
    try:
        saida, linhas, pasta = _rodar(
            tmp_path, pids=f"{lento.pid},{_pid_encerrado()}", prazo_s=PRAZO_LONGO_S
        )
    finally:
        lento.wait()

    assert linhas == [
        MARCA_PID,
        DESATIVAR,
        _schtasks(AcaoSchtasks.END),
        " ".join(CMD),
        f"{MOTOR_FALSO} {COMANDO_POS_REINSTALAR}",
        ATIVAR,
        _schtasks(AcaoSchtasks.RUN),
    ], saida
    assert (pasta / ARQUIVO_RESULTADO).read_text().strip() == RESULTADO_OK


@so_windows
@pytest.mark.parametrize("tarefa", [EstadoTarefa.DESATIVADA, None])
def test_ajudante_nao_sobe_o_daemon_parado_ou_sem_tarefa(
    tmp_path: Path, tarefa: EstadoTarefa | None
) -> None:
    saida, linhas, pasta = _rodar(tmp_path, pids=str(_pid_encerrado()), tarefa=tarefa)

    assert linhas == [" ".join(CMD), f"{MOTOR_FALSO} {COMANDO_POS_REINSTALAR}"], saida
    assert (pasta / ARQUIVO_RESULTADO).read_text().strip() == RESULTADO_OK


@so_windows
def test_ajudante_para_e_religa_a_tarefa_legada_ativada(tmp_path: Path) -> None:
    saida, linhas, _ = _rodar(
        tmp_path,
        pids=str(_pid_encerrado()),
        tarefa=None,
        legada=EstadoTarefa.ATIVADA,
    )

    assert linhas == [
        _schtasks(AcaoSchtasks.CHANGE, FLAG_DESATIVAR_SCHTASKS, nome=NOME_TAREFA_SERVE),
        _schtasks(AcaoSchtasks.END, nome=NOME_TAREFA_SERVE),
        " ".join(CMD),
        f"{MOTOR_FALSO} {COMANDO_POS_REINSTALAR}",
        _schtasks(AcaoSchtasks.CHANGE, FLAG_ATIVAR_SCHTASKS, nome=NOME_TAREFA_SERVE),
        _schtasks(AcaoSchtasks.RUN, nome=NOME_TAREFA_SERVE),
    ], saida


@so_windows
def test_ajudante_com_uv_que_falha(tmp_path: Path) -> None:
    saida, linhas, pasta = _rodar(
        tmp_path, pids=str(_pid_encerrado()), codigo_uv=CODIGO_FALHA_UV
    )

    assert AVISO_UV_FALHOU in saida.stdout
    assert " ".join(CMD) in saida.stdout
    assert linhas[-3:] == [" ".join(CMD), ATIVAR, _schtasks(AcaoSchtasks.RUN)]
    assert (pasta / ARQUIVO_RESULTADO).read_text().strip() == RESULTADO_FALHA


@so_windows
def test_ajudante_desiste_com_processo_vivo_do_ambiente(tmp_path: Path) -> None:
    ambiente = tmp_path / PASTA_VENV
    venv.create(ambiente)
    vivo = subprocess.Popen(
        [
            str(ambiente / PYTHON_DO_VENV),
            ARG_PYTHON_CODIGO,
            f"import time; time.sleep({PROCESSO_DE_TESTE_S})",
        ]
    )
    try:
        saida, linhas, pasta = _rodar(
            tmp_path, pids=str(_pid_encerrado()), ambiente=ambiente
        )
    finally:
        vivo.kill()
        vivo.wait()

    assert " ".join(CMD) not in linhas
    assert str(vivo.pid) in saida.stdout
    assert linhas[-2:] == [ATIVAR, _schtasks(AcaoSchtasks.RUN)]
    assert (pasta / ARQUIVO_RESULTADO).read_text().strip() == RESULTADO_FALHA
