"""Double em memória de CommitSource, para testes de services/engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from motor.domain.types import CommitRef, TargetSet, TaskTarget


@dataclass
class FakeCommitSource:
    # chamado -> commits que esta fonte "acha".
    por_chamado: dict[str, list[CommitRef]] = field(default_factory=dict)
    err: Exception | None = None

    def resolve(self, tasks: list[TaskTarget]) -> TargetSet:
        if self.err is not None:
            raise self.err
        out: TargetSet = {}
        for t in tasks:
            commits = self.por_chamado.get(t.chamado)
            if commits:
                out[t.chamado] = TaskTarget(
                    chamado=t.chamado, task=t.task, titulo=t.titulo, commits=commits
                )
        return out
