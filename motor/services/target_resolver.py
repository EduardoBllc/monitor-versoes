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
        """Busca as tasks e casa cada uma com seus commits via CommitSource
        (§4). A descoberta em si (grep em master, PR do Bitbucket, ...) é
        plugável — aqui só orquestra e garante que TODA task buscada apareça
        no alvo, mesmo sem commit, pra `verificar` poder pintá-la vermelha
        (falso-verde de task sem entrega).
        """
        try:
            tasks = self.tasks.fetch(versao)
        except Exception as e:
            raise MotorError(f"buscando tasks: {e}") from e

        if not tasks:
            return {}

        try:
            achados = self.commits.resolve(tasks)
        except Exception as e:
            raise MotorError(f"buscando commits das tasks: {e}") from e

        resultado: TargetSet = {}
        for t in tasks:
            tt = achados.get(t.chamado)
            resultado[t.chamado] = (
                tt
                if tt is not None and tt.commits
                else TaskTarget(chamado=t.chamado, task=t.task, titulo=t.titulo, commits=[])
            )
        return resultado
