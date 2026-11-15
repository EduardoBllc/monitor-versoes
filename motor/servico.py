"""Serviço de login que mantém o daemon (`serve`) de pé: systemd de usuário e LaunchAgent."""

from __future__ import annotations

import contextlib
import os
import plistlib
import subprocess
import sysconfig
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from motor.agendador import (
    FLAG_AGORA,
    LAUNCHCTL,
    SYSTEMCTL,
    Acao,
    Comando,
    Sistema,
    sistema_atual,
)
from motor.errors import BackendIndisponivel, ErroDeEntrada

ARQUIVO_SERVICE = "monitor-versoes-serve.service"
ROTULO_LAUNCHD = "monitor-versoes.serve"
ARQUIVO_PLIST = f"{ROTULO_LAUNCHD}.plist"
ARQUIVO_LOG_LAUNCHD = "monitor-versoes-serve.log"
EXECUTAVEL = "monitor-versoes"
COMANDO_CONFIGURAR = "configurar"
ARGUMENTOS_SERVE = ("serve", "--sem-navegador")

FLAG_PERSISTIR = "-w"
FLAG_FORCAR = "-k"
ESTADO_SYSTEMD_ATIVO = "active"
ESTADO_LAUNCHD_ATIVO = "state = running"

Consultar = Callable[[list[str]], str | None]


class EstadoServico(StrEnum):
    ATIVO = "ativo"
    PARADO = "parado"
    DESLIGADO = "desligado"
    SEM_SUPORTE = "sem suporte"


@dataclass(frozen=True)
class Situacao:
    estado: EstadoServico
    ver_log: str = ""


def executavel_motor() -> str:
    return str(Path(sysconfig.get_path("scripts")) / EXECUTAVEL)


def caminho(sistema: Sistema, home: Path) -> Path:
    if sistema is Sistema.MACOS:
        return home / "Library" / "LaunchAgents" / ARQUIVO_PLIST
    return home / ".config" / "systemd" / "user" / ARQUIVO_SERVICE


def _log_launchd(home: Path) -> Path:
    return home / "Library" / "Logs" / ARQUIVO_LOG_LAUNCHD


def _alvo_launchd() -> str:
    return f"gui/{os.getuid()}/{ROTULO_LAUNCHD}"


def _unit(executavel: str) -> str:
    return (
        "[Unit]\n"
        "Description=monitor-versoes: interface web e disparo das inscrições\n\n"
        "[Service]\n"
        f'ExecStart="{executavel}" {" ".join(ARGUMENTOS_SERVE)}\n'
        "Restart=on-failure\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _plist(executavel: str, home: Path) -> bytes:
    log = str(_log_launchd(home))
    return plistlib.dumps(
        {
            "Label": ROTULO_LAUNCHD,
            "ProgramArguments": [executavel, *ARGUMENTOS_SERVE],
            "RunAtLoad": True,
            "KeepAlive": True,
            "StandardOutPath": log,
            "StandardErrorPath": log,
        }
    )


def ligar(
    sistema: Sistema, home: Path, executavel: str, rodar_comando: Comando
) -> None:
    arquivo = caminho(sistema, home)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    if sistema is Sistema.MACOS:
        _log_launchd(home).parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_bytes(_plist(executavel, home))
        # Um job já carregado ignoraria o plist novo; descarregar antes é inócuo se não estiver.
        with contextlib.suppress(BackendIndisponivel):
            rodar_comando([LAUNCHCTL, Acao.UNLOAD, FLAG_PERSISTIR, str(arquivo)])
        rodar_comando([LAUNCHCTL, Acao.LOAD, FLAG_PERSISTIR, str(arquivo)])
        return
    arquivo.write_text(_unit(executavel))
    rodar_comando([*SYSTEMCTL, Acao.DAEMON_RELOAD])
    rodar_comando([*SYSTEMCTL, Acao.ENABLE, FLAG_AGORA, ARQUIVO_SERVICE])


def desligar(sistema: Sistema, home: Path, rodar_comando: Comando) -> None:
    arquivo = caminho(sistema, home)
    # Desativar o que não está ativo não pode impedir a remoção do arquivo.
    with contextlib.suppress(BackendIndisponivel):
        if sistema is Sistema.MACOS:
            rodar_comando([LAUNCHCTL, Acao.UNLOAD, FLAG_PERSISTIR, str(arquivo)])
        else:
            rodar_comando([*SYSTEMCTL, Acao.DISABLE, FLAG_AGORA, ARQUIVO_SERVICE])
    arquivo.unlink(missing_ok=True)
    if sistema is Sistema.LINUX:
        with contextlib.suppress(BackendIndisponivel):
            rodar_comando([*SYSTEMCTL, Acao.DAEMON_RELOAD])


def _sistema_ou_none() -> Sistema | None:
    try:
        return sistema_atual()
    except ErroDeEntrada:
        return None


def ligado(home: Path) -> bool:
    sistema = _sistema_ou_none()
    return sistema is not None and caminho(sistema, home).exists()


def reiniciar_se_ligado(home: Path, rodar_comando: Comando) -> bool:
    sistema = _sistema_ou_none()
    if sistema is None or not caminho(sistema, home).exists():
        return False
    if sistema is Sistema.MACOS:
        rodar_comando([LAUNCHCTL, Acao.KICKSTART, FLAG_FORCAR, _alvo_launchd()])
    else:
        rodar_comando([*SYSTEMCTL, Acao.RESTART, ARQUIVO_SERVICE])
    return True


def situacao(home: Path, consultar: Consultar) -> Situacao:
    sistema = _sistema_ou_none()
    if sistema is None:
        return Situacao(EstadoServico.SEM_SUPORTE)
    if not caminho(sistema, home).exists():
        return Situacao(EstadoServico.DESLIGADO)
    if sistema is Sistema.MACOS:
        saida = consultar([LAUNCHCTL, Acao.PRINT, _alvo_launchd()])
        ativo = saida is not None and ESTADO_LAUNCHD_ATIVO in saida
        ver_log = f"tail -f ~/Library/Logs/{ARQUIVO_LOG_LAUNCHD}"
    else:
        saida = consultar([*SYSTEMCTL, Acao.IS_ACTIVE, ARQUIVO_SERVICE])
        ativo = saida is not None and saida.strip() == ESTADO_SYSTEMD_ATIVO
        ver_log = f"journalctl --user -u {ARQUIVO_SERVICE}"
    return (
        Situacao(EstadoServico.ATIVO)
        if ativo
        else Situacao(EstadoServico.PARADO, ver_log)
    )


def consultar_do_sistema(cmd: list[str]) -> str | None:
    try:
        feito = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError, OSError:
        return None
    return feito.stdout
