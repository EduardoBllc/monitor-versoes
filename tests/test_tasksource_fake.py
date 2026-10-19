"""Porte de internal/adapters/tasksource/fake_test.go."""

import pytest

from motor.adapters.tasksource.fake import FakeTaskSource


def test_fake_task_source_fetch():
    f = FakeTaskSource()
    f.chamados["13.7.0"] = ["255514"]

    chamados = f.fetch("13.7.0")

    assert chamados == ["255514"], f"chamados = {chamados!r}"


def test_fake_task_source_erro():
    f = FakeTaskSource()
    f.err = RuntimeError("falha simulada")

    with pytest.raises(RuntimeError):
        f.fetch("13.7.0")
