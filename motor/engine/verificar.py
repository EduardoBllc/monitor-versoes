"""Porte de internal/engine/verificar.go."""

from __future__ import annotations

from motor.domain.reconcile import filtrar_excluidos, reconciliar
from motor.domain.types import CommitRef, VersionStatus
from motor.engine.deps import Deps
from motor.services.lock_store import LockStore
from motor.services.presence_oracle import PresenceOracle
from motor.services.target_resolver import TargetResolver


def verificar(deps: Deps, versao: str) -> VersionStatus:
    """Implementa a operacao read-only do §5: cruza ClickUp x lock x git
    e retorna o VersionStatus. Nunca muta nada.
    """
    resolver = TargetResolver(tasks=deps.tasks, git=deps.git)
    alvo = resolver.resolve(versao)

    lock_store = LockStore(git=deps.git)
    lock = lock_store.ler(versao)

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

    presentes: dict[str, bool] = {}
    conflitantes: list[CommitRef] = []
    for hash_, c in todos_os_hashes.items():
        ok = oracle.presente(hash_, lock.base.ref, versao)
        presentes[hash_] = ok
        # predict_merge so faz sentido pra commits que sao candidatos reais de
        # cherry-pick (lado alvo) - conflitantes e subconjunto de faltantes
        # (VersionStatus), nunca de commits sumidos so-no-lock.
        if not ok and candidatos_conflito.get(hash_):
            meta = deps.git.commit_meta(hash_)
            pred = deps.git.predict_merge(meta.parent, tip, hash_)
            if pred.conflita:
                conflitantes.append(c)

    return reconciliar(alvo_filtrado, lock, presentes, conflitantes)
