"""Porte de internal/engine/verificar.go."""

from __future__ import annotations

import logging
import time

from motor.adapters.commitsource.bitbucket import (
    BitbucketPRCommitSource,
    parse_workspace_repo,
)
from motor.adapters.commitsource.chain import ChainCommitSource
from motor.adapters.commitsource.grep import GrepCommitSource
from motor.domain.reconcile import filtrar_excluidos, reconciliar
from motor.domain.types import CommitRef, VersionStatus, Presence
from motor.engine.deps import Deps
from motor.ports import CommitSource
from motor.services.lock_store import LockStore
from motor.services.presence_oracle import PresenceOracle
from motor.services.target_resolver import TargetResolver

logger = logging.getLogger(__name__)


def _montar_commit_source(deps: Deps) -> CommitSource:
    """Grep em master é o fallback sempre disponível. Com token do Bitbucket,
    a PR (merged) vira a fonte primária: ordem = prioridade (§CommitSource).
    """
    grep = GrepCommitSource(git=deps.git)
    if not deps.bitbucket_token:
        return grep
    workspace, repo = parse_workspace_repo(deps.git.remote_url("origin"))
    pr = BitbucketPRCommitSource(
        token=deps.bitbucket_token,
        email=deps.bitbucket_email,
        workspace=workspace,
        repo=repo,
        git=deps.git,
    )
    return ChainCommitSource(sources=[pr, grep])


def verificar(deps: Deps, versao: str) -> VersionStatus:
    """Implementa a operacao read-only do §5: cruza ClickUp x lock x git
    e retorna o VersionStatus. Nao muta dados do usuario - so avanca (fast-
    forward) a branch local ate o que ja esta publicado no remoto, pra nao
    cruzar contra um estado desatualizado (ex.: incremento rodado em outra
    maquina).
    """
    inicio = time.monotonic()
    deps.git.fetch("origin")
    deps.git.use_worktree(versao)
    if deps.git.remote_branch_exists("origin", versao):
        deps.git.pull_branch("origin", versao)

    resolver = TargetResolver(tasks=deps.tasks, commits=_montar_commit_source(deps))
    alvo = resolver.resolve(versao)
    logger.debug("resolver.resolve: %.3fs", time.monotonic() - inicio)

    t = time.monotonic()
    lock_store = LockStore(git=deps.git, lock_dir=deps.lock_dir)
    lock = lock_store.ler(versao)
    logger.debug("lock_store.ler: %.3fs", time.monotonic() - t)

    alvo_filtrado = filtrar_excluidos(alvo, lock.excluidos)

    todos_os_hashes: dict[str, CommitRef] = {}
    candidatos_conflito: dict[str, bool] = {}
    for tt in alvo_filtrado.values():
        for c in tt.commits:
            todos_os_hashes[c.hash_origem] = c
            candidatos_conflito[c.hash_origem] = True
    for tt in lock.tasks.values():
        for c in tt.commits:
            if c.hash_origem not in todos_os_hashes:
                todos_os_hashes[c.hash_origem] = c

    oracle = PresenceOracle(git=deps.git)
    tip = deps.git.resolve_ref(versao)

    t = time.monotonic()
    presentes: dict[str, Presence] = {}
    conflitantes: list[CommitRef] = []
    suspeitos_conteudo: list[CommitRef] = []
    for hash_, c in todos_os_hashes.items():
        p = oracle.presente(hash_, lock.base.commit, versao)
        presentes[hash_] = p
        # predict_merge e o nivel 4 (msg+arquivos) so fazem sentido pra commits
        # que sao candidatos reais de cherry-pick (lado alvo) - conflitantes e
        # suspeitos_conteudo sao subconjunto de faltantes (VersionStatus), nunca
        # de commits sumidos so-no-lock.
        if p == Presence.AUSENTE and candidatos_conflito.get(hash_):
            if oracle.suspeita_por_conteudo(hash_, lock.base.commit, versao) is not None:
                suspeitos_conteudo.append(c)
            meta = deps.git.commit_meta(hash_)
            pred = deps.git.predict_merge(meta.parent, tip, hash_)
            if pred.conflita:
                conflitantes.append(c)
    logger.debug(
        "oraculo de presenca: %.3fs (%d commits)", time.monotonic() - t, len(todos_os_hashes)
    )

    logger.debug("verificar total: %.3fs", time.monotonic() - inicio)
    return reconciliar(alvo_filtrado, lock, presentes, conflitantes, suspeitos_conteudo)
