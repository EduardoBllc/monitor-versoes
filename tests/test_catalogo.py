"""Camadas do criterio de liberacao: config > esquema > tag homonima."""

from __future__ import annotations

import datetime

import pytest

from motor.adapters.git.fake import FakeGit
from motor.atribuicoes import Exata
from motor.esquemas.semver import Semver
from motor.ports import GitRepo
from motor.services.catalogo import Catalogo
from motor.services.versionamento import Versionamento

D_TAG = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
D_TAG_V = datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC)
D_MERGE = datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC)


class EsquemaQueLiberaPeloMerge(Semver):
    """Da a 1.1.0 por liberada na data do tip da principal, como um criterio
    de "merge da branch na principal" leria do repositorio."""

    def liberacoes(
        self, git: GitRepo, versoes: list[str], /
    ) -> dict[str, datetime.datetime] | None:
        return {"1.1.0": git.commit_meta(git.resolve_ref("main")).commit_date}


def _git() -> FakeGit:
    """1.0.0 tem a tag homonima, 1.2.0 tem a tag `v1.2.0`, e 1.1.0 so o merge."""
    git = FakeGit(
        tags={"1.0.0": True, "v1.2.0": True},
        tag_commits={"1.0.0": "t100", "v1.2.0": "t120"},
    )
    git.add_commit("t100", "", "1.0.0", D_TAG)
    git.add_commit("t120", "", "1.2.0", D_TAG_V)
    git.add_commit("merge", "", "merge da 1.1.0", D_MERGE)
    git.branches.update({"main": "merge", "1.1.0": "merge", "1.2.0": "t120"})
    return git


@pytest.mark.parametrize(
    ("tag_liberacao", "esquema", "esperado"),
    [
        pytest.param(
            "v{versao}", EsquemaQueLiberaPeloMerge(), {"1.2.0": D_TAG_V}, id="config"
        ),
        pytest.param(
            None, EsquemaQueLiberaPeloMerge(), {"1.1.0": D_MERGE}, id="esquema"
        ),
        pytest.param(None, Semver(), {"1.0.0": D_TAG}, id="tag-homonima"),
    ],
)
def test_vale_so_a_camada_mais_alta_do_criterio_de_liberacao(
    tag_liberacao, esquema, esperado
):
    v = Versionamento(esquema=esquema, politica=Exata(), tag_liberacao=tag_liberacao)
    catalogo = Catalogo(_git(), v)

    assert catalogo.liberadas() == set(esperado)
    assert {n: catalogo.data_liberacao(n) for n in esperado} == esperado
