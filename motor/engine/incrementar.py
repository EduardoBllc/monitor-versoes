"""Porte de internal/engine/incrementar.go."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from enum import IntEnum

from motor.domain.commits import ordenar_por_data
from motor.domain.types import CommitRef, Lock, TargetSet, TaskTarget, Exclusion, ExclusionReason
from motor.engine.deps import Deps
from motor.engine.verificar import verificar
from motor.errors import MotorError
from motor.ports import CherryPickOutcome
from motor.services.lock_store import LockStore

logger = logging.getLogger(__name__)


class IncrementStatus(IntEnum):
    DONE = 0
    BLOCKED = 1


@dataclass
class IncrementResult:
    status: IncrementStatus
    blocked_commit: str = ""
    arquivos_conflito: list[str] = field(default_factory=list)


def incrementar(deps: Deps, versao: str) -> IncrementResult:
    """Aplica os commits faltantes por commit-date asc (§5). So adiciona
    historia - e o unico modo permitido quando a versao ja tem tag (§6, checado
    pelo chamador via services.PublicationGate antes de decidir entre criar e
    incrementar).
    """
    status = verificar(deps, versao)

    faltam = ordenar_por_data(status.faltantes)
    lock_store = LockStore(git=deps.git, lock_dir=deps.lock_dir)
    lock = lock_store.ler(versao)

    if status.ancestrais:
        excluidos = list(lock.excluidos)
        ja_excluidos = {e.commit for e in excluidos}
        for c in status.ancestrais:
            if c.hash_origem not in ja_excluidos:
                excluidos.append(
                    Exclusion(
                        commit=c.hash_origem,
                        chamado=c.chamado,
                        motivo=f"ja presente na base {lock.base.ref}",
                        reason=ExclusionReason.AUTOMATICA,
                    )
                )
        lock = replace(lock, excluidos=excluidos)

    deps.git.use_worktree(versao)

    t = time.monotonic()
    for c in faltam:
        outcome = deps.git.cherry_pick_x(c.hash_origem)
        if outcome == CherryPickOutcome.CONFLITO:
            paths = deps.git.conflicted_paths()
            if len(paths) == 0:
                # rerere.autoUpdate resolveu sozinho (§8) - segue o pick.
                deps.git.continue_cherry_pick()
                lock = _registrar_commit(lock, c)
                continue
            return IncrementResult(
                status=IncrementStatus.BLOCKED,
                blocked_commit=c.hash_origem,
                arquivos_conflito=paths,
            )
        lock = _registrar_commit(lock, c)
    logger.debug("cherry-pick de %d commits: %.3fs", len(faltam), time.monotonic() - t)

    lock_store.escrever(versao, lock)
    return IncrementResult(status=IncrementStatus.DONE)


def _registrar_commit(lock: Lock, c: CommitRef) -> Lock:
    tasks: TargetSet = dict(lock.tasks)
    tt = tasks.get(c.chamado, TaskTarget())
    tasks[c.chamado] = TaskTarget(
        chamado=c.chamado,
        task=c.task or tt.task,
        titulo=c.titulo or tt.titulo,
        commits=[*tt.commits, c],
    )
    return replace(lock, tasks=tasks)


def incrementar_continue(deps: Deps, versao: str) -> IncrementResult:
    """Retoma um cherry-pick pendente resolvido manualmente (checkpoint
    resumivel, §8). E uma invocacao nova do CLI - sem contexto em memoria de
    quais commits do lote ja foram aplicados antes do conflito, por isso usa
    LockStore.reconstruir (varre base..branch de verdade) pra recompor o lock
    inteiro antes de continuar o lote.
    """
    deps.git.use_worktree(versao)
    _, ok = deps.git.pending_cherry_pick()
    if not ok:
        raise MotorError("nenhum cherry-pick pendente pra continuar")

    deps.git.continue_cherry_pick()

    lock_store = LockStore(git=deps.git, lock_dir=deps.lock_dir)
    anterior = lock_store.ler(versao)

    # O lote (§5) so escreve o lock no fim de um lote bem-sucedido - se o
    # conflito que trouxe a gente aqui aconteceu no meio de um lote, os
    # commits anteriores a ele ja foram cherry-picked pra branch mas ainda nao
    # estao no lock. reconstruir varre base..branch de verdade (git) e
    # recupera todos eles de uma vez, em vez de registrar so o commit que
    # acabou de ser resolvido.
    lock, _ = lock_store.reconstruir(versao, anterior.base, versao, anterior)
    lock_store.escrever(versao, lock)

    return incrementar(deps, versao)


def incrementar_abort(deps: Deps, versao: str) -> None:
    deps.git.use_worktree(versao)
    deps.git.abort_cherry_pick()
