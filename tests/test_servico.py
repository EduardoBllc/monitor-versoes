from __future__ import annotations

import os
import plistlib
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from motor import servico
from motor.__main__ import main
from motor.agendador import Acao, Sistema
from motor.errors import BackendIndisponivel
from motor.servico import (
    ARGUMENTOS_SERVE,
    ARQUIVO_LOG_LAUNCHD,
    ARQUIVO_SERVICE,
    ROTULO_LAUNCHD,
    EstadoServico,
    caminho,
    desligar,
    executavel_motor,
    ligado,
    ligar,
    reiniciar_se_ligado,
    situacao,
)
from tests.plataforma import PLATAFORMA_WINDOWS
from tests.test_agendador import Registro

EXE = "/opt/venv/bin/monitor-versoes"
SYSTEMCTL = ["systemctl", "--user"]

pula_mac_no_windows = pytest.mark.skipif(
    sys.platform == PLATAFORMA_WINDOWS, reason="launchctl usa o uid do POSIX"
)
SISTEMAS = [
    pytest.param(Sistema.LINUX, id="linux"),
    pytest.param(Sistema.MACOS, id="macos", marks=pula_mac_no_windows),
]


def _como(sistema: Sistema, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", sistema.value)


def _devolvendo(saida: str | None) -> Callable[[list[str]], str | None]:
    return lambda _: saida


def _alvo_mac() -> str:
    return f"gui/{os.getuid()}/{ROTULO_LAUNCHD}"


def _criar_arquivo(sistema: Sistema, home: Path) -> Path:
    arquivo = caminho(sistema, home)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.touch()
    return arquivo


@pytest.mark.parametrize("sistema", SISTEMAS)
def test_ligar_cria_o_servico_e_sobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sistema: Sistema
) -> None:
    _como(sistema, monkeypatch)
    registro = Registro()
    ligar(sistema, tmp_path, EXE, registro)

    arquivo = caminho(sistema, tmp_path)
    assert arquivo.exists()
    if sistema is Sistema.LINUX:
        texto = arquivo.read_text()
        assert f'ExecStart="{EXE}" {" ".join(ARGUMENTOS_SERVE)}' in texto
        assert "Restart=on-failure" in texto
        assert registro.comandos == [
            [*SYSTEMCTL, Acao.DAEMON_RELOAD],
            [*SYSTEMCTL, Acao.ENABLE, "--now", ARQUIVO_SERVICE],
        ]
    else:
        dados = plistlib.loads(arquivo.read_bytes())
        log = str(tmp_path / "Library" / "Logs" / ARQUIVO_LOG_LAUNCHD)
        assert dados["ProgramArguments"] == [EXE, *ARGUMENTOS_SERVE]
        assert dados["RunAtLoad"] is True
        assert dados["KeepAlive"] is True
        assert dados["StandardOutPath"] == log
        assert dados["StandardErrorPath"] == log
        assert registro.comandos == [["launchctl", Acao.LOAD, "-w", str(arquivo)]]


@pytest.mark.parametrize(
    ("sistema", "acao"),
    [
        (Sistema.LINUX, Acao.DISABLE),
        (Sistema.LINUX, Acao.DAEMON_RELOAD),
        pytest.param(Sistema.MACOS, Acao.UNLOAD, marks=pula_mac_no_windows),
    ],
)
def test_desligar_para_e_remove_mesmo_se_o_sistema_falha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sistema: Sistema, acao: Acao
) -> None:
    _como(sistema, monkeypatch)
    arquivo = _criar_arquivo(sistema, tmp_path)
    desligar(sistema, tmp_path, Registro(falhar_em=acao))
    assert not arquivo.exists()


@pytest.mark.parametrize("sistema", SISTEMAS)
def test_reiniciar_se_ligado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sistema: Sistema
) -> None:
    _como(sistema, monkeypatch)
    desligado = Registro()
    assert not reiniciar_se_ligado(tmp_path, desligado)
    assert not desligado.comandos

    _criar_arquivo(sistema, tmp_path)
    registro = Registro()
    assert reiniciar_se_ligado(tmp_path, registro)
    esperado = (
        [*SYSTEMCTL, Acao.RESTART, ARQUIVO_SERVICE]
        if sistema is Sistema.LINUX
        else ["launchctl", Acao.KICKSTART, "-k", _alvo_mac()]
    )
    assert registro.comandos == [esperado]


def test_reiniciar_se_ligado_sem_suporte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", PLATAFORMA_WINDOWS)
    registro = Registro()
    assert not reiniciar_se_ligado(tmp_path, registro)
    assert not ligado(tmp_path)
    assert not registro.comandos


@pytest.mark.parametrize(
    ("sistema", "ativo", "ver_log"),
    [
        pytest.param(
            Sistema.LINUX,
            "active\n",
            "journalctl --user -u monitor-versoes-serve.service",
            id="linux",
        ),
        pytest.param(
            Sistema.MACOS,
            "\tstate = running\n",
            f"tail -f ~/Library/Logs/{ARQUIVO_LOG_LAUNCHD}",
            marks=pula_mac_no_windows,
            id="macos",
        ),
    ],
)
def test_situacao(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sistema: Sistema,
    ativo: str,
    ver_log: str,
) -> None:
    _como(sistema, monkeypatch)
    assert situacao(tmp_path, lambda _: ativo).estado is EstadoServico.DESLIGADO

    _criar_arquivo(sistema, tmp_path)
    assert situacao(tmp_path, lambda _: ativo).estado is EstadoServico.ATIVO
    for saida in (None, "inactive\n", "\tstate = waiting\n"):
        parado = situacao(tmp_path, _devolvendo(saida))
        assert parado.estado is EstadoServico.PARADO
        assert parado.ver_log == ver_log


def test_situacao_sem_suporte(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", PLATAFORMA_WINDOWS)
    assert situacao(tmp_path, lambda _: None).estado is EstadoServico.SEM_SUPORTE


def test_executavel_motor_nao_depende_do_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")
    exe = Path(executavel_motor())
    assert exe.is_absolute()
    assert exe.stem == servico.EXECUTAVEL


def test_comando_do_sistema_que_falha_propaga(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _como(Sistema.LINUX, monkeypatch)
    with pytest.raises(BackendIndisponivel):
        ligar(Sistema.LINUX, tmp_path, EXE, Registro(falhar_em=Acao.ENABLE))


@pytest.mark.parametrize("sem_navegador", [False, True])
def test_serve_sem_navegador_nao_abre(
    monkeypatch: pytest.MonkeyPatch, sem_navegador: bool
) -> None:
    import threading

    import uvicorn

    import motor.__main__ as cli
    import motor.daemon.app as daemon_app

    with socket.socket() as livre:
        livre.bind(("127.0.0.1", 0))
        porta = livre.getsockname()[1]
    abertos: list[str] = []

    def timer(_atraso, funcao, args):
        return SimpleNamespace(start=lambda: funcao(*args))

    monkeypatch.setattr(cli, "checar_backend", lambda: None)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(threading, "Timer", timer)
    monkeypatch.setattr(daemon_app, "_abrir_navegador", abertos.append)

    main(["serve", "--porta", str(porta), *(["--sem-navegador"] * sem_navegador)])

    assert bool(abertos) is not sem_navegador
