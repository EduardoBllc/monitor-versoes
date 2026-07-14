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
            raise MotorError(f"buscando tasks: {e}") from e

        if not tasks:
            return {}

        # Uma chamada so de `git log` com o --grep de todas as tasks juntos
        # (git faz OR entre --grep por padrao) em vez de uma por task: o
        # filtro continua do lado do git (saida so com o que bate, do mesmo
        # tamanho de antes mesmo em historico grande) - so troca N walks do
        # historico de master por 1.
        padroes_uniao: list[str] = []
        for t in tasks:
            padroes_uniao.append("ch" + t.chamado)
            padroes_uniao.append(t.task)
        try:
            candidatos_uniao = self.git.search_commits(padroes_uniao, "master")
        except Exception as e:
            raise MotorError(f"buscando commits das tasks: {e}") from e

        resultado: TargetSet = {}
        for t in tasks:
            commits = match_exato(candidatos_uniao, t.chamado, t.task)
            commits = ordenar_por_data(commits)
            # search_commits nao sabe de chamado/task/titulo - carimba aqui,
            # unico lugar que sabe pra qual task esta busca era (evita perder
            # o dado ao achatar TaskTarget.commits em CommitRef mais adiante,
            # ex. Faltantes).
            commits = [replace(c, chamado=t.chamado, task=t.task, titulo=t.titulo) for c in commits]
            resultado[t.chamado] = TaskTarget(
                chamado=t.chamado, task=t.task, titulo=t.titulo, commits=commits
            )
        return resultado
