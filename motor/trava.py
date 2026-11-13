"""Lock por clone, entre processos do motor (decisão 032).

Lock não bloqueante num arquivo fora do clone: `flock` no Linux/macOS,
`msvcrt.locking` no Windows. O lock é do descritor aberto, então morre com o
processo — inclusive por `kill -9` — e o arquivo que sobra não trava nada.
Ninguém espera: quem encontra o lock ocupado recebe `RepoOcupado` na hora.
"""

from __future__ import annotations

import errno
import hashlib
import os
import sys
from pathlib import Path
from types import TracebackType

from motor.config import diretorio_dados
from motor.errors import MotorError, RepoOcupado

# `sys.platform == "win32"` literal, e não enum: é a única forma com que o mypy
# deixa de checar o ramo do outro sistema (que não tem `msvcrt`/`fcntl`).
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

# No Windows o lock é obrigatório: a região travada não pode ser lida por outro
# handle. O byte travado fica longe do pid, gravado no início do arquivo, para
# quem encontra o repo ocupado ainda conseguir ler quem o segura.
BYTE_TRAVADO_WINDOWS = 1 << 20


def diretorio_travas() -> Path:
    return Path(diretorio_dados()) / "travas"


def caminho_trava(caminho: str) -> Path:
    """Arquivo do lock do clone em `caminho`.

    O nome sai do caminho real: dois nomes de repo, ou dois caminhos que
    resolvem para o mesmo clone, caem no mesmo arquivo. Fora do clone para não
    sujar o `git status` nem depender do layout do `.git`.
    """
    chave = hashlib.sha256(os.path.realpath(caminho).encode()).hexdigest()[:16]
    return diretorio_travas() / f"{chave}.lock"


class Trava:
    """Lock segurado; `soltar` (ou a saída do `with`) o libera."""

    def __init__(self, fd: int) -> None:
        self._fd: int | None = fd

    def soltar(self) -> None:
        if self._fd is not None:
            fd, self._fd = self._fd, None
            try:
                # Ramo literal: ver o import do `msvcrt`.
                if sys.platform == "win32":
                    # O Windows solta o lock de handle fechado só quando puder;
                    # soltar explícito libera o repo já.
                    os.lseek(fd, BYTE_TRAVADO_WINDOWS, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            finally:
                os.close(fd)

    def __enter__(self) -> Trava:
        return self

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.soltar()


def travar(nome: str, caminho: str) -> Trava:
    """Toma o lock do clone ou levanta `RepoOcupado` sem esperar.

    O lock é por descritor aberto: dois `travar` no mesmo processo também se
    excluem, e é isso que recusa a segunda operação do daemon no mesmo repo. O
    fd de `os.open` não é herdável, então um `git` filho órfão não mantém o repo
    travado depois que o motor morre.
    """
    arquivo = caminho_trava(caminho)
    try:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(arquivo, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as e:
        raise MotorError(f"não foi possível abrir o lock {arquivo}: {e}") from e
    try:
        tomado = _tomar(fd)
    except OSError as e:
        os.close(fd)
        raise MotorError(f"não foi possível travar {arquivo}: {e}") from e
    if not tomado:
        pid = _ler_pid(fd)
        os.close(fd)
        raise RepoOcupado(nome, pid)
    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, f"{os.getpid()}\n".encode())
    except OSError as e:
        os.close(fd)
        raise MotorError(f"não foi possível gravar o lock {arquivo}: {e}") from e
    return Trava(fd)


def _tomar(fd: int) -> bool:
    """Tenta o lock sem esperar: `False` se outro o segura."""
    # Ramo literal: ver o import do `msvcrt`.
    if sys.platform == "win32":
        # `msvcrt.locking` trava a partir da posição atual do arquivo.
        os.lseek(fd, BYTE_TRAVADO_WINDOWS, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EDEADLOCK):
                return False
            raise
        return True
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _ler_pid(fd: int) -> int | None:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        return int(os.read(fd, 32).decode().strip())
    except OSError, UnicodeDecodeError, ValueError:
        return None
