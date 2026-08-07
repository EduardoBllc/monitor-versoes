"""Porte de internal/services/target_resolver.go."""

from __future__ import annotations

from dataclasses import dataclass

from motor.domain.types import TargetSet, TaskTarget
from motor.errors import MotorError
from motor.ports import CommitSource, TaskSource


@dataclass
class TargetResolver:
    tasks: TaskSource
    commits: CommitSource

    def resolve(self, versao: str) -> TargetSet:
        try:
            chamados = self.tasks.fetch(versao)
        except Exception as e:
            raise MotorError(f"buscando tasks: {e}") from e

        if not chamados:
            return {}

        try:
            achados = self.commits.resolve(chamados)
        except Exception as e:
            raise MotorError(f"buscando commits das tasks: {e}") from e

        return {
            ch: TaskTarget(chamado=ch, marcada=versao, commits=achados.get(ch, []))
            for ch in chamados
        }
