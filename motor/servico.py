"""Daemon em segundo plano: a peça do processo e a do login, no systemd, no launchd e no Agendador de Tarefas."""

from __future__ import annotations

import contextlib
import os
import plistlib
import re
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
    FLAG_ATIVAR_SCHTASKS,
    FLAG_DESATIVAR_SCHTASKS,
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
from motor.errors import BackendIndisponivel, ErroDeEntrada

ARQUIVO_SERVICE = "monitor-versoes-serve.service"
ROTULO_PROCESSO = "monitor-versoes.daemon"
ROTULO_LOGIN = "monitor-versoes.login"
ROTULO_LEGADO = "monitor-versoes.serve"
ARQUIVO_LOG_LAUNCHD = "monitor-versoes-serve.log"
EXECUTAVEL = "monitor-versoes"
EXECUTAVEL_SERVE = "monitor-versoes-serve"
NOME_TAREFA_SERVE = "monitor-versoes-serve"
NOME_TAREFA_PROCESSO = "monitor-versoes-daemon"
NOME_TAREFA_LOGIN = "monitor-versoes-login"
ARQUIVO_LOG_SERVE = "serve.log"
PRAZO_SUBIDA_S = 10
INTERVALO_SONDA_S = 0.5
TIMEOUT_SONDA_S = 2
FORMATO_INICIO_TAREFA = "%Y-%m-%dT%H:%M:%S"
COMANDO_CONFIGURAR = "configurar"
ARGUMENTOS_SERVE = ("daemon", "rodar", "--sem-navegador")
ARGUMENTOS_LEGADOS = ("serve", "--sem-navegador")
ARGUMENTOS_LOGIN = ("daemon", "iniciar", "--sem-perguntas")
ARGUMENTOS_SEM_LOGIN = ("daemon", "parar", "--sem-perguntas")

FLAG_PERSISTIR = "-w"
ESTADO_SYSTEMD_ATIVO = "active"
ESTADO_SYSTEMD_HABILITADO = "enabled"
ESTADO_LAUNCHD_ATIVO = "state = running"
TAREFA_DESATIVADA = "<Enabled>false</Enabled>"
SETTINGS_DA_TAREFA = re.compile(r"<Settings>.*?</Settings>", re.DOTALL)

Consultar = Callable[[list[str]], str | None]


class EstadoServico(StrEnum):
    ATIVO = "ativo"
    PARADO = "parado"
    NO_TERMINAL = "no terminal"
    SEM_SUPORTE = "sem suporte"


@dataclass(frozen=True)
class Situacao:
    estado: EstadoServico
    login: bool = False
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


def endereco_web(porta: int) -> str:
    return f"http://127.0.0.1:{porta}/"


def serve_responde(porta: int, esperar: bool) -> bool:
    limite = time.monotonic() + (PRAZO_SUBIDA_S if esperar else 0)
    while True:
        try:
            if httpx.get(endereco_web(porta), timeout=TIMEOUT_SONDA_S).is_success:
                return True
        except httpx.HTTPError:
            pass
        if time.monotonic() >= limite:
            return False
        time.sleep(INTERVALO_SONDA_S)


def caminho(sistema: Sistema, home: Path) -> Path:
    """O arquivo da peça do processo."""
    if sistema is Sistema.MACOS:
        # Fora do LaunchAgents: o launchd não o carrega sozinho no login.
        return Path(diretorio_dados()) / f"{ROTULO_PROCESSO}.plist"
    return home / ".config" / "systemd" / "user" / ARQUIVO_SERVICE


def _agente(home: Path, rotulo: str) -> Path:
    return home / "Library" / "LaunchAgents" / f"{rotulo}.plist"


def _log_launchd(home: Path) -> Path:
    return home / "Library" / "Logs" / ARQUIVO_LOG_LAUNCHD


def _alvo_launchd() -> str:
    return f"gui/{os.getuid()}/{ROTULO_PROCESSO}"


