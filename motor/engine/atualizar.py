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


class AtualizarStatus(IntEnum):
    DONE = 0
    BLOCKED = 1


@dataclass
class AtualizarResult:
    status: AtualizarStatus
    blocked_commit: str = ""
    arquivos_conflito: list[str] = field(default_factory=list)
    # commits cherry-picked nesta invocacao (vazio = nada a fazer)
    aplicados: list[CommitRef] = field(default_factory=list)
    # commits que ja estavam no historico (ancestrais, sem cherry-pick a fazer)
    ja_presentes: int = 0


def atualizar(deps: Deps, versao: str) -> AtualizarResult:
    """Aplica os commits faltantes por commit-date asc (§5). So adiciona
    historia - e o unico modo permitido quando a versao ja tem tag (§6, checado
    pelo chamador via services.PublicationGate antes de decidir entre criar e
    atulizar).
    """
    status = verificar(deps, versao)

    if status.suspeitos_conteudo:
        hashes = ", ".join(c.hash_origem[:8] for c in status.suspeitos_conteudo)
        raise MotorError(
            "commits suspeitos de cherry-pick manual com conteudo divergente "
            f"(mesma mensagem e arquivos ja existem no alvo, sem trailer -x): {hashes}. "
            "Confirme manualmente (exclua do lock se ja aplicado) antes de rodar atualizar de novo."
        )

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
                        motivo="ja presente no historico (sem cherry-pick a fazer)",
                        reason=ExclusionReason.AUTOMATICA,
                    )
                )
        lock = replace(lock, excluidos=excluidos)

    deps.git.use_worktree(versao)

    aplicados: list[CommitRef] = []
    ja_presentes = len(status.ancestrais)
    t = time.monotonic()
    for c in faltam:
        outcome = deps.git.cherry_pick_x(c.hash_origem)
        if outcome == CherryPickOutcome.CONFLITO:
            paths = deps.git.conflicted_paths()
            if len(paths) == 0:
                # rerere.autoUpdate resolveu sozinho (§8) - segue o pick.
                deps.git.continue_cherry_pick()
                lock = _registrar_commit(lock, c)
                aplicados.append(c)
                continue
            return AtualizarResult(
                status=AtualizarStatus.BLOCKED,
                blocked_commit=c.hash_origem,
                arquivos_conflito=paths,
                aplicados=aplicados,
                ja_presentes=ja_presentes,
            )
        lock = _registrar_commit(lock, c)
        aplicados.append(c)
    logger.debug("cherry-pick de %d commits: %.3fs", len(faltam), time.monotonic() - t)

    lock_store.escrever(versao, lock)
    # publica so apos o lote fechar sem conflito (§6, "branch compartilhada") -
    # um lote BLOCKED fica so local ate resolver e rodar de novo.
    deps.git.push_branch("origin", versao)
    # a worktree e so um checkout local descartavel - o que importa (commits,
    # lock) ja esta na branch e no remoto. use_worktree recria sob demanda.
    deps.git.worktree_remove(versao)
    return AtualizarResult(status=AtualizarStatus.DONE, aplicados=aplicados, ja_presentes=ja_presentes)


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


def atualizar_continue(deps: Deps, versao: str) -> AtualizarResult:
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

    return atualizar(deps, versao)


def atualizar_abort(deps: Deps, versao: str) -> None:
    deps.git.use_worktree(versao)
    deps.git.abort_cherry_pick()
    deps.git.worktree_remove(versao)
