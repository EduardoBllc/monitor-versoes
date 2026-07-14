"""Porte de internal/engine/incrementar_test.go."""

import datetime

from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import TaskTarget
from motor.engine.deps import Deps
from motor.engine.incrementar import (
    IncrementStatus,
    incrementar,
    incrementar_continue,
)
from motor.services.lock_store import LockStore


def _service_lock_store(g: FakeGit) -> LockStore:
    return LockStore(git=g)


def _setup_incremento_basico() -> tuple[FakeGit, FakeTaskSource]:
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("master", "origem1")
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")
    g.write_file(
        "13.7.0",
        "VERSAO.lock",
        b"""{
        "versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
        "tasks":{}
        }""",
        "lock inicial",
    )

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")]
    return g, tasks


def test_incrementar_aplica_tudo():
    g, tasks = _setup_incremento_basico()

    resultado = incrementar(Deps(git=g, tasks=tasks), "13.7.0")

    assert resultado.status == IncrementStatus.DONE, f"status = {resultado.status!r}, quer DONE"

    lock_store = _service_lock_store(g)
    lock = lock_store.ler("13.7.0")
    assert (
        len(lock.tasks["255514"].commits) == 1
    ), f"lock apos incrementar = {lock.tasks!r}"


def test_incrementar_para_em_conflito():
    g, tasks = _setup_incremento_basico()
    g.conflict_on["origem1"] = True

    resultado = incrementar(Deps(git=g, tasks=tasks), "13.7.0")

    assert (
        resultado.status == IncrementStatus.BLOCKED
    ), f"status = {resultado.status!r}, quer BLOCKED"
    assert resultado.blocked_commit == "origem1", (
        f"blocked_commit = {resultado.blocked_commit!r}, quer origem1"
    )


def test_incrementar_continue_registra_no_lock():
    g, tasks = _setup_incremento_basico()
    g.conflict_on["origem1"] = True

    incrementar(Deps(git=g, tasks=tasks), "13.7.0")

    resultado = incrementar_continue(Deps(git=g, tasks=tasks), "13.7.0")

    assert resultado.status == IncrementStatus.DONE, f"status = {resultado.status!r}, quer DONE"

    lock_store = _service_lock_store(g)
    lock = lock_store.ler("13.7.0")
    assert (
        len(lock.tasks["255514"].commits) == 1
    ), f"lock apos continue = {lock.tasks!r}"


def test_incrementar_continue_preserva_commits_anteriores():
    """Cobre um lote de 2 commits onde o SEGUNDO conflita. O primeiro ja foi
    cherry-picked pra branch (e so nao esta no lock ainda, porque incrementar
    escreve o lock em lote, no fim). incrementar_continue precisa recuperar
    OS DOIS commits do git (via LockStore.reconstruir), nao so o que acabou de
    ser resolvido - senao o registro do primeiro chamado se perde pra sempre
    do lock, mesmo estando correto no historico do git.
    """
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    t1 = t0 + datetime.timedelta(minutes=1)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("origem2", "origem1", "fix: ch255515 outra correcao VB-9999", t1)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("master", "origem2")
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")
    g.write_file(
        "13.7.0",
        "VERSAO.lock",
        b"""{
        "versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
        "tasks":{}
        }""",
        "lock inicial",
    )
    g.conflict_on["origem2"] = True

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [
        TaskTarget(chamado="255514", task="VB-2354", titulo="Logs"),
        TaskTarget(chamado="255515", task="VB-9999", titulo="Outra"),
    ]

    resultado = incrementar(Deps(git=g, tasks=tasks), "13.7.0")
    assert resultado.status == IncrementStatus.BLOCKED and resultado.blocked_commit == "origem2", (
        f"resultado inicial = {resultado!r}, quer BLOCKED em origem2"
    )

    resultado = incrementar_continue(Deps(git=g, tasks=tasks), "13.7.0")
    assert resultado.status == IncrementStatus.DONE, f"status = {resultado.status!r}, quer DONE"

    lock_store = _service_lock_store(g)
    lock = lock_store.ler("13.7.0")
    assert len(lock.tasks["255514"].commits) == 1, (
        f"lock.tasks[255514] = {lock.tasks['255514']!r}, "
        "o commit aplicado antes do conflito nao pode se perder"
    )
    assert (
        len(lock.tasks["255515"].commits) == 1
    ), f"lock.tasks[255515] = {lock.tasks['255515']!r}, quer 1 commit"
