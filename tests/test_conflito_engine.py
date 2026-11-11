"""Testes do engine do conflito de 3 vias, com `Deps` sobre `FakeGit`."""

from __future__ import annotations

import datetime
from dataclasses import replace

import pytest

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.conflito import Estagios, TipoArquivo
from motor.domain.types import CommitRef, RepoInfo
from motor.engine.atualizar import atualizar
from motor.engine.conflito import (
    ArquivoDoConflito,
    ler_arquivo,
    ler_conflito,
    reabrir_arquivo,
    resolver_arquivo,
)
from motor.engine.deps import Deps
from motor.errors import ErroDeEntrada, NaoEncontrado, VersaoDesatualizada
from tests.fontes_falsas import REFERENCIA_CH
from tests.versionamento import ESCALONADO_COMPOSTA

D = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
VERSAO = "13.7.0"
CHAMADO = "255514"
MENSAGEM = "ch255514 corrige logs"
CONTEUDO = "conteudo.txt"
APAGADO = "apagado.txt"
COM_MARCADOR = "a\n<<<<<<< HEAD\nb\n=======\nc\n>>>>>>> a0\n"
RESOLVIDO = "a\nc\n"
MUDOU_FORA = "editado fora da web\n"
ESTAGIOS = {
    CONTEUDO: Estagios("a\n", "a\nb\n", "a\nc\n", COM_MARCADOR, binario=False),
    APAGADO: Estagios("x\n", None, "y\n", "y\n", binario=False),
}
UM = {
    CHAMADO: [
        CommitRef(
            hash_origem="a0", parent="m0", chamado=CHAMADO, commit_date=D, msg=MENSAGEM
        )
    ]
}


def _git() -> FakeGit:
    g = FakeGit()
    g.add_commit("m0", "", "raiz", D)
    g.add_commit("a0", "m0", MENSAGEM, D)
    g.set_branch("master", "a0")
    g.set_branch("origin/master", "a0")
    g.set_branch("13.6.0", "m0")
    g.set_branch(VERSAO, "m0")
    return g


def _deps(g: FakeGit) -> Deps:
    return Deps(
        versionamento=ESCALONADO_COMPOSTA,
        git=g,
        tasks=FakeTaskSource(chamados={VERSAO: [CHAMADO]}),
        estado=FakeEstado(repos={"r": RepoInfo(nome="r")}),
        repo="r",
        commit_source=FakeCommitSource(por_chamado=UM),
        referencia=lambda: REFERENCIA_CH,
    )


def _deps_em_conflito() -> Deps:
    g = _git()
    g.conflict_on["a0"] = True
    g.estagios_on["a0"] = ESTAGIOS
    deps = _deps(g)
    atualizar(deps, VERSAO)
    return deps


def test_ler_conflito_lista_arquivos_e_contexto():
    conflito = ler_conflito(_deps_em_conflito(), VERSAO)

    assert (conflito.commit, conflito.mensagem, conflito.chamado) == (
        "a0",
        MENSAGEM,
        CHAMADO,
    )
    assert sorted(conflito.arquivos, key=lambda a: a.caminho) == [
        ArquivoDoConflito(APAGADO, TipoArquivo.MODIFICADO_APAGADO, resolvido=False),
        ArquivoDoConflito(CONTEUDO, TipoArquivo.CONTEUDO, resolvido=False),
    ]


@pytest.mark.parametrize("caminho", ["outro.txt", "../a.txt", "/etc/passwd"])
def test_caminho_fora_do_pick_e_recusado(caminho: str):
    deps = _deps_em_conflito()

    with pytest.raises(NaoEncontrado):
        ler_arquivo(deps, VERSAO, caminho)
    with pytest.raises(NaoEncontrado):
        resolver_arquivo(deps, VERSAO, caminho, RESOLVIDO, "")
    with pytest.raises(NaoEncontrado):
        reabrir_arquivo(deps, VERSAO, caminho)


def test_sem_pick_pendente():
    with pytest.raises(NaoEncontrado):
        ler_conflito(_deps(_git()), VERSAO)


def test_resolver_recusa_disco_mudado():
    deps = _deps_em_conflito()
    lido = ler_arquivo(deps, VERSAO, CONTEUDO)
    assert isinstance(deps.git, FakeGit)
    # Edição fora da web num arquivo ainda pendente: muda só o disco do fake.
    deps.git._arquivos_pick[CONTEUDO] = replace(ESTAGIOS[CONTEUDO], disco=MUDOU_FORA)

    with pytest.raises(VersaoDesatualizada):
        resolver_arquivo(deps, VERSAO, CONTEUDO, RESOLVIDO, lido.versao_disco)
    assert ler_arquivo(deps, VERSAO, CONTEUDO).disco == MUDOU_FORA
    assert deps.git.arquivos_do_pick()[CONTEUDO] is False


def test_resolver_recusa_marcador():
    deps = _deps_em_conflito()
    lido = ler_arquivo(deps, VERSAO, CONTEUDO)

    with pytest.raises(ErroDeEntrada):
        resolver_arquivo(deps, VERSAO, CONTEUDO, COM_MARCADOR, lido.versao_disco)


def test_resolver_e_reabrir():
    deps = _deps_em_conflito()

    def resolvido() -> bool:
        return {a.caminho: a.resolvido for a in ler_conflito(deps, VERSAO).arquivos}[
            CONTEUDO
        ]

    with pytest.raises(ErroDeEntrada):
        reabrir_arquivo(deps, VERSAO, CONTEUDO)

    lido = ler_arquivo(deps, VERSAO, CONTEUDO)
    resolver_arquivo(deps, VERSAO, CONTEUDO, RESOLVIDO, lido.versao_disco)
    assert resolvido()
    assert ler_arquivo(deps, VERSAO, CONTEUDO).disco == RESOLVIDO

    reabrir_arquivo(deps, VERSAO, CONTEUDO)
    assert not resolvido()
    assert ler_arquivo(deps, VERSAO, CONTEUDO).disco == COM_MARCADOR
