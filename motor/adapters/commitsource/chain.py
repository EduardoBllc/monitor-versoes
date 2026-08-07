"""ChainCommitSource: fontes em lista, ordem = prioridade.

Primeira fonte que devolve commits não-vazios ganha a task; as demais só
veem o que sobrou (pendentes). Não mistura fontes numa mesma task, pra
evitar dedup entre hash e patch-id. Composite: é ele mesmo um CommitSource,
então o TargetResolver não muda.
"""

from __future__ import annotations

from dataclasses import dataclass

from motor.domain.types import CommitRef
from motor.ports import CommitSource


@dataclass
class ChainCommitSource:
    sources: list[CommitSource]  # ordem = prioridade

    def resolve(self, chamados: list[str]) -> dict[str, list[CommitRef]]:
        resultado: dict[str, list[CommitRef]] = {}
        pendentes = list(chamados)
        for src in self.sources:
            if not pendentes:
                break
            for chamado, commits in src.resolve(pendentes).items():
                if commits:
                    resultado[chamado] = commits
            pendentes = [c for c in pendentes if c not in resultado]
        return resultado
