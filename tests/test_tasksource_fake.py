"""Porte de internal/adapters/tasksource/fake_test.go."""

import pytest

from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import TaskTarget


def test_fake_task_source_fetch():
    f = FakeTaskSource()
    f.tasks["13.7.0"] = [TaskTarget(chamado="255514", task="VB-2354")]

    tasks = f.fetch("13.7.0")

    assert len(tasks) == 1 and tasks[0].chamado == "255514", f"tasks = {tasks!r}"


def test_fake_task_source_erro():
    f = FakeTaskSource()
    f.err = Exception("falha simulada")

    with pytest.raises(Exception):
        f.fetch("13.7.0")
