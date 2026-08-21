from __future__ import annotations

import datetime

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import Atribuicao, RepoInfo, VersaoInfo
from motor.engine.consultar import consultar
from motor.engine.deps import Deps


def _deps(git: FakeGit, estado: FakeEstado) -> Deps:
    return Deps(git=git, tasks=FakeTaskSource(), estado=estado, repo="r",
                _commit_source=FakeCommitSource())


def _estado(atribuicoes: list[Atribuicao]) -> FakeEstado:
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})
    estado.registrar_versao("r", VersaoInfo(numero="13.34.0"))
    estado.substituir_atribuicoes("r", "13.34.0", atribuicoes)
    return estado


def test_ordena_pelo_commit_de_origem_mais_recente():
    # O repo de estado devolve por chamado (ordem alfabetica: 100, 25, 9), que
    # nao e nem a ordem numerica nem a cronologica. A consulta reordena.
    git = FakeGit()
    git.add_commit("a1", "", "ch9 antigo", datetime.datetime(2026, 1, 1))
    git.add_commit("b1", "", "ch25 novo", datetime.datetime(2026, 3, 1))
    git.add_commit("c1", "", "ch100 meio", datetime.datetime(2026, 2, 1))
    estado = _estado([
        Atribuicao(chamado="9", marcada="13.34.0", commits=["a1"]),
        Atribuicao(chamado="25", marcada="13.34.0", commits=["b1"]),
        Atribuicao(chamado="100", marcada="13.34.0", commits=["c1"]),
    ])

    assert [c.chamado for c in consultar(_deps(git, estado), "13.34.0")] == [
        "25",
        "100",
        "9",
    ]


def test_chamado_usa_o_commit_mais_novo_que_tem():
    git = FakeGit()
    git.add_commit("a1", "", "ch9 um", datetime.datetime(2026, 1, 1))
    git.add_commit("a2", "", "ch9 dois", datetime.datetime(2026, 5, 1))
    git.add_commit("b1", "", "ch25 so", datetime.datetime(2026, 3, 1))
    estado = _estado([
        Atribuicao(chamado="9", marcada="13.34.0", commits=["a1", "a2"]),
        Atribuicao(chamado="25", marcada="13.34.0", commits=["b1"]),
    ])

    assert [c.chamado for c in consultar(_deps(git, estado), "13.34.0")] == ["9", "25"]


def test_commit_sem_meta_vai_para_o_fim():
    # Hash ausente no git cai no fallback com commit_date = datetime.min.
    git = FakeGit()
    git.add_commit("b1", "", "ch25 so", datetime.datetime(2026, 3, 1))
    estado = _estado([
        Atribuicao(chamado="9", marcada="13.34.0", commits=["sumido"]),
        Atribuicao(chamado="25", marcada="13.34.0", commits=["b1"]),
    ])

    resultado = consultar(_deps(git, estado), "13.34.0")

    assert [c.chamado for c in resultado] == ["25", "9"]
    assert resultado[1].commits[0].msg == "mensagem indisponível"
