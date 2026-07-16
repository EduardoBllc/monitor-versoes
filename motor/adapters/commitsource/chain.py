"""ChainCommitSource: fontes em lista, ordem = prioridade.

Primeira fonte que devolve commits não-vazios ganha a task; as demais só
veem o que sobrou (pendentes). Não mistura fontes numa mesma task, pra
evitar dedup entre hash e patch-id. Composite: é ele mesmo um CommitSource,
então o TargetResolver não muda.
"""

from __future__ import annotations

from dataclasses import dataclass

from motor.domain.types import TargetSet, TaskTarget
from motor.ports import CommitSource


@dataclass
class ChainCommitSource:
    sources: list[CommitSource]  # ordem = prioridade

    def resolve(self, tasks: list[TaskTarget]) -> TargetSet:
        resultado: TargetSet = {}
        pendentes = list(tasks)
        for src in self.sources:
            if not pendentes:
                break
            achados = src.resolve(pendentes)
            for chamado, tt in achados.items():
                if tt.commits:
                    resultado[chamado] = tt
            pendentes = [t for t in pendentes if t.chamado not in resultado]
        return resultado
