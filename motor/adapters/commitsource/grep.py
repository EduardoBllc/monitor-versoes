"""GrepCommitSource: descobre commits varrendo mensagens de master.

Move a lógica que vivia no TargetResolver — uma chamada só de `git log`
com o --grep de todos os chamados/VB-ids juntos (git faz OR entre --grep),
depois match exato por word-boundary (search_commits só traz candidatos
brutos). Frágil por natureza: depende do dev ter escrito o ID certo na
mensagem. É a fonte de fallback; o Bitbucket (PR) é a primária.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from motor.domain.commits import match_exato, ordenar_por_data
from motor.domain.types import TargetSet, TaskTarget
from motor.ports import GitRepo


@dataclass
class GrepCommitSource:
    git: GitRepo
    ref: str = "origin/master"

    def resolve(self, tasks: list[TaskTarget]) -> TargetSet:
        if not tasks:
            return {}

        padroes: list[str] = []
        for t in tasks:
            if t.chamado:
                padroes.append("ch" + t.chamado)
            if t.task:
                padroes.append(t.task)

        candidatos = self.git.search_commits(padroes, self.ref)

        resultado: TargetSet = {}
        for t in tasks:
            commits = ordenar_por_data(match_exato(candidatos, t.chamado, t.task))
            if not commits:
                continue
            # search_commits nao sabe de chamado/task/titulo - carimba aqui.
            commits = [
                replace(c, chamado=t.chamado, task=t.task, titulo=t.titulo) for c in commits
            ]
            resultado[t.chamado] = TaskTarget(
                chamado=t.chamado, task=t.task, titulo=t.titulo, commits=commits
            )
        return resultado
