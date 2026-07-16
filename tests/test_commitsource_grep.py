"""GrepCommitSource: descoberta por --grep em master + match exato."""

import datetime

from motor.adapters.commitsource.grep import GrepCommitSource
from motor.adapters.git.fake import FakeGit
from motor.domain.types import TaskTarget


def test_grep_acha_chamado_exato_nao_substring():
    g = FakeGit()
    base = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch5514 corrige logs", base)
    g.add_commit("origem2", "origem1", "fix: ch55140 chamado diferente", base)
    g.set_branch("master", "origem2")

    fonte = GrepCommitSource(git=g)
    resultado = fonte.resolve([TaskTarget(chamado="5514", task="VB-2354", titulo="Logs")])

    tt = resultado.get("5514")
    assert tt is not None, f"esperava 5514 no resultado: {resultado!r}"
    assert (
        len(tt.commits) == 1 and tt.commits[0].hash_origem == "origem1"
    ), f"commits = {tt.commits!r}, quer so origem1 (ch5514 exato, nao ch55140)"


def test_grep_omite_task_sem_commit():
    g = FakeGit()
    g.set_branch("master", "")

    fonte = GrepCommitSource(git=g)
    resultado = fonte.resolve([TaskTarget(chamado="9999", task="VB-9", titulo="Nada")])

    assert resultado == {}, f"task sem commit nao deveria aparecer: {resultado!r}"
