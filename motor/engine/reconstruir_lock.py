"""Porte de internal/engine/reconstruir_lock.go."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from motor.domain.types import Exclusion
from motor.engine.deps import Deps
from motor.errors import MotorError
from motor.services.base_resolver import BaseResolver
from motor.services.lock_store import LockStore


class ReconstructStatus(IntEnum):
    DONE = 0
    PENDING_JUDGMENT = 1


@dataclass
class ReconstructResult:
    status: ReconstructStatus
    orfaos: list[Exclusion] = field(default_factory=list)


def reconstruir_lock(deps: Deps, versao: str) -> ReconstructResult:
    """Regenera VERSAO.lock a partir dos trailers quando ele e
    apagado/corrompido (§3). Nunca interativo - PENDING_JUDGMENT e um valor
    de retorno, quem pergunta ao humano e o front-end (§14).
    """
    lock_store = LockStore(git=deps.git, lock_dir=deps.lock_dir)

    anterior = None
    try:
        anterior = lock_store.ler(versao)
    except MotorError:
        pass

    base_resolver = BaseResolver(git=deps.git)
    base = base_resolver.resolve(versao)

    novo_lock, orfaos = lock_store.reconstruir(versao, base, versao, anterior)
    lock_store.escrever(versao, novo_lock)

    if len(orfaos) > 0:
        return ReconstructResult(status=ReconstructStatus.PENDING_JUDGMENT, orfaos=orfaos)
    return ReconstructResult(status=ReconstructStatus.DONE)
