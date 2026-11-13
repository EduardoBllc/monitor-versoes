"""Helpers de `Deps` sobre `FakeGit` com um pick em conflito, para os testes do conflito."""

from __future__ import annotations

import datetime

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.conflito import Estagios
from motor.domain.types import CommitRef, RepoInfo
from motor.engine.atualizar import atualizar
from motor.engine.deps import Deps
from motor.ports import ProvedorSugestao
from tests.fontes_falsas import REFERENCIA_CH
from tests.versionamento import ESCALONADO_COMPOSTA

D = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
VERSAO = "13.7.0"
CHAMADO = "255514"
MENSAGEM = "ch255514 corrige logs"
CONTEUDO = "conteudo.txt"
APAGADO = "apagado.txt"
COM_MARCADOR = "a\n<<<<<<< HEAD\nb\n=======\nc\n>>>>>>> a0\n"
ESTAGIOS = {
    CONTEUDO: Estagios("a\n", "a\nb\n", "a\nc\n", COM_MARCADOR, binario=False),
    APAGADO: Estagios("x\n", None, "y\n", "y\n", binario=False),
}
DOIS = "dois.txt"
DISCO_DOIS = (
    "topo\n<<<<<<< HEAD\nA1\n=======\nB1\n>>>>>>> a0\nmeio mesclado\n"
    "<<<<<<< HEAD\nA2\n||||||| base\nO2\n=======\nB2\n>>>>>>> a0\nfim\n"
)
ESTAGIOS_DOIS = {
    **ESTAGIOS,
    DOIS: Estagios(
        base="topo\nO1\nmeio mesclado\nO2\nfim\n",
        ours="topo\nA1\nmeio mesclado\nA2\nfim\n",
        theirs="topo\nB1\nmeio mesclado\nB2\nfim\n",
        disco=DISCO_DOIS,
        binario=False,
    ),
}
UM = {
    CHAMADO: [
        CommitRef(
            hash_origem="a0", parent="m0", chamado=CHAMADO, commit_date=D, msg=MENSAGEM
        )
    ]
}


def git_falso(mensagem: str = MENSAGEM) -> FakeGit:
    g = FakeGit()
    g.add_commit("m0", "", "raiz", D)
    g.add_commit("a0", "m0", mensagem, D)
    g.set_branch("master", "a0")
    g.set_branch("origin/master", "a0")
    g.set_branch("13.6.0", "m0")
    g.set_branch(VERSAO, "m0")
    return g


def deps_falsas(g: FakeGit, provedor: ProvedorSugestao | None = None) -> Deps:
    return Deps(
        versionamento=ESCALONADO_COMPOSTA,
        git=g,
        tasks=FakeTaskSource(chamados={VERSAO: [CHAMADO]}),
        estado=FakeEstado(repos={"r": RepoInfo(nome="r")}),
        repo="r",
        commit_source=FakeCommitSource(por_chamado=UM),
        referencia=lambda: REFERENCIA_CH,
        sugestao=lambda: provedor,
    )


def deps_em_conflito(
    *,
    mensagem: str = MENSAGEM,
    provedor: ProvedorSugestao | None = None,
    estagios: dict[str, Estagios] = ESTAGIOS,
) -> Deps:
    g = git_falso(mensagem)
    g.conflict_on["a0"] = True
    g.estagios_on["a0"] = estagios
    deps = deps_falsas(g, provedor)
    atualizar(deps, VERSAO)
    return deps
