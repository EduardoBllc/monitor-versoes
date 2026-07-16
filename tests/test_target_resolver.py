"""TargetResolver: casa tasks (TaskSource) com commits (CommitSource) e
garante que toda task buscada sobrevive ao alvo, mesmo sem commit."""

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import CommitRef, TaskTarget
from motor.services.target_resolver import TargetResolver


def _tasks():
    fake = FakeTaskSource()
    fake.tasks["13.7.0"] = [TaskTarget(chamado="5514", task="VB-2354", titulo="Logs")]
    return fake


def test_resolver_preenche_commits_da_fonte():
    commits = FakeCommitSource(por_chamado={"5514": [CommitRef(hash_origem="c1")]})
    resultado = TargetResolver(tasks=_tasks(), commits=commits).resolve("13.7.0")

    tt = resultado.get("5514")
    assert tt is not None and len(tt.commits) == 1 and tt.commits[0].hash_origem == "c1", (
        f"resultado = {resultado!r}"
    )


def test_resolver_emite_task_vazia_quando_nenhuma_fonte_acha():
    # sem isso a task sem commit some do alvo e verificar nunca a pinta vermelha.
    resultado = TargetResolver(tasks=_tasks(), commits=FakeCommitSource()).resolve("13.7.0")

    tt = resultado.get("5514")
    assert tt is not None, f"task sem commit deveria sobreviver ao alvo: {resultado!r}"
    assert tt.commits == [], f"esperava commits vazios, veio {tt.commits!r}"
    assert tt.task == "VB-2354" and tt.titulo == "Logs", f"metadados perdidos: {tt!r}"
