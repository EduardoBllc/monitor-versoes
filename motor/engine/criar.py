"""Porte de internal/engine/criar.go."""

from __future__ import annotations

from motor.domain.types import Lock, TargetSet
from motor.domain.version import inferir_tipo
from motor.engine.deps import Deps
from motor.engine.incrementar import IncrementResult, incrementar
from motor.errors import MotorError
from motor.services.base_resolver import BaseResolver
from motor.services.lock_store import LockStore
from motor.services.publication_gate import PublicationGate


def criar(deps: Deps, versao: str) -> IncrementResult:
    """Monta uma versao do zero (§5). Branch nova e nao publicada - rebuild
    idempotente e permitido ate a primeira publicacao (§6), mas esta operacao
    so cria; recriar do zero e responsabilidade do chamador (remover a
    worktree antes de chamar criar de novo).
    """
    gate = PublicationGate(git=deps.git)
    if gate.publicada(versao):
        raise MotorError(f"versao {versao} ja publicada - use incrementar")

    base_resolver = BaseResolver(git=deps.git)
    base = base_resolver.resolve(versao)

    deps.git.worktree_add(versao, base.commit)
    deps.git.write_file(versao, "VERSAO", f"{versao}\n".encode(), f"Atualiza VERSAO para {versao}")

    tipo = inferir_tipo(versao)
    lock_store = LockStore(git=deps.git, lock_dir=deps.lock_dir)
    lock_inicial = Lock(versao=versao, tipo=tipo, base=base, tasks=TargetSet())
    lock_store.escrever(versao, lock_inicial)

    return incrementar(deps, versao)
