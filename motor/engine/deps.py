"""Dependencias injetadas nas operacoes."""

from __future__ import annotations

from dataclasses import dataclass, field

from motor.ports import CommitSource, EstadoRepo, GitRepo, TaskSource
from motor.progresso import RelatorProgresso, silencioso


@dataclass
class Deps:
    git: GitRepo
    tasks: TaskSource
    estado: EstadoRepo
    repo: str = ""  # nome canonico do repo, resolvido no __main__
    # repr=False: o par email:token e a credencial Basic do Bitbucket — um repr
    # de Deps (sob --debug, ou no repr de uma excecao) a imprimiria em claro.
    bitbucket_token: str = field(default="", repr=False)  # se presente, PR do Bitbucket vira fonte primaria
    bitbucket_email: str = field(default="", repr=False)  # email da conta dona do token (Basic auth)
    # Canal de progresso. O default silencioso e a propria flag: quem nao
    # passa relator nao paga nada, e nenhum comando precisa de --progresso
    # para funcionar. Chega aos services e adapters por construtor, nunca
    # por assinatura de porta (ver motor/progresso.py).
    progresso: RelatorProgresso = silencioso
    # injetavel nos testes; em producao e montado por _montar_commit_source
    _commit_source: CommitSource | None = None
