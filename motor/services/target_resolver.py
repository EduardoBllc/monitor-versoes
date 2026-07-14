"""Porte de internal/services/target_resolver.go."""

from __future__ import annotations

from dataclasses import dataclass, replace

from motor.domain.commits import match_exato, ordenar_por_data
from motor.domain.types import TargetSet, TaskTarget
from motor.errors import MotorError
from motor.ports import GitRepo, TaskSource


@dataclass
class TargetResolver:
    tasks: TaskSource
    git: GitRepo

    def resolve(self, versao: str) -> TargetSet:
        """Busca as tasks no ClickUp e casa cada uma com seus commits em
        master (§4). Desambiguacao multi-projeto (§11) e implicita:
        search_commits so acha commits que existem *neste* repo.
        """
        try:
            tasks = self.tasks.fetch(versao)
        except Exception as e:
            raise MotorError(f"buscando tasks no ClickUp: {e}") from e

        resultado: TargetSet = {}
        for t in tasks:
            padroes = ["ch" + t.chamado, t.task]
            try:
                candidatos = self.git.search_commits(padroes, "master")
            except Exception as e:
                raise MotorError(f"buscando commits do chamado {t.chamado}: {e}") from e
            commits = match_exato(candidatos, t.chamado, t.task)
            commits = ordenar_por_data(commits)
            # search_commits nao sabe de chamado/task - carimba aqui, unico
            # lugar que sabe pra qual task esta busca era (evita perder o
            # dado ao achatar TaskTarget.commits em CommitRef mais adiante,
            # ex. Faltantes).
            commits = [replace(c, chamado=t.chamado, task=t.task) for c in commits]
            resultado[t.chamado] = TaskTarget(
                chamado=t.chamado, task=t.task, titulo=t.titulo, commits=commits
            )
        return resultado
