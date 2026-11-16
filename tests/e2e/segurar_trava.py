"""Segura o lock do clone de um repo do cenário até o SIGTERM; imprime `pronto` ao travar."""

from __future__ import annotations

import signal
import sys
import threading

from motor.operacoes import repos_do_ambiente, travar_repo

PRONTO = "pronto"


def main(nome: str) -> None:
    repo = next(r for r in repos_do_ambiente() if r.nome == nome)
    parar = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: parar.set())
    trava = travar_repo(repo)
    if trava is None:
        raise SystemExit(f"repo {nome} sem checkout: nada a travar")
    with trava:
        print(PRONTO, flush=True)
        parar.wait()


if __name__ == "__main__":
    main(sys.argv[1])
