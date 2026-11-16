"""Serviço de login que mantém o daemon (`serve`) de pé: systemd, LaunchAgent e Agendador de Tarefas."""

from __future__ import annotations

import contextlib
import os
import plistlib
import subprocess
import sys
import sysconfig
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from xml.sax.saxutils import escape

import httpx

from motor import console
from motor.agendador import (
    FLAG_AGORA,
    FLAG_FORCAR_SCHTASKS,
    FLAG_TAREFA,
    FLAG_XML,
    LAUNCHCTL,
    SCHTASKS,
    SYSTEMCTL,
    Acao,
    AcaoSchtasks,
    Comando,
    Sistema,
    sistema_atual,
)
from motor.config import diretorio_dados
from motor.daemon import PORTA_PADRAO
from motor.errors import BackendIndisponivel, ErroDeEntrada

ARQUIVO_SERVICE = "monitor-versoes-serve.service"
ROTULO_LAUNCHD = "monitor-versoes.serve"
ARQUIVO_PLIST = f"{ROTULO_LAUNCHD}.plist"
ARQUIVO_LOG_LAUNCHD = "monitor-versoes-serve.log"
EXECUTAVEL = "monitor-versoes"
EXECUTAVEL_SERVE = "monitor-versoes-serve"
NOME_TAREFA_SERVE = "monitor-versoes-serve"
ARQUIVO_LOG_SERVE = "serve.log"
ENDERECO_WEB = f"http://127.0.0.1:{PORTA_PADRAO}/"
PRAZO_SUBIDA_S = 10
INTERVALO_SONDA_S = 0.5
TIMEOUT_SONDA_S = 2
FORMATO_INICIO_TAREFA = "%Y-%m-%dT%H:%M:%S"
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


def _executavel(nome: str) -> str:
    sufixo = ""
    if sys.platform == "win32":
        sufixo = sysconfig.get_config_var("EXE") or ""
    return str(Path(sysconfig.get_path("scripts")) / f"{nome}{sufixo}")


def executavel_motor() -> str:
    return _executavel(EXECUTAVEL)


def executavel_servico() -> str:
    """No Windows, o `.exe` sem console; nos outros, o mesmo `monitor-versoes`."""
    if sys.platform == "win32":
        return _executavel(EXECUTAVEL_SERVE)
    return executavel_motor()


def serve_responde(esperar: bool) -> bool:
    limite = time.monotonic() + (PRAZO_SUBIDA_S if esperar else 0)
    while True:
        try:
            if httpx.get(ENDERECO_WEB, timeout=TIMEOUT_SONDA_S).is_success:
                return True
        except httpx.HTTPError:
            pass
        if time.monotonic() >= limite:
            return False
        time.sleep(INTERVALO_SONDA_S)


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


def _tarefa(acao: AcaoSchtasks, *resto: str) -> list[str]:
    return [SCHTASKS, acao, FLAG_TAREFA, NOME_TAREFA_SERVE, *resto]


def _xml_tarefa(executavel: str) -> str:
    usuario = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"
    inicio = datetime.now().strftime(FORMATO_INICIO_TAREFA)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(usuario)}</UserId>
    </LogonTrigger>
    <TimeTrigger>
      <StartBoundary>{inicio}</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>PT1M</Interval>
      </Repetition>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(executavel)}</Command>
    </Exec>
  </Actions>
