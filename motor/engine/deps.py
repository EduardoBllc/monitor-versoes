"""Dependencias injetadas nas operacoes."""

from __future__ import annotations

from dataclasses import dataclass

from motor.ports import CommitSource, EstadoRepo, GitRepo, TaskSource
from motor.progresso import RelatorProgresso, silencioso


@dataclass
class Deps:
    git: GitRepo
    tasks: TaskSource
    estado: EstadoRepo
    repo: str = ""  # nome canonico do repo, resolvido no front-end
    # Canal de progresso. O default silencioso e a propria flag: quem nao
    # passa relator nao paga nada, e nenhum comando precisa de --progresso
    # para funcionar. Chega aos services e adapters por construtor, nunca
    # por assinatura de porta (ver motor/progresso.py).
    progresso: RelatorProgresso = silencioso
    # Montada pelo front-end (motor.montagem.montar_commit_source), nunca pelo
    # engine: e o que mantem o engine vendo so `motor.ports`. Opcional porque
    # `consulta`, `reconstruir-estado` e `atualizar --abort` nunca resolvem
    # commits — o `verificar` cobra a ausencia quando precisa dela.
    commit_source: CommitSource | None = None
