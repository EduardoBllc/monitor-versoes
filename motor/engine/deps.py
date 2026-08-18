"""Dependencias injetadas nas operacoes."""

from __future__ import annotations

from dataclasses import dataclass

from motor.ports import CommitSource, EstadoRepo, GitRepo, TaskSource


@dataclass
class Deps:
    git: GitRepo
    tasks: TaskSource
    estado: EstadoRepo
    repo: str = ""  # nome canonico do repo, resolvido no __main__
    bitbucket_token: str = ""  # se presente, PR do Bitbucket vira fonte primaria
    bitbucket_email: str = ""  # email da conta dona do token (Basic auth)
    # injetavel nos testes; em producao e montado por _montar_commit_source
    _commit_source: CommitSource | None = None
