"""Porte de internal/engine/verificar_test.go."""

import datetime

from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import TaskTarget
from motor.engine.deps import Deps
from motor.engine.verificar import verificar
from motor.ports import MergePrediction


def test_verificar_verde_quando_tudo_aplicado():
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("master", "origem1")
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")
    g.cherry_pick_x("origem1")
    g.write_file(
        "13.7.0",
        "VERSAO.lock",
        b"""{
        "versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
        "tasks":{"255514":{"task":"VB-2354","titulo":"Logs","commits":["origem1"]}}
        }""",
        "lock inicial",
    )

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")]

    status = verificar(Deps(git=g, tasks=tasks), "13.7.0")

    assert status.verde, f"esperava verde, status = {status!r}"


def test_verificar_faltante():
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("master", "origem1")
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")
    g.write_file(
        "13.7.0",
        "VERSAO.lock",
        b"""{
        "versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
        "tasks":{}
        }""",
        "lock vazio",
    )

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")]

    status = verificar(Deps(git=g, tasks=tasks), "13.7.0")

    assert not status.verde, "nao deveria ser verde"
    assert (
        len(status.faltantes) == 1 and status.faltantes[0].hash_origem == "origem1"
    ), f"faltantes = {status.faltantes!r}"


def test_verificar_sumido_nunca_entra_em_conflitantes():
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
    g.write_file(
        "13.7.0",
        "VERSAO.lock",
        b"""{
        "versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
        "tasks":{
            "255514":{"task":"VB-2354","titulo":"Logs","commits":["origem1"]},
            "999999":{"task":"","titulo":"Removida","commits":["sumido1"]}
        }
        }""",
        "lock inicial",
    )
    g.merge_predictions["sumido1"] = MergePrediction(conflita=True, arquivos_conflito=[])

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")]

    status = verificar(Deps(git=g, tasks=tasks), "13.7.0")

    assert status.commits_sumidos == [
        "sumido1"
    ], f"commits_sumidos = {status.commits_sumidos!r}, quer [sumido1]"
    for c in status.conflitantes:
        assert c.hash_origem != "sumido1", (
            f"sumido1 nao deveria aparecer em conflitantes: {status.conflitantes!r}"
        )
