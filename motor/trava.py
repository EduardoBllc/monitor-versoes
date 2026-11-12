"""Lock por clone, entre processos do motor (decisão 032).

`flock` não bloqueante num arquivo fora do clone. O lock é do descritor aberto,
então morre com o processo — inclusive por `kill -9` — e o arquivo que sobra
não trava nada. Ninguém espera: quem encontra o lock ocupado recebe
`RepoOcupado` na hora.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
from pathlib import Path
from types import TracebackType

from motor.config import diretorio_dados
from motor.errors import MotorError, RepoOcupado


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

    O `flock` é por descrição de arquivo aberto: dois `travar` no mesmo
    processo também se excluem, e é isso que recusa a segunda operação do
    daemon no mesmo repo. O fd de `os.open` não é herdável, então um `git`
    filho órfão não mantém o repo travado depois que o motor morre.
    """
    arquivo = caminho_trava(caminho)
    try:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(arquivo, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as e:
        raise MotorError(f"não foi possível abrir o lock {arquivo}: {e}") from e
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        pid = _ler_pid(fd)
        os.close(fd)
        raise RepoOcupado(nome, pid) from None
    except OSError as e:
        os.close(fd)
        raise MotorError(f"não foi possível travar {arquivo}: {e}") from e
    try:
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{os.getpid()}\n".encode(), 0)
    except OSError as e:
        os.close(fd)
        raise MotorError(f"não foi possível gravar o lock {arquivo}: {e}") from e
    return Trava(fd)


def _ler_pid(fd: int) -> int | None:
    try:
        return int(os.pread(fd, 32, 0).decode().strip())
    except OSError, UnicodeDecodeError, ValueError:
        return None
