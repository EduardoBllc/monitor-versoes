"""TaskSource que entrega a versão-alvo já buscada em paralelo com o `git fetch`."""

from __future__ import annotations

from concurrent.futures import Future, wait
from dataclasses import dataclass

from motor.ports import TaskSource


@dataclass(frozen=True)
class TarefasAdiantadas:
    fonte: TaskSource
    alvo: str
    adiantada: Future[list[str]]

    def fetch(self, versao: str, /) -> list[str]:
        if versao == self.alvo:
            return self.adiantada.result()
        # A porta não exige thread-safety: a fonte só volta a ser chamada com a
        # busca adiantada terminada.
        wait([self.adiantada])
        return self.fonte.fetch(versao)
