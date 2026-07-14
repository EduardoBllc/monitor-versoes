"""Porte de internal/engine/reconstruir_lock_test.go."""

import datetime

from motor.adapters.git.fake import FakeGit
from motor.engine.deps import Deps
from motor.engine.reconstruir_lock import ReconstructStatus, reconstruir_lock
from motor.services.lock_store import LockStore


def test_reconstruir_lock_sem_anterior():
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("hash136", "", "base 13.6.0", t0)
    g.set_branch("13.6.0", "hash136")
    g.set_branch("13.7.0", "hash136")
    g.cherry_pick_x("origem1")

    resultado = reconstruir_lock(Deps(git=g, tasks=None), "13.7.0")

    assert (
        resultado.status == ReconstructStatus.DONE
    ), f"status = {resultado.status!r}, quer DONE"

    lock_store = LockStore(git=g)
    lock = lock_store.ler("13.7.0")
    assert len(lock.tasks["255514"].commits) == 1, f"tasks reconstruidas = {lock.tasks!r}"
