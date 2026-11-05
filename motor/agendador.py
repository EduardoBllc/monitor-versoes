"""Instala o disparo por minuto de `motor inscricao rodar` no systemd ou no launchd."""

from __future__ import annotations

import contextlib
import plistlib
import shutil
import subprocess
import sys
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from motor.errors import BackendIndisponivel, ErroDeEntrada

ARGUMENTOS_RODAR = ("inscricao", "rodar")
ARQUIVO_SERVICE = "monitor-versoes-inscricoes.service"
ARQUIVO_TIMER = "monitor-versoes-inscricoes.timer"
ROTULO_LAUNCHD = "monitor-versoes.inscricoes"
ARQUIVO_PLIST = f"{ROTULO_LAUNCHD}.plist"
INTERVALO_LAUNCHD_S = 60
CHAVE_ROTULO = "Label"
CHAVE_ARGUMENTOS = "ProgramArguments"
CHAVE_INTERVALO = "StartInterval"
EXECUTAVEL = "motor"

Comando = Callable[[list[str]], None]


class Sistema(StrEnum):
    LINUX = "linux"
    MACOS = "darwin"


def sistema_atual() -> Sistema:
    try:
        return Sistema(sys.platform)
    except ValueError:
        raise ErroDeEntrada(f"agendador não suportado em {sys.platform}") from None


def executavel_motor() -> str:
    # O agendador roda com PATH mínimo: o caminho absoluto é resolvido aqui.
    achado = shutil.which(EXECUTAVEL)
    if achado is None:
        raise ErroDeEntrada(f"executável `{EXECUTAVEL}` fora do PATH")
    return str(Path(achado).absolute())


def _dir_systemd(home: Path) -> Path:
    return home / ".config" / "systemd" / "user"


def _caminho_plist(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / ARQUIVO_PLIST


def arquivos(sistema: Sistema, executavel: str, home: Path) -> dict[Path, str]:
    if sistema is Sistema.MACOS:
        plist = plistlib.dumps(
            {
                CHAVE_ROTULO: ROTULO_LAUNCHD,
                CHAVE_ARGUMENTOS: [executavel, *ARGUMENTOS_RODAR],
                CHAVE_INTERVALO: INTERVALO_LAUNCHD_S,
            }
        ).decode()
        return {_caminho_plist(home): plist}
    base = _dir_systemd(home)
    servico = (
        "[Unit]\nDescription=Inscrições do monitor-versoes\n\n"
        f"[Service]\nType=oneshot\nExecStart={executavel} {' '.join(ARGUMENTOS_RODAR)}\n"
    )
    timer = (
        "[Unit]\nDescription=Dispara as inscrições do monitor-versoes\n\n"
        "[Timer]\nOnCalendar=minutely\n\n[Install]\nWantedBy=timers.target\n"
    )
    return {base / ARQUIVO_SERVICE: servico, base / ARQUIVO_TIMER: timer}


def agendar(
    sistema: Sistema, home: Path, executavel: str, rodar_comando: Comando
) -> None:
    conteudo = arquivos(sistema, executavel, home)
    for caminho, texto in conteudo.items():
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(texto)
    if sistema is Sistema.MACOS:
        [plist] = conteudo
        with contextlib.suppress(BackendIndisponivel):  # pode não estar carregado
            rodar_comando(["launchctl", "unload", str(plist)])
        rodar_comando(["launchctl", "load", "-w", str(plist)])
        return
    rodar_comando(["systemctl", "--user", "daemon-reload"])
    rodar_comando(["systemctl", "--user", "enable", "--now", ARQUIVO_TIMER])


def desagendar(sistema: Sistema, home: Path, rodar_comando: Comando) -> None:
    caminhos = list(arquivos(sistema, "", home))
    if sistema is Sistema.MACOS:
        rodar_comando(["launchctl", "unload", str(caminhos[0])])
    else:
        rodar_comando(["systemctl", "--user", "disable", "--now", ARQUIVO_TIMER])
    for caminho in caminhos:
        caminho.unlink(missing_ok=True)
    if sistema is Sistema.LINUX:
        rodar_comando(["systemctl", "--user", "daemon-reload"])


def instalado(sistema: Sistema, home: Path) -> bool:
    return all(c.exists() for c in arquivos(sistema, "", home))


def rodar_comando_do_sistema(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise BackendIndisponivel(f"{' '.join(cmd)}: {e}") from e
