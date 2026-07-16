"""Porte de internal/services/lock_store_test.go."""

import datetime

from motor.adapters.git.fake import FakeGit
from motor.domain.types import (
    BaseRef,
    CommitRef,
    Exclusion,
    ExclusionReason,
    Lock,
    TaskTarget,
    VersionType,
)
from motor.services.lock_store import LockStore


def test_lock_store_escrever_e_ler(tmp_path):
    g = FakeGit()
    store = LockStore(git=g, lock_dir=str(tmp_path))

    original = Lock(
        versao="13.7.0",
        tipo=VersionType.AJUSTADA,
        base=BaseRef(ref="13.6.0", commit="571fea583e"),
        tasks={
            "255514": TaskTarget(
                chamado="255514",
                task="VB-2354",
                titulo="Logs pedidos ecommerce",
                commits=[CommitRef(hash_origem="d1a0ff9450")],
            )
        },
        excluidos=[
            Exclusion(commit="83cd5cb8a2", chamado="251099", motivo="ja presente na base 13.6.0")
        ],
        tasks_sem_entrega=["270001"],
    )

    store.escrever("13.7.0", original)
    lido = store.ler("13.7.0")

    assert lido.tasks_sem_entrega == ["270001"], f"tasks_sem_entrega lida = {lido.tasks_sem_entrega!r}"

    assert lido.versao == "13.7.0" and lido.tipo == VersionType.AJUSTADA, f"lock lido = {lido!r}"
    assert lido.base.ref == "13.6.0" and lido.base.commit == "571fea583e", f"base lida = {lido.base!r}"

    tt = lido.tasks.get("255514")
    assert (
        tt is not None and len(tt.commits) == 1 and tt.commits[0].hash_origem == "d1a0ff9450"
    ), f"tasks lidas = {lido.tasks!r}"

    assert (
        len(lido.excluidos) == 1 and lido.excluidos[0].commit == "83cd5cb8a2"
    ), f"excluidos lidos = {lido.excluidos!r}"


def test_lock_store_reconstruir_reagrupa_por_trailer(tmp_path):
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")
    g.cherry_pick_x("origem1")

    store = LockStore(git=g, lock_dir=str(tmp_path))
    lock, orfaos = store.reconstruir("13.7.0", BaseRef(ref="13.6.0"), "13.7.0", None)

    assert len(orfaos) == 0, f"orfaos = {orfaos!r}, quer nenhum (sem lock anterior)"

    tt = lock.tasks.get("255514")
    assert (
        tt is not None and len(tt.commits) == 1 and tt.commits[0].hash_origem == "origem1"
    ), f"tasks reconstruidas = {lock.tasks!r}"


def test_lock_store_reconstruir_retorna_orfaos_de_julgamento(tmp_path):
    g = FakeGit()
    g.add_commit("base-tip", "", "base", datetime.datetime.now(datetime.timezone.utc))
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")

    anterior = Lock(
        excluidos=[
            Exclusion(
                commit="revertido1",
                chamado="999999",
                motivo="revertido depois",
                reason=ExclusionReason.JULGAMENTO,
            ),
            Exclusion(
                commit="auto1",
                chamado="888888",
                motivo="ja presente na base",
                reason=ExclusionReason.AUTOMATICA,
            ),
        ]
    )

    store = LockStore(git=g, lock_dir=str(tmp_path))
    _, orfaos = store.reconstruir("13.7.0", BaseRef(ref="13.6.0"), "13.7.0", anterior)

    assert (
        len(orfaos) == 1 and orfaos[0].commit == "revertido1"
    ), f"orfaos = {orfaos!r}, quer so a exclusao por julgamento"


def test_lock_store_reconstruir_ordena_commits_por_data(tmp_path):
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    t1 = t0 + datetime.timedelta(hours=1)
    g.add_commit("origem1", "", "fix: ch255514 primeira parte", t0)
    g.add_commit("origem2", "", "fix: ch255514 segunda parte", t1)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")
    g.cherry_pick_x("origem1")
    g.cherry_pick_x("origem2")

    store = LockStore(git=g, lock_dir=str(tmp_path))
    lock, _ = store.reconstruir("13.7.0", BaseRef(ref="13.6.0"), "13.7.0", None)

    commits = lock.tasks["255514"].commits
    assert len(commits) == 2, f"esperava 2 commits, veio {commits!r}"
    assert (
        commits[0].hash_origem == "origem1" and commits[1].hash_origem == "origem2"
    ), f"ordem = [{commits[0].hash_origem}, {commits[1].hash_origem}], quer [origem1, origem2] (commit_date asc)"
