"""Testes do `criar`, agora contra o estado (nao ha mais lock)."""

from __future__ import annotations

import datetime

import pytest

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.atribuicoes import Exata
from motor.domain.types import CommitRef, RepoInfo
from motor.engine.atualizar import AtualizarStatus
from motor.engine.criar import criar
from motor.engine.deps import Deps
from motor.engine.verificar import situacao_das_versoes
from motor.errors import RecusaDeInvariante
from motor.esquemas.semver import Semver
from motor.services.catalogo import Catalogo
from motor.services.versionamento import Versionamento
from tests.versionamento import VENDABEM_COMPOSTA

D = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

UM = {
    "255514": [
        CommitRef(
            hash_origem="a0",
            parent="m0",
            chamado="255514",
            commit_date=D,
            msg="ch255514 corrige logs",
        )
    ]
}


class _GitQueTagueiaNoFetch(FakeGit):
    """FakeGit em que a tag da 13.7.0 so existe DEPOIS do fetch — como no git
    de verdade, onde `fetch` e o ponto em que a tag criada em outra maquina
    entra no ref store local.
    """

    def fetch(self, remote: str) -> None:
        super().fetch(remote)
        self.tags["13.7.0"] = True


def _git(classe: type[FakeGit] = FakeGit) -> FakeGit:
    """A 13.7.0 nao existe: e ela que o criar tem de montar. A 13.6.0 em m0 e a
    base inferida, e a0 (so no master) e o commit a cobrar.
    """
    g = classe()
    g.add_commit("m0", "", "raiz", D)
    g.add_commit("a0", "m0", "ch255514 corrige logs", D)
    g.set_branch("master", "a0")
    g.set_branch("origin/master", "a0")
    g.set_branch("13.6.0", "m0")
    return g


def _estado() -> FakeEstado:
    return FakeEstado(repos={"r": RepoInfo(nome="r")})


def _deps(git, estado) -> Deps:
    return Deps(
        versionamento=VENDABEM_COMPOSTA,
        git=git,
        tasks=FakeTaskSource(chamados={"13.7.0": ["255514"]}),
        estado=estado,
        repo="r",
        commit_source=FakeCommitSource(por_chamado=UM),
    )


def test_criar_nova_versao():
    g = _git()
    estado = _estado()

    resultado = criar(_deps(g, estado), "13.7.0")

    assert resultado.status == AtualizarStatus.DONE, (
        f"status = {resultado.status!r}, quer DONE"
    )
    assert "13.7.0" in g.branches, "esperava branch 13.7.0 criada"
    assert g.remotes.get("13.7.0") is True, "esperava push da branch nova pro remoto"
    assert g.read_file("13.7.0", "VERSAO") == b"13.7.0\n", (
        "esperava arquivo VERSAO com a versao"
    )

    gravada = estado.versao("r", "13.7.0")
    assert gravada is not None, "criar tem de registrar a versao no estado"
    # a base resolvida na criacao e a autoritativa dali em diante
    assert (gravada.base_ref, gravada.base_commit) == ("13.6.0", "m0")
    assert gravada.tipo == "ajustada"
    assert [
        (a.chamado, a.estado, a.commits) for a in estado.atribuicoes("r", "13.7.0")
    ] == [("255514", "aplicado", ["a0"])]


def test_criar_nao_publica_se_bloqueada_por_conflito():
    g = _git()
    g.conflict_on["a0"] = True
    estado = _estado()

    resultado = criar(_deps(g, estado), "13.7.0")

    assert resultado.status == AtualizarStatus.BLOCKED, (
        f"status = {resultado.status!r}, quer BLOCKED"
    )
    assert "13.7.0" not in g.remotes, (
        "nao esperava push com composicao bloqueada por conflito"
    )
    assert [a.estado for a in estado.atribuicoes("r", "13.7.0")] == ["pendente"], (
        "conflito nao resolvido nao pode virar atribuicao aplicada"
    )


def test_criar_falha_se_ja_publicada():
    g = _git()
    g.tags["13.7.0"] = True
    estado = _estado()

    with pytest.raises(RecusaDeInvariante):
        criar(_deps(g, estado), "13.7.0")

    assert "13.7.0" not in g.branches, "nao pode criar branch de versao ja publicada"


def test_criar_busca_antes_de_ler_a_publicacao():
    """A 13.7.0 foi liberada em outra maquina: a tag so aparece no fetch.

    Pina a ORDEM. Lendo as refs antes de buscar, a trava nao ve a tag e o criar
    segue em frente: cria branch, commita o VERSAO e registra a versao no
    estado — tudo em cima de uma versao que ja saiu.
    """
    g = _git(classe=_GitQueTagueiaNoFetch)
    estado = _estado()

    with pytest.raises(RecusaDeInvariante):
        criar(_deps(g, estado), "13.7.0")

    assert g.fetched == ["origin"]
    assert "13.7.0" not in g.branches
    assert estado.versao("r", "13.7.0") is None


# -- branch da versao por template (critério 8 da #115) -----------------------

_RELEASE = Versionamento(
    esquema=Semver(),
    politica=Exata(),
    branch_versao="release/{versao}",
)


def _git_release() -> FakeGit:
    g = FakeGit()
    g.add_commit("m0", "", "raiz", D)
    g.add_commit("a0", "m0", "ch255514 corrige logs", D)
    g.set_branch("main", "a0")
    g.set_branch("origin/main", "a0")
    g.set_branch("release/1.2.0", "m0")
    return g


def _deps_release(git, estado) -> Deps:
    return Deps(
        versionamento=lambda: _RELEASE,
        git=git,
        tasks=FakeTaskSource(chamados={"1.3.0": ["255514"]}),
        estado=estado,
        repo="r",
        commit_source=FakeCommitSource(por_chamado=UM),
    )


def test_branch_com_template_e_a_versao_aberta():
    g = _git_release()

    situacao = situacao_das_versoes(
        _deps_release(g, _estado()), Catalogo(g, _RELEASE), congelar=False
    )

    assert situacao.abertas == ["1.2.0"]


def test_criar_cria_a_branch_pelo_template():
    g = _git_release()
    estado = _estado()

    resultado = criar(_deps_release(g, estado), "1.3.0")

    assert resultado.status == AtualizarStatus.DONE
    assert "release/1.3.0" in g.branches and "1.3.0" not in g.branches
    assert g.remotes.get("release/1.3.0") is True
    assert g.read_file("release/1.3.0", "VERSAO") == b"1.3.0\n"
    gravada = estado.versao("r", "1.3.0")
    assert gravada is not None and gravada.base_ref == "main"


def test_trava_de_publicacao_olha_a_branch_do_template():
    g = _git_release()
    g.remotes["1.3.0"] = True  # nome puro nao e a branch da versao

    criar(_deps_release(g, _estado()), "1.3.0")

    g = _git_release()
    g.remotes["release/1.3.0"] = True
    with pytest.raises(RecusaDeInvariante):
        criar(_deps_release(g, _estado()), "1.3.0")
