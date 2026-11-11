"""Listar e julgar os órfãos de uma versão pelo caso de uso."""

from __future__ import annotations

import datetime

import pytest

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import Atribuicao, JulgamentoOrfao, RepoInfo, VersaoInfo
from motor.engine.deps import Deps
from motor.engine.orfaos import julgar_orfao, listar_orfaos
from motor.errors import ErroDeEntrada
from tests.fontes_falsas import REFERENCIA_CH
from tests.versionamento import ESCALONADO_COMPOSTA

D = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
D_ORIGEM = datetime.datetime(2025, 12, 1, tzinfo=datetime.UTC)
VERSAO = "13.34.0"


def _git() -> FakeGit:
    """Acima da base: um commit direto sem referencia (`d1...`), um pick de
    origem sem referencia (`a1...`) e um commit com `ch123` (`a2...`, que
    comeca igual ao pick para exercitar o prefixo)."""
    git = FakeGit(tags={"13.33.0": True})
    git.add_commit("base", "", "raiz", D)
    git.add_commit("d1aaaa", "base", "ajuste direto\n\ncorpo", D)
    git.add_commit("p2", "d1aaaa", "solto\n\n(cherry picked from commit a1bbbb)", D)
    git.add_commit("a2cccc", "p2", "ch123 alfa", D)
    git.add_commit("a1bbbb", "x", "solto na origem", D_ORIGEM)
    git.set_branch("13.33.0", "base")
    git.set_branch(VERSAO, "a2cccc")
    return git


def _estado(*, liberada: bool = False) -> FakeEstado:
    estado = FakeEstado(repos={"r": RepoInfo(nome="r")})
    estado.registrar_versao(
        "r", VersaoInfo(numero=VERSAO, base_ref="13.33.0", base_commit="base")
    )
    if liberada:
        estado.marcar_liberadas("r", {VERSAO: D})
    return estado


def _deps(git: FakeGit, estado: FakeEstado) -> Deps:
    return Deps(
        versionamento=ESCALONADO_COMPOSTA,
        git=git,
        tasks=FakeTaskSource(),
        estado=estado,
        repo="r",
        commit_source=FakeCommitSource(),
        referencia=lambda: REFERENCIA_CH,
    )


def test_listar_orfaos_traz_hash_assunto_data_e_julgamento():
    estado = _estado()
    j = JulgamentoOrfao("d1aaaa", VERSAO, "123", "faz parte")
    estado.julgar_orfao("r", j)

    orfaos = listar_orfaos(_deps(_git(), estado), VERSAO)

    assert [(o.hash_origem, o.assunto, o.data, o.julgamento) for o in orfaos] == [
        ("a1bbbb", "solto na origem", D_ORIGEM, None),
        ("d1aaaa", "ajuste direto", D, j),
    ]


def test_listar_orfaos_nao_escreve_no_estado():
    estado = _estado()
    estado.substituir_atribuicoes("r", VERSAO, [Atribuicao(chamado="999")])
    antes = (estado.atribuicoes("r", VERSAO), dict(estado.versoes))

    listar_orfaos(_deps(_git(), estado), VERSAO)

    assert (estado.atribuicoes("r", VERSAO), dict(estado.versoes)) == antes


def test_listar_orfaos_omite_julgamento_de_hash_que_nao_e_mais_orfao():
    estado = _estado()
    fora = JulgamentoOrfao("saiu", VERSAO, None, "m")
    estado.julgar_orfao("r", fora)

    orfaos = listar_orfaos(_deps(_git(), estado), VERSAO)

    assert "saiu" not in {o.hash_origem for o in orfaos}
    assert estado.julgamentos_orfao("r") == [fora]


def test_julgar_orfao_grava_com_hash_completo_a_partir_de_prefixo():
    estado = _estado()

    j = julgar_orfao(_deps(_git(), estado), VERSAO, "a1", "123", "  faz parte ")

    assert j == JulgamentoOrfao("a1bbbb", VERSAO, "123", "faz parte")
    assert estado.julgamentos_orfao("r") == [j]


@pytest.mark.parametrize(
    ("versao", "hash_", "chamado", "motivo"),
    [
        pytest.param(VERSAO, "fffff", None, "m", id="fora-da-varredura"),
        pytest.param(VERSAO, "a2cccc", None, "m", id="com-referencia"),
        pytest.param(VERSAO, "", None, "m", id="hash-vazio"),
        pytest.param(VERSAO, "d1aaaa", None, "  ", id="motivo-em-branco"),
        pytest.param(VERSAO, "d1aaaa", "12 3", "m", id="chamado-fora-do-alfabeto"),
        pytest.param("13.35.0", "d1aaaa", None, "m", id="versao-nao-registrada"),
    ],
)
def test_julgar_orfao_recusa_sem_gravar(versao, hash_, chamado, motivo):
    estado = _estado()

    with pytest.raises(ErroDeEntrada):
        julgar_orfao(_deps(_git(), estado), versao, hash_, chamado, motivo)

    assert estado.julgamentos_orfao("r") == []


def test_julgar_orfao_recusa_prefixo_ambiguo():
    git = _git()
    git.add_commit("d1bbbb", "a2cccc", "outro ajuste", D)
    git.set_branch(VERSAO, "d1bbbb")
    estado = _estado()

    with pytest.raises(ErroDeEntrada):
        julgar_orfao(_deps(git, estado), VERSAO, "d1", None, "m")

    assert estado.julgamentos_orfao("r") == []


def test_listar_orfaos_recusa_versao_nao_registrada():
    with pytest.raises(ErroDeEntrada):
        listar_orfaos(_deps(_git(), _estado()), "13.35.0")


def test_julgar_orfao_grava_em_versao_liberada():
    estado = _estado(liberada=True)

    j = julgar_orfao(_deps(_git(), estado), VERSAO, "d1aaaa", None, "m")

    assert estado.julgamentos_orfao("r") == [j]


class _GitQueTrazABranchNoFetch(FakeGit):
    def fetch(self, remote: str) -> None:
        super().fetch(remote)
        self.branches[VERSAO] = "a2cccc"


@pytest.mark.parametrize(
    "achou",
    [
        pytest.param(
            lambda d: "d1aaaa" in {o.hash_origem for o in listar_orfaos(d, VERSAO)},
            id="listar",
        ),
        pytest.param(
            lambda d: julgar_orfao(d, VERSAO, "d1", None, "m").hash_origem == "d1aaaa",
            id="julgar",
        ),
    ],
)
def test_busca_antes_de_ler_a_branch(achou):
    """A branch só chega no fetch: sem buscar antes, a varredura não acharia
    o órfão, e o julgamento o recusaria."""
    original = _git()
    git = _GitQueTrazABranchNoFetch(tags=original.tags, commits=original.commits)
    git.branches["13.33.0"] = "base"

    assert achou(_deps(git, _estado()))
    assert git.fetched == ["origin"]
