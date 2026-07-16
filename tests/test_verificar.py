"""Porte de internal/engine/verificar_test.go."""

import datetime

from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import TaskTarget
from motor.engine.deps import Deps
from motor.engine.verificar import verificar
from motor.ports import MergePrediction


def test_verificar_verde_quando_tudo_aplicado(tmp_path):
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("master", "origem1")
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")
    g.cherry_pick_x("origem1")
    (tmp_path / "13.7.0.lock").write_bytes(
        b"""{
        "versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
        "tasks":{"255514":{"task":"VB-2354","titulo":"Logs","commits":["origem1"]}}
        }"""
    )

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")]

    status = verificar(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")

    assert status.verde, f"esperava verde, status = {status!r}"
    assert g.pulled == [], "sem branch remota, verificar nao deveria puxar nada"


def test_verificar_puxa_remoto_quando_branch_publicada(tmp_path):
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("master", "origem1")
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")
    g.remotes["13.7.0"] = True
    (tmp_path / "13.7.0.lock").write_bytes(
        b"""{
        "versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
        "tasks":{}
        }"""
    )

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")]

    verificar(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")

    assert g.pulled == ["13.7.0"], "branch ja publicada, esperava pull antes de verificar"


def test_verificar_faltante(tmp_path):
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("master", "origem1")
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")
    (tmp_path / "13.7.0.lock").write_bytes(
        b"""{
        "versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
        "tasks":{}
        }"""
    )

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")]

    status = verificar(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")

    assert not status.verde, "nao deveria ser verde"
    assert (
        len(status.faltantes) == 1 and status.faltantes[0].hash_origem == "origem1"
    ), f"faltantes = {status.faltantes!r}"


def test_verificar_task_sem_commit_nao_verde(tmp_path):
    # task no ClickUp pra versao, mas nenhum commit achado em master: vermelho.
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("master", "base-tip")
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")
    (tmp_path / "13.7.0.lock").write_bytes(
        b"""{
        "versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
        "tasks":{}
        }"""
    )

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")]

    status = verificar(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")

    assert not status.verde, "task sem commit nao pode sair verde"
    assert status.tasks_sem_commits == ["255514"], f"tasks_sem_commits = {status.tasks_sem_commits}"


def test_verificar_task_sem_entrega_reconhecida_fica_verde(tmp_path):
    # escape hatch: chamado listado em tasks_sem_entrega no lock (edicao manual).
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("master", "base-tip")
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")
    (tmp_path / "13.7.0.lock").write_bytes(
        b"""{
        "versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
        "tasks":{},"tasks_sem_entrega":["255514"]
        }"""
    )

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [TaskTarget(chamado="255514", task="VB-2354", titulo="Sem entrega aqui")]

    status = verificar(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")

    assert status.tasks_sem_commits == [], f"reconhecida nao deveria entrar: {status.tasks_sem_commits}"
    assert status.verde, f"esperava verde com escape hatch, status = {status!r}"


def test_verificar_sumido_nunca_entra_em_conflitantes(tmp_path):
    """Cobre o invariante documentado em VersionStatus: conflitantes e
    subconjunto de faltantes (lado alvo), nunca de commits sumidos so-no-lock.
    Um commit ausente do git E do alvo atual nao e candidato real de
    cherry-pick, entao mesmo com uma previsao de conflito configurada pra
    ele, PredictMerge nao deveria nem ser chamado.
    """
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("base-tip", "", "base", t0)
    g.add_commit("sumido1", "", "fix: ch999999 tarefa removida do clickup", t0)
    g.set_branch("master", "origem1")
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")
    g.cherry_pick_x("origem1")
    (tmp_path / "13.7.0.lock").write_bytes(
        b"""{
        "versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
        "tasks":{
            "255514":{"task":"VB-2354","titulo":"Logs","commits":["origem1"]},
            "999999":{"task":"","titulo":"Removida","commits":["sumido1"]}
        }
        }"""
    )
    g.merge_predictions["sumido1"] = MergePrediction(conflita=True, arquivos_conflito=[])

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")]

    status = verificar(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")

    assert status.commits_sumidos == [
        "sumido1"
    ], f"commits_sumidos = {status.commits_sumidos!r}, quer [sumido1]"
    for c in status.conflitantes:
        assert c.hash_origem != "sumido1", (
            f"sumido1 nao deveria aparecer em conflitantes: {status.conflitantes!r}"
        )
