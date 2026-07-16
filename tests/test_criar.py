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


def test_criar_nova_versao(tmp_path):
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("hash136", "", "base 13.6.0", t0)
    g.set_branch("master", "origem1")
    g.set_branch("13.6.0", "hash136")

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")]

    resultado = criar(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")

    assert resultado.status == IncrementStatus.DONE, f"status = {resultado.status!r}, quer DONE"
    assert "13.7.0" in g.branches, "esperava branch 13.7.0 criada"
    assert g.remotes.get("13.7.0") is True, "esperava push da branch nova pro remoto"
    assert g.read_file("13.7.0", "VERSAO") == b"13.7.0\n", "esperava arquivo VERSAO com a versao"


def test_criar_nao_publica_se_bloqueada_por_conflito(tmp_path):
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("hash136", "", "base 13.6.0", t0)
    g.set_branch("master", "origem1")
    g.set_branch("13.6.0", "hash136")
    g.conflict_on["origem1"] = True

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")]

    resultado = criar(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")

    assert resultado.status == IncrementStatus.BLOCKED, f"status = {resultado.status!r}, quer BLOCKED"
    assert "13.7.0" not in g.remotes, "nao esperava push com composicao bloqueada por conflito"


def test_criar_falha_se_ja_publicada(tmp_path):
    g = FakeGit()
    g.tags["13.7.0"] = True
    tasks = FakeTaskSource()

    with pytest.raises(MotorError):
        criar(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")
