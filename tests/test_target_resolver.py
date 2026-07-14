"""Porte de internal/services/target_resolver_test.go."""

import datetime

from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import TaskTarget
from motor.services.target_resolver import TargetResolver


def test_target_resolver_resolve():
    fake_git = FakeGit()
    base = datetime.datetime.now(datetime.timezone.utc)
    fake_git.add_commit("origem1", "", "fix: ch5514 corrige logs", base)
    fake_git.add_commit(
        "origem2", "origem1", "fix: ch55140 chamado diferente e nao relacionado", base
    )
    fake_git.set_branch("master", "origem2")

    fake_tasks = FakeTaskSource()
    fake_tasks.tasks["13.7.0"] = [
        TaskTarget(chamado="5514", task="VB-2354", titulo="Logs pedidos ecommerce")
    ]

    resolver = TargetResolver(tasks=fake_tasks, git=fake_git)
    resultado = resolver.resolve("13.7.0")

    tt = resultado.get("5514")
    assert tt is not None, "esperava chamado 5514 no resultado"
    assert (
        len(tt.commits) == 1 and tt.commits[0].hash_origem == "origem1"
    ), f"commits = {tt.commits!r}, quer so origem1"