</Task>
"""


def _ligar_windows(executavel: str, rodar_comando: Comando) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-16", suffix=".xml", delete=False
    ) as xml:
        xml.write(_xml_tarefa(executavel))
    # Com IgnoreNew, o `/run` deixaria de pé o serve antigo; parar o que não roda é inócuo.
    with contextlib.suppress(BackendIndisponivel):
        rodar_comando(_tarefa(AcaoSchtasks.END))
    try:
        rodar_comando(
            _tarefa(AcaoSchtasks.CREATE, FLAG_XML, xml.name, FLAG_FORCAR_SCHTASKS)
        )
    finally:
        Path(xml.name).unlink(missing_ok=True)
    try:
        rodar_comando(_tarefa(AcaoSchtasks.RUN))
    except BackendIndisponivel:
        with contextlib.suppress(BackendIndisponivel):
            rodar_comando(_tarefa(AcaoSchtasks.DELETE, FLAG_FORCAR_SCHTASKS))
        raise


def ligar(
    sistema: Sistema, home: Path, executavel: str, rodar_comando: Comando
) -> None:
    if sistema is Sistema.WINDOWS:
        _ligar_windows(executavel, rodar_comando)
        return
    arquivo = caminho(sistema, home)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    try:
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
        rodar_comando([*SYSTEMCTL, Acao.ENABLE, ARQUIVO_SERVICE])
        # `enable --now` não reinicia uma unit ativa, que seguiria com o ExecStart antigo.
        rodar_comando([*SYSTEMCTL, Acao.RESTART, ARQUIVO_SERVICE])
    except BackendIndisponivel:
        # O arquivo é o que `ligado()` olha: deixá-lo sem o serviço de pé mente que está ligado.
        if sistema is Sistema.LINUX:
            # O `enable` já criou o link em default.target.wants; sem a unit ele ficaria órfão.
            with contextlib.suppress(BackendIndisponivel):
                rodar_comando([*SYSTEMCTL, Acao.DISABLE, ARQUIVO_SERVICE])
        arquivo.unlink(missing_ok=True)
        if sistema is Sistema.LINUX:
            with contextlib.suppress(BackendIndisponivel):
                rodar_comando([*SYSTEMCTL, Acao.DAEMON_RELOAD])
        raise


def desligar(sistema: Sistema, home: Path, rodar_comando: Comando) -> None:
    if sistema is Sistema.WINDOWS:
        for acao in (
            _tarefa(AcaoSchtasks.END),
            _tarefa(AcaoSchtasks.DELETE, FLAG_FORCAR_SCHTASKS),
        ):
            with contextlib.suppress(BackendIndisponivel):
                rodar_comando(acao)
        return
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
    if sistema is Sistema.WINDOWS:
        return _tarefa_existe(consultar_do_sistema)
    return sistema is not None and caminho(sistema, home).exists()


def _tarefa_existe(consultar: Consultar) -> bool:
    return consultar(_tarefa(AcaoSchtasks.QUERY)) is not None


def reiniciar_se_ligado(home: Path, rodar_comando: Comando) -> bool:
    sistema = _sistema_ou_none()
    # No Windows quem reinicia é o ajudante da reinstalação, não este caminho.
    if (
        sistema is None
        or sistema is Sistema.WINDOWS
        or not caminho(sistema, home).exists()
    ):
        return False
    if sistema is Sistema.MACOS:
        rodar_comando([LAUNCHCTL, Acao.KICKSTART, FLAG_FORCAR, _alvo_launchd()])
    else:
        rodar_comando([*SYSTEMCTL, Acao.RESTART, ARQUIVO_SERVICE])
    return True


def situacao(
    home: Path, consultar: Consultar, responde: Callable[[], bool]
) -> Situacao:
    sistema = _sistema_ou_none()
    if sistema is None:
        return Situacao(EstadoServico.SEM_SUPORTE)
    if sistema is Sistema.WINDOWS:
        if not _tarefa_existe(consultar):
            return Situacao(EstadoServico.DESLIGADO)
        if responde():
            return Situacao(EstadoServico.ATIVO)
        log = Path(diretorio_dados()) / ARQUIVO_LOG_SERVE
        return Situacao(EstadoServico.PARADO, f"Get-Content -Wait '{log}'")
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
    if cmd[0] == SCHTASKS:
        # Só o código de saída conta: o texto vem na página OEM do console.
        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=console.FLAGS_SEM_JANELA,
            )
        except subprocess.CalledProcessError, OSError:
            return None
        return ""
    try:
        feito = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            creationflags=console.FLAGS_SEM_JANELA,
        )
    except subprocess.CalledProcessError, OSError:
        return None
    return feito.stdout
