"""Porte de internal/domain/reconcile_test.go."""

from motor.domain.reconcile import filtrar_excluidos, reconciliar
from motor.domain.types import CommitRef, Exclusion, Lock, TargetSet, TaskTarget, Presence


def mk_target_set(chamado: str, task: str, *hashes: str) -> TargetSet:
    commits = [CommitRef(hash_origem=h) for h in hashes]
    return {chamado: TaskTarget(chamado=chamado, task=task, commits=commits)}


def test_reconciliar_verde():
    alvo = mk_target_set("255514", "VB-2354", "hash1")
    lock = Lock(tasks=mk_target_set("255514", "VB-2354", "hash1"))
    presentes = {"hash1": Presence.TRAILER}

    status = reconciliar(alvo, lock, presentes, [])

    assert status.verde, f"esperava verde, status = {status!r}"


def test_reconciliar_task_nova():
    alvo = mk_target_set("255514", "VB-2354", "hash1")
    lock = Lock(tasks={})
    presentes = {"hash1": Presence.TRAILER}

    status = reconciliar(alvo, lock, presentes, [])

    assert not status.verde, "nao deveria ser verde com task nova"
    assert status.tasks_novas == ["255514"], f"tasks_novas = {status.tasks_novas}, quer [255514]"


def test_reconciliar_task_removida():
    alvo: TargetSet = {}
    lock = Lock(tasks=mk_target_set("255514", "VB-2354", "hash1"))
    presentes = {"hash1": Presence.TRAILER}

    status = reconciliar(alvo, lock, presentes, [])

    assert status.tasks_removidas == ["255514"], f"tasks_removidas = {status.tasks_removidas}, quer [255514]"


def test_reconciliar_lock_nao_integro():
    alvo = mk_target_set("255514", "VB-2354", "hash1")
    lock = Lock(tasks=mk_target_set("255514", "VB-2354", "hash1"))
    presentes: dict[str, Presence] = {}  # hash1 nao presente

    status = reconciliar(alvo, lock, presentes, [])

    assert not status.lock_integro, "esperava lock_integro=False"
    assert status.commits_sumidos == ["hash1"], f"commits_sumidos = {status.commits_sumidos}, quer [hash1]"
    assert len(status.faltantes) == 1, f"faltantes = {status.faltantes!r}, quer 1 item"


def test_filtrar_excluidos():
    alvo = mk_target_set("251099", "VB-2549", "hashA", "hashB")
    excluidos = [Exclusion(commit="hashA", chamado="251099", motivo="ja presente na base")]

    filtrado = filtrar_excluidos(alvo, excluidos)

    commits = filtrado["251099"].commits
    assert len(commits) == 1 and commits[0].hash_origem == "hashB", f"commits apos filtro = {commits!r}, quer so hashB"
