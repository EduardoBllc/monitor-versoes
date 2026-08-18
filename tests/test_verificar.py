from __future__ import annotations

import datetime

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import Atribuicao, CommitRef, RepoInfo, VersaoInfo, VersionType
from motor.engine.deps import Deps
from motor.engine.verificar import verificar
from motor.ports import MergePrediction

D = datetime.datetime(2026, 1, 1)


def _deps(git, tasks, commits, estado) -> Deps:
    return Deps(git=git, tasks=tasks, estado=estado, repo="r", _commit_source=commits)


def _estado_com_repo() -> FakeEstado:
    return FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})


def _git(tags: dict[str, bool] | None = None) -> FakeGit:
    """Grafo: m0 e a raiz; a0 e um commit que so existe no master.

    As versoes ficam em m0, entao a0 e faltante em todas elas — e o que
    permite afirmar que o commit foi cobrado, e nao herdado da base.
    """
    git = FakeGit(tags=tags or {})
    git.add_commit("m0", "", "raiz", D)
    git.add_commit("a0", "m0", "ch123123 alfa", D)
    git.set_branch("master", "a0")
    git.set_branch("origin/master", "a0")
    for versao in ("13.33.1", "13.34.0", "14.0.0"):
        git.set_branch(versao, "m0")
    return git


def test_verificar_une_tarefas_das_versoes_abertas_menores():
    git = _git()
    tasks = FakeTaskSource(chamados={"13.33.1": ["123123"], "14.0.0": []})
    commits = FakeCommitSource(por_chamado={
        "123123": [CommitRef(hash_origem="a0", parent="m0", chamado="123123",
                             commit_date=D, msg="ch123123 alfa")]
    })
    estado = _estado_com_repo()
    # base gravada na criacao: m0. Sem isso o BaseResolver resolveria "master",
    # que hoje aponta para a0 — e o commit apareceria como ja presente.
    estado.registrar_versao("r", VersaoInfo(numero="14.0.0", tipo=VersionType.FECHADA,
                                            base_ref="master", base_commit="m0"))

    status = verificar(_deps(git, tasks, commits, estado), "14.0.0")

    # marcada para 13.33.1, cobrada na 14.0.0
    assert [c.hash_origem for c in status.faltantes] == ["a0"]


def test_verificar_congela_versao_quando_a_tag_aparece():
    git = _git(tags={"13.34.0": True})
    estado = _estado_com_repo()
    estado.registrar_versao("r", VersaoInfo(numero="13.34.0", tipo=VersionType.AJUSTADA,
                                            base_ref="13.33.0", base_commit="m0"))
    estado.substituir_atribuicoes("r", "13.34.0", [
        Atribuicao(chamado="123456", marcada="13.34.0", estado="aplicado",
                   commits=["a0"])
    ])

    status = verificar(_deps(git, FakeTaskSource(), FakeCommitSource(), estado),
                       "13.34.0")

    assert estado.versao("r", "13.34.0").liberada_em is not None
    # devolve o snapshot congelado, nao recalcula
    assert status.verde is True
    assert status.tasks_novas == []


def test_verificar_nao_grava_em_versao_liberada():
    git = _git(tags={"13.34.0": True})
    estado = _estado_com_repo()
    estado.registrar_versao("r", VersaoInfo(numero="13.34.0", tipo=VersionType.AJUSTADA,
                                            base_ref="13.33.0", base_commit="m0"))
    tasks = FakeTaskSource(chamados={"13.34.0": ["999111"]})

    verificar(_deps(git, tasks, FakeCommitSource(), estado), "13.34.0")

    # a trava do fake nao disparou => nao tentou escrever
    assert estado.atribuicoes("r", "13.34.0") == []


def test_verificar_commit_sumido_do_estado_nunca_entra_em_conflitantes():
    """Invariante documentada em VersionStatus: `conflitantes` e subconjunto de
    `faltantes` (lado alvo), nunca de `commits_sumidos`. Commit que so o estado
    conhecia e que sumiu do alvo nao e candidato a cherry-pick, entao
    predict_merge nao pode nem ser consultado para ele.

    Herdado do teste equivalente contra o lock: sem ele a guarda
    `hash_ in candidatos_conflito` do verificar fica sem cobertura. Os dois
    commits tem conflito plantado de proposito — assim a assercao distingue
    "a guarda funciona" de "nenhum commit conflita".
    """
    git = _git()
    git.add_commit("sumido", "", "ch999999 tarefa que saiu do Tickio", D)
    git.merge_predictions["a0"] = MergePrediction(conflita=True, arquivos_conflito=[])
    git.merge_predictions["sumido"] = MergePrediction(
        conflita=True, arquivos_conflito=[]
    )
    tasks = FakeTaskSource(chamados={"14.0.0": ["123123"]})
    commits = FakeCommitSource(por_chamado={
        "123123": [CommitRef(hash_origem="a0", parent="m0", chamado="123123",
                             commit_date=D, msg="ch123123 alfa")]
    })
    estado = _estado_com_repo()
    estado.registrar_versao("r", VersaoInfo(numero="14.0.0", tipo=VersionType.FECHADA,
                                            base_ref="master", base_commit="m0"))
    estado.substituir_atribuicoes("r", "14.0.0", [
        Atribuicao(chamado="999999", marcada="14.0.0", estado="aplicado",
                   commits=["sumido"])
    ])

    status = verificar(_deps(git, tasks, commits, estado), "14.0.0")

    assert status.commits_sumidos == ["sumido"]
    assert status.estado_integro is False
    assert [c.hash_origem for c in status.conflitantes] == ["a0"]


def test_verificar_ignora_tag_de_versao_que_o_motor_nunca_viu():
    git = _git(tags={"13.33.1": True})
    estado = _estado_com_repo()
    estado.registrar_versao("r", VersaoInfo(numero="14.0.0", tipo=VersionType.FECHADA,
                                            base_ref="master", base_commit="m0"))

    verificar(_deps(git, FakeTaskSource(), FakeCommitSource(), estado), "14.0.0")

    # nada a congelar: sem linha no estado, nao ha snapshot para proteger
    assert estado.versao("r", "13.33.1") is None
