"""Porte de internal/engine/criar_test.go."""

import datetime

import pytest

from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import TaskTarget
from motor.engine.criar import criar
from motor.engine.deps import Deps
from motor.engine.incrementar import IncrementStatus
from motor.errors import MotorError


def test_criar_nova_versao():
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("hash136", "", "base 13.6.0", t0)
    g.set_branch("master", "origem1")
    g.set_branch("13.6.0", "hash136")

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")]

    resultado = criar(Deps(git=g, tasks=tasks), "13.7.0")

    assert resultado.status == IncrementStatus.DONE, f"status = {resultado.status!r}, quer DONE"
    assert "13.7.0" in g.branches, "esperava branch 13.7.0 criada"


def test_criar_falha_se_ja_publicada():
    g = FakeGit()
    g.tags["13.7.0"] = True
    tasks = FakeTaskSource()

    with pytest.raises(MotorError):
        criar(Deps(git=g, tasks=tasks), "13.7.0")
