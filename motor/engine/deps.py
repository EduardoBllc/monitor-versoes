"""Dependencias injetadas nas operacoes."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass

from motor.domain.referencia import FonteReferencia, Referencia, resolver_referencia
from motor.ports import CommitSource, EstadoRepo, GitRepo, TaskSource
from motor.progresso import RelatorProgresso, silencioso
from motor.services.versionamento import (
    BRANCH_VERSAO_PADRAO,
    PRINCIPAL_PADRAO,
    FonteVersionamento,
    versionamento_padrao,
)


def _sem_referencia() -> Referencia:
    """Sem proposta nem config, como a lista manual sem `[referencia]`."""
    return resolver_referencia(None, None, ())


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
    # Quantas worktrees de versao ficam em disco depois da operacao. O default 0
    # e o comportamento historico (checkout descartado a cada run) e mantem os
    # testes de engine falando de uma worktree so; o default de produto sai de
    # WORKTREES_MANTIDAS, lido em motor.montagem — o engine nao ve ambiente.
    worktrees_mantidas: int = 0
    # Esquema, politica, piso e nomes de branch e de tag, resolvidos so por
    # quem usa: plugin inexistente na config nao pode derrubar `atualizar --abort`.
    versionamento: FonteVersionamento = versionamento_padrao
    # Template da branch da versao e principal so das camadas config e padrao
    # (`nomes_sem_esquema`): o `atualizar --abort` acha a worktree sem
    # resolver o `versionamento`.
    nomes_abort: tuple[str, str] = (BRANCH_VERSAO_PADRAO, PRINCIPAL_PADRAO)
    # Relógio injetável: a validade do carimbo da verificação depende dele.
    agora: Callable[[], datetime.datetime] = lambda: datetime.datetime.now(datetime.UTC)
    # Referencia de tarefa (padrao e alfabeto), resolvida so por quem a usa: a
    # falta de padrao nao pode derrubar `atualizar --abort`. Quem usa o default
    # cobra a falta do padrao.
    referencia: FonteReferencia = _sem_referencia
    # Fontes, referencia e piso desta invocacao, montados no front-end: o
    # carimbo da verificacao so vale para as mesmas entradas.
    identidade_das_entradas: str = ""