def _exec_start(executavel: str) -> str:
    return f'ExecStart="{executavel}" {" ".join(ARGUMENTOS_SERVE)}\n'


def _unit(executavel: str) -> str:
    return (
        "[Unit]\n"
        "Description=monitor-versoes: interface web e disparo das inscrições\n\n"
        "[Service]\n"
        f"{_exec_start(executavel)}"
        "Restart=on-failure\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _plist_login(executavel: str, home: Path) -> bytes:
    log = str(_log_launchd(home))
    return plistlib.dumps(
        {
            "Label": ROTULO_LOGIN,
            "ProgramArguments": [executavel, *ARGUMENTOS_LOGIN],
            "RunAtLoad": True,
            "StandardOutPath": log,
            "StandardErrorPath": log,
        }
    )


def _plist(executavel: str, home: Path) -> bytes:
    log = str(_log_launchd(home))
    return plistlib.dumps(
        {
            "Label": ROTULO_PROCESSO,
            "ProgramArguments": [executavel, *ARGUMENTOS_SERVE],
            "RunAtLoad": True,
            "KeepAlive": True,
            "StandardOutPath": log,
            "StandardErrorPath": log,
        }
    )


def _tarefa(nome: str, acao: AcaoSchtasks, *resto: str) -> list[str]:
    return [SCHTASKS, acao, FLAG_TAREFA, nome, *resto]


def _gatilho_logon() -> str:
    usuario = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"
    return f"""    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(usuario)}</UserId>
    </LogonTrigger>"""


def _gatilho_repetido() -> str:
    inicio = datetime.now().strftime(FORMATO_INICIO_TAREFA)
    return f"""    <TimeTrigger>
      <StartBoundary>{inicio}</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>PT1M</Interval>
      </Repetition>
    </TimeTrigger>"""


def _argumentos_xml(argumentos: tuple[str, ...]) -> str:
    return f"<Arguments>{escape(' '.join(argumentos))}</Arguments>"


def _xml_tarefa(gatilho: str, executavel: str, argumentos: tuple[str, ...]) -> str:
    args = f"\n      {_argumentos_xml(argumentos)}" if argumentos else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
{gatilho}
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
      <Command>{escape(executavel)}</Command>{args}
    </Exec>
  </Actions>
</Task>
"""


def _criar_tarefa(nome: str, xml_tarefa: str, rodar_comando: Comando) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-16", suffix=".xml", delete=False
    ) as xml:
        xml.write(xml_tarefa)
    try:
        rodar_comando(
            _tarefa(nome, AcaoSchtasks.CREATE, FLAG_XML, xml.name, FLAG_FORCAR_SCHTASKS)
        )
    finally:
        Path(xml.name).unlink(missing_ok=True)


def _criar_login(
    executavel: str, argumentos: tuple[str, ...], rodar_comando: Comando
) -> None:
    xml_login = _xml_tarefa(_gatilho_logon(), executavel, argumentos)
    _criar_tarefa(NOME_TAREFA_LOGIN, xml_login, rodar_comando)


def _subir_windows(executavel: str, rodar_comando: Comando) -> None:
    # Sem a tarefa de logon com `parar`, o gatilho de 1 min religaria no próximo logon um daemon iniciado sem login.
    try:
        rodar_comando(_tarefa(NOME_TAREFA_LOGIN, AcaoSchtasks.QUERY))
    except BackendIndisponivel:
        _criar_login(executavel, ARGUMENTOS_SEM_LOGIN, rodar_comando)
    # Com IgnoreNew, o `/run` deixaria de pé o daemon antigo; parar o que não roda é inócuo.
    with contextlib.suppress(BackendIndisponivel):
        rodar_comando(_tarefa(NOME_TAREFA_PROCESSO, AcaoSchtasks.END))
    _criar_tarefa(
        NOME_TAREFA_PROCESSO,
        _xml_tarefa(_gatilho_repetido(), executavel, ()),
        rodar_comando,
    )
    rodar_comando(
        _tarefa(NOME_TAREFA_PROCESSO, AcaoSchtasks.CHANGE, FLAG_ATIVAR_SCHTASKS)
    )
    try:
        rodar_comando(_tarefa(NOME_TAREFA_PROCESSO, AcaoSchtasks.RUN))
    except BackendIndisponivel:
        with contextlib.suppress(BackendIndisponivel):
            rodar_comando(
                _tarefa(NOME_TAREFA_PROCESSO, AcaoSchtasks.DELETE, FLAG_FORCAR_SCHTASKS)
            )
        raise


def _remover_windows(rodar_comando: Comando) -> None:
    for nome in (NOME_TAREFA_PROCESSO, NOME_TAREFA_LOGIN, NOME_TAREFA_SERVE):
        for acao in (
            _tarefa(nome, AcaoSchtasks.END),
            _tarefa(nome, AcaoSchtasks.DELETE, FLAG_FORCAR_SCHTASKS),
        ):
            with contextlib.suppress(BackendIndisponivel):
                rodar_comando(acao)


def regravar(
    sistema: Sistema, home: Path, executavel: str, rodar_comando: Comando
) -> None:
    # No Windows gravar a tarefa a ativa, e o gatilho de 1 min subiria o processo.
    if sistema is Sistema.WINDOWS:
        return
    arquivo = caminho(sistema, home)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    if sistema is Sistema.MACOS:
        _log_launchd(home).parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_bytes(_plist(executavel, home))
        return
    arquivo.write_text(_unit(executavel))
    rodar_comando([*SYSTEMCTL, Acao.DAEMON_RELOAD])


def subir(
    sistema: Sistema, home: Path, executavel: str, rodar_comando: Comando
) -> None:
    if sistema is Sistema.WINDOWS:
        _subir_windows(executavel, rodar_comando)
        return
    regravar(sistema, home, executavel, rodar_comando)
    if sistema is Sistema.MACOS:
        arquivo = str(caminho(sistema, home))
        # Um job já carregado ignoraria o plist novo; descarregar antes é inócuo se não estiver.
        with contextlib.suppress(BackendIndisponivel):
            rodar_comando([LAUNCHCTL, Acao.UNLOAD, arquivo])
        rodar_comando([LAUNCHCTL, Acao.LOAD, arquivo])
        return
    # `start` não reinicia uma unit ativa, que seguiria com o ExecStart antigo.
    rodar_comando([*SYSTEMCTL, Acao.RESTART, ARQUIVO_SERVICE])


def parar(sistema: Sistema, home: Path, rodar_comando: Comando) -> None:
    if sistema is Sistema.WINDOWS:
        rodar_comando(
            _tarefa(NOME_TAREFA_PROCESSO, AcaoSchtasks.CHANGE, FLAG_DESATIVAR_SCHTASKS)
        )
        # O `parar` do logon roda também com o daemon já parado: o `/end` falharia.
        with contextlib.suppress(BackendIndisponivel):
            rodar_comando(_tarefa(NOME_TAREFA_PROCESSO, AcaoSchtasks.END))
    elif sistema is Sistema.MACOS:
        rodar_comando([LAUNCHCTL, Acao.UNLOAD, str(caminho(sistema, home))])
    else:
        rodar_comando([*SYSTEMCTL, Acao.STOP, ARQUIVO_SERVICE])


def rodando(sistema: Sistema, home: Path, consultar: Consultar) -> bool:
    if sistema is Sistema.WINDOWS:
        saida = consultar(_tarefa(NOME_TAREFA_PROCESSO, AcaoSchtasks.QUERY, FLAG_XML))
        if saida is None:
            return False
        settings = SETTINGS_DA_TAREFA.search(saida)
        return settings is None or TAREFA_DESATIVADA not in settings.group()
    if sistema is Sistema.MACOS:
        saida = consultar([LAUNCHCTL, Acao.PRINT, _alvo_launchd()])
        return saida is not None and ESTADO_LAUNCHD_ATIVO in saida
    saida = consultar([*SYSTEMCTL, Acao.IS_ACTIVE, ARQUIVO_SERVICE])
    return saida is not None and saida.strip() == ESTADO_SYSTEMD_ATIVO


def ligar_login(
    sistema: Sistema, home: Path, executavel: str, rodar_comando: Comando
) -> None:
    if sistema is Sistema.WINDOWS:
        _criar_login(executavel, ARGUMENTOS_LOGIN, rodar_comando)
        return
    if sistema is Sistema.MACOS:
        arquivo = _agente(home, ROTULO_LOGIN)
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_bytes(_plist_login(executavel, home))
        return
    arquivo = caminho(sistema, home)
    if not arquivo.exists():
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(_unit(executavel))
    rodar_comando([*SYSTEMCTL, Acao.DAEMON_RELOAD])
    rodar_comando([*SYSTEMCTL, Acao.ENABLE, ARQUIVO_SERVICE])


def desligar_login(sistema: Sistema, home: Path, rodar_comando: Comando) -> None:
    if sistema is Sistema.WINDOWS:
        # A tarefa fica, com `parar`: sem ela o gatilho de 1 min religaria o daemon no logon.
        _criar_login(executavel_servico(), ARGUMENTOS_SEM_LOGIN, rodar_comando)
    elif sistema is Sistema.MACOS:
        arquivo = _agente(home, ROTULO_LOGIN)
        # O arquivo é o que `login_ligado` olha: falha no unload não pode deixá-lo.
        with contextlib.suppress(BackendIndisponivel):
            rodar_comando([LAUNCHCTL, Acao.UNLOAD, str(arquivo)])
        arquivo.unlink(missing_ok=True)
    else:
        rodar_comando([*SYSTEMCTL, Acao.DISABLE, ARQUIVO_SERVICE])


def login_ligado(sistema: Sistema, home: Path, consultar: Consultar) -> bool:
    if sistema is Sistema.WINDOWS:
        saida = consultar(_tarefa(NOME_TAREFA_LOGIN, AcaoSchtasks.QUERY, FLAG_XML))
        return saida is not None and _argumentos_xml(ARGUMENTOS_LOGIN) in saida
    if sistema is Sistema.MACOS:
        return _agente(home, ROTULO_LOGIN).exists()
    saida = consultar([*SYSTEMCTL, Acao.IS_ENABLED, ARQUIVO_SERVICE])
    return saida is not None and saida.strip() == ESTADO_SYSTEMD_HABILITADO


def migrar_legado(
    sistema: Sistema,
    home: Path,
    executavel: str,
    rodar_comando: Comando,
    consultar: Consultar,
) -> bool:
    if sistema is Sistema.WINDOWS:
        if not _tarefa_existe(NOME_TAREFA_SERVE, consultar):
            return False
        with contextlib.suppress(BackendIndisponivel):
            rodar_comando(_tarefa(NOME_TAREFA_SERVE, AcaoSchtasks.END))
        rodar_comando(
            _tarefa(NOME_TAREFA_SERVE, AcaoSchtasks.DELETE, FLAG_FORCAR_SCHTASKS)
        )
        ligar_login(sistema, home, executavel, rodar_comando)
        subir(sistema, home, executavel, rodar_comando)
        return True
    if sistema is Sistema.MACOS:
        legado = _agente(home, ROTULO_LEGADO)
        if not legado.exists():
            return False
        # O antigo só sai depois do novo de pé: se subir falhar, a próxima reinstalação tenta de novo.
        ligar_login(sistema, home, executavel, rodar_comando)
        subir(sistema, home, executavel, rodar_comando)
        with contextlib.suppress(BackendIndisponivel):
            rodar_comando([LAUNCHCTL, Acao.UNLOAD, FLAG_PERSISTIR, str(legado)])
        legado.unlink()
        return True
    arquivo = caminho(sistema, home)
    if not arquivo.exists() or _exec_start(executavel) in arquivo.read_text():
        return False
    regravar(sistema, home, executavel, rodar_comando)
    return True


def remover(sistema: Sistema, home: Path, rodar_comando: Comando) -> None:
    if sistema is Sistema.WINDOWS:
        _remover_windows(rodar_comando)
        return
    # Desativar o que não está ativo não pode impedir a remoção dos arquivos.
    if sistema is Sistema.MACOS:
        for arquivo, flags in (
            (caminho(sistema, home), ()),
            (_agente(home, ROTULO_LOGIN), ()),
            (_agente(home, ROTULO_LEGADO), (FLAG_PERSISTIR,)),
        ):
            if not arquivo.exists():
                continue
            with contextlib.suppress(BackendIndisponivel):
                rodar_comando([LAUNCHCTL, Acao.UNLOAD, *flags, str(arquivo)])
            arquivo.unlink()
        return
    for acao in (Acao.STOP, Acao.DISABLE):
        with contextlib.suppress(BackendIndisponivel):
            rodar_comando([*SYSTEMCTL, acao, ARQUIVO_SERVICE])
    caminho(sistema, home).unlink(missing_ok=True)
    with contextlib.suppress(BackendIndisponivel):
        rodar_comando([*SYSTEMCTL, Acao.DAEMON_RELOAD])


def _sistema_ou_none() -> Sistema | None:
    try:
        return sistema_atual()
    except ErroDeEntrada:
        return None


def _tarefa_existe(nome: str, consultar: Consultar) -> bool:
    return consultar(_tarefa(nome, AcaoSchtasks.QUERY)) is not None


def apos_reinstalar(home: Path, rodar_comando: Comando, consultar: Consultar) -> bool:
    sistema = _sistema_ou_none()
    # No Windows quem reinicia é o ajudante da reinstalação, não este caminho.
    if sistema is None or sistema is Sistema.WINDOWS:
        return False
    executavel = executavel_servico()
    migrar_legado(sistema, home, executavel, rodar_comando, consultar)
    if rodando(sistema, home, consultar):
        subir(sistema, home, executavel, rodar_comando)
        return True
    if caminho(sistema, home).exists():
        regravar(sistema, home, executavel, rodar_comando)
    return False


def situacao(
    home: Path, consultar: Consultar, responde: Callable[[], bool]
) -> Situacao:
    sistema = _sistema_ou_none()
    if sistema is None:
        return Situacao(EstadoServico.SEM_SUPORTE)
    login = login_ligado(sistema, home, consultar)
    if sistema is Sistema.WINDOWS:
        # Tarefa ativada não diz se o processo está de pé: só a porta diz.
        if responde():
            gerido = rodando(sistema, home, consultar)
            estado = EstadoServico.ATIVO if gerido else EstadoServico.NO_TERMINAL
            return Situacao(estado, login)
        log = Path(diretorio_dados()) / ARQUIVO_LOG_SERVE
        return Situacao(EstadoServico.PARADO, login, f"Get-Content -Wait '{log}'")
    if rodando(sistema, home, consultar):
        return Situacao(EstadoServico.ATIVO, login)
    if responde():
        return Situacao(EstadoServico.NO_TERMINAL, login)
    if sistema is Sistema.MACOS:
        ver_log = f"tail -f ~/Library/Logs/{ARQUIVO_LOG_LAUNCHD}"
    else:
        ver_log = f"journalctl --user -u {ARQUIVO_SERVICE}"
    return Situacao(EstadoServico.PARADO, login, ver_log)


def consultar_do_sistema(cmd: list[str]) -> str | None:
    if cmd[0] == SCHTASKS:
        # Fora o XML, só o código de saída conta: o texto vem na página OEM do console.
        try:
            schtasks = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE if FLAG_XML in cmd else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=console.FLAGS_SEM_JANELA,
            )
        except subprocess.CalledProcessError, OSError:
            return None
        return (schtasks.stdout or b"").decode(errors="replace")
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
