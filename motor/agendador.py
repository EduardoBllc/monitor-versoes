"""Remove o timer do systemd/launchd que versões antigas instalavam; o daemon dispara as inscrições."""

from __future__ import annotations

import contextlib
import subprocess
import sys
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from motor.errors import BackendIndisponivel, ErroDeEntrada

ARQUIVO_SERVICE = "monitor-versoes-inscricoes.service"
ARQUIVO_TIMER = "monitor-versoes-inscricoes.timer"
ARQUIVO_PLIST = "monitor-versoes.inscricoes.plist"
SYSTEMCTL = ("systemctl", "--user")
LAUNCHCTL = "launchctl"
SCHTASKS = "schtasks"
FLAG_TAREFA = "/tn"
FLAG_XML = "/xml"
FLAG_FORCAR_SCHTASKS = "/f"


class Acao(StrEnum):
    DAEMON_RELOAD = "daemon-reload"
    DISABLE = "disable"
    UNLOAD = "unload"
    ENABLE = "enable"
    RESTART = "restart"
    IS_ACTIVE = "is-active"
    LOAD = "load"
    KICKSTART = "kickstart"
    PRINT = "print"


class AcaoSchtasks(StrEnum):
    CREATE = "/create"
    DELETE = "/delete"
    END = "/end"
    RUN = "/run"
    QUERY = "/query"


FLAG_AGORA = "--now"

Comando = Callable[[list[str]], None]


class Sistema(StrEnum):
    LINUX = "linux"
    MACOS = "darwin"
    WINDOWS = "win32"


def sistema_atual() -> Sistema:
    try:
        return Sistema(sys.platform)
    except ValueError:
        raise ErroDeEntrada(
            f"agendador automático não suportado em {sys.platform}"
        ) from None


def caminhos(sistema: Sistema, home: Path) -> list[Path]:
    if sistema is Sistema.MACOS:
        return [home / "Library" / "LaunchAgents" / ARQUIVO_PLIST]
    base = home / ".config" / "systemd" / "user"
    return [base / ARQUIVO_SERVICE, base / ARQUIVO_TIMER]


def desagendar(sistema: Sistema, home: Path, rodar_comando: Comando) -> None:
    lista = caminhos(sistema, home)
    # Desativar o que não está ativo não pode impedir a remoção dos arquivos.
    with contextlib.suppress(BackendIndisponivel):
        if sistema is Sistema.MACOS:
            rodar_comando([LAUNCHCTL, Acao.UNLOAD, str(lista[0])])
        else:
            rodar_comando([*SYSTEMCTL, Acao.DISABLE, FLAG_AGORA, ARQUIVO_TIMER])
    for caminho in lista:
        caminho.unlink(missing_ok=True)
    if sistema is Sistema.LINUX:
        with contextlib.suppress(BackendIndisponivel):
            rodar_comando([*SYSTEMCTL, Acao.DAEMON_RELOAD])


def instalado(sistema: Sistema, home: Path) -> bool:
    return all(c.exists() for c in caminhos(sistema, home))


def remover_agendador_antigo(home: Path, rodar_comando: Comando) -> bool:
    """Apaga o timer das versões antigas; `True` se havia algo a apagar."""
    try:
        sistema = sistema_atual()
    except ErroDeEntrada:
        return False
    # O Windows nunca teve timer antigo: `caminhos` não cobre esse sistema.
    if sistema is Sistema.WINDOWS or not instalado(sistema, home):
        return False
    desagendar(sistema, home, rodar_comando)
    print(
        "timer antigo das inscrições removido: o `serve` passou a dispará-las",
        file=sys.stderr,
    )
    return True


def rodar_comando_do_sistema(cmd: list[str]) -> None:
    # O `stderr` do `schtasks` vem na página OEM do console: decodificar com rigor quebraria.
    try:
        subprocess.run(
            cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as e:
        detalhe = (e.stderr or b"").decode(errors="replace").strip()
        raise BackendIndisponivel(f"{' '.join(cmd)}: {e} {detalhe}".strip()) from e
    except OSError as e:
        raise BackendIndisponivel(f"{' '.join(cmd)}: {e}") from e
