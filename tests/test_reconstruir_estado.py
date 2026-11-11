from __future__ import annotations

import datetime

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import JulgamentoOrfao, RepoInfo, VersaoInfo
from motor.engine.deps import Deps
from motor.engine.reconstruir_estado import ReconstructStatus, reconstruir_estado
from tests.fontes_falsas import REFERENCIA_CH
from tests.versionamento import ESCALONADO_COMPOSTA


def _deps(git, estado) -> Deps:
    return Deps(
        versionamento=ESCALONADO_COMPOSTA,
        git=git,
        tasks=FakeTaskSource(),
        estado=estado,
        repo="r",
        commit_source=FakeCommitSource(),
        referencia=lambda: REFERENCIA_CH,
    )


D = datetime.datetime(2026, 1, 1)


def _git_com_pick(msg_do_pick: str, msg_da_origem: str | None = None) -> FakeGit:
    """13.33.0 e a base; 13.34.0 tem um commit acima dela.

    commits_in_range para em base, entao so o commit do pick e varrido.
    """
    git = FakeGit(tags={"13.33.0": True})
    git.add_commit("base", "", "raiz", D)
    git.add_commit("p1", "base", msg_do_pick, D)
    if msg_da_origem is not None:
        git.add_commit("aaa", "", msg_da_origem, D)
    git.set_branch("13.33.0", "base")
    git.set_branch("13.34.0", "p1")
    return git


def test_reconstroi_atribuicoes_dos_trailers():
    git = _git_com_pick(
        "ch123456 alfa\n\n(cherry picked from commit aaa)",
        msg_da_origem="ch123456 alfa",
    )
    estado = FakeEstado(repos={"r": RepoInfo(nome="r")})

    resultado = reconstruir_estado(_deps(git, estado), "13.34.0")

    assert resultado.status == ReconstructStatus.DONE
    atribuicoes = estado.atribuicoes("r", "13.34.0")
    assert [a.chamado for a in atribuicoes] == ["123456"]
    # guarda o hash de ORIGEM, nao o do pick — o pick e local desta branch
    assert atribuicoes[0].commits == ["aaa"]


def test_commit_direto_na_branch_e_sua_propria_origem():
    git = _git_com_pick("ch123456 alfa")
    estado = FakeEstado(repos={"r": RepoInfo(nome="r")})

    reconstruir_estado(_deps(git, estado), "13.34.0")

    assert estado.atribuicoes("r", "13.34.0")[0].commits == ["p1"]


def test_commit_sem_chamado_vira_orfao():
    git = _git_com_pick("ajuste solto sem identificador")
    estado = FakeEstado(repos={"r": RepoInfo(nome="r")})

    resultado = reconstruir_estado(_deps(git, estado), "13.34.0")

    assert resultado.status == ReconstructStatus.PENDING_JUDGMENT
    assert resultado.orfaos == ["p1"]


class _GitQueRevelaBaseNoFetch(FakeGit):
    """FakeGit em que a base 13.33.0 so entra no ref store local no fetch, e
    entra da forma que o git de verdade a faz entrar: como
    `refs/remotes/origin/13.33.0`, sem head local nenhum e sem tag (branch
    recem-cortada em outra maquina ainda nao foi liberada).

    A versao anterior deste double chamava `set_branch`, ou seja, modelava o
    fetch criando head local — o que o git nao faz. O teste passava por causa
    da mentira do fake.
    """

    def fetch(self, remote: str) -> None:
        super().fetch(remote)
        self.remote_refs["13.33.0"] = "base"


def test_reconstruir_estado_busca_antes_de_resolver_a_base():
    """Pina a ORDEM: 13.34.0 nunca foi registrada, entao a base sai do
    BaseResolver, que le list_version_branches/tag_exists do ref store local.
    Sem buscar primeiro, nem a ref de rastreamento de 13.33.0 existiria e o
    BaseResolver estouraria (ou, pior, uma base errada seria gravada de forma
    definitiva).
    """
    git = _GitQueRevelaBaseNoFetch()
    git.add_commit("base", "", "raiz", D)
    git.add_commit("p1", "base", "ch123456 alfa", D)
    git.set_branch("13.34.0", "p1")
    estado = FakeEstado(repos={"r": RepoInfo(nome="r")})

    resultado = reconstruir_estado(_deps(git, estado), "13.34.0")

    assert git.fetched == ["origin"]
    assert resultado.status == ReconstructStatus.DONE
    gravada = estado.versao("r", "13.34.0")
    assert gravada is not None
    assert gravada.base_ref == "13.33.0"


def _git_com_orfaos() -> FakeGit:
    """13.34.0 tem dois orfaos (o1, o2) e um commit ch123456 (c1)."""
    git = FakeGit(tags={"13.33.0": True})
    git.add_commit("base", "", "raiz", D)
    git.add_commit("o1", "base", "ajuste solto", D)
    git.add_commit("o2", "o1", "outro ajuste", D)
    git.add_commit("c1", "o2", "ch123456 alfa", D)
    git.set_branch("13.33.0", "base")
    git.set_branch("13.34.0", "c1")
    return git


def _estado_julgado(*julgamentos: JulgamentoOrfao) -> FakeEstado:
    estado = FakeEstado(repos={"r": RepoInfo(nome="r")})
    for numero in ("13.34.0", "13.35.0"):
        estado.registrar_versao(
            "r", VersaoInfo(numero=numero, base_ref="13.33.0", base_commit="base")
        )
    for j in julgamentos:
        estado.julgar_orfao("r", j)
    return estado


def _commits_por_chamado(estado: FakeEstado) -> dict[str, list[str]]:
    return {a.chamado: a.commits for a in estado.atribuicoes("r", "13.34.0")}


def test_orfaos_julgados_nos_dois_sentidos_dao_done():
    estado = _estado_julgado(
        JulgamentoOrfao("o1", "13.34.0", "777", "m"),
        JulgamentoOrfao("o2", "13.34.0", None, "m"),
    )

    resultado = reconstruir_estado(_deps(_git_com_orfaos(), estado), "13.34.0")

    assert resultado.status == ReconstructStatus.DONE
    assert _commits_por_chamado(estado) == {"123456": ["c1"], "777": ["o1"]}
    assert {a.estado for a in estado.atribuicoes("r", "13.34.0")} == {"aplicado"}


def test_so_o_orfao_sem_julgamento_fica_pendente():
    estado = _estado_julgado(JulgamentoOrfao("o1", "13.34.0", None, "m"))

    resultado = reconstruir_estado(_deps(_git_com_orfaos(), estado), "13.34.0")

    assert resultado.status == ReconstructStatus.PENDING_JUDGMENT
    assert resultado.orfaos == ["o2"]


def test_reconstruir_duas_vezes_mantem_o_julgamento():
    estado = _estado_julgado(
        JulgamentoOrfao("o1", "13.34.0", "777", "m"),
        JulgamentoOrfao("o2", "13.34.0", None, "m"),
    )
    deps = _deps(_git_com_orfaos(), estado)

    primeiro = reconstruir_estado(deps, "13.34.0")
    atribuicoes = estado.atribuicoes("r", "13.34.0")
    segundo = reconstruir_estado(deps, "13.34.0")

    assert segundo == primeiro
    assert estado.atribuicoes("r", "13.34.0") == atribuicoes


def test_orfao_julgado_soma_aos_commits_da_referencia():
    estado = _estado_julgado(
        JulgamentoOrfao("o1", "13.34.0", "123456", "m"),
        JulgamentoOrfao("o2", "13.34.0", None, "m"),
    )

    reconstruir_estado(_deps(_git_com_orfaos(), estado), "13.34.0")

    assert _commits_por_chamado(estado) == {"123456": ["c1", "o1"]}


def test_julgamento_de_outra_versao_nao_vale():
    estado = _estado_julgado(
        JulgamentoOrfao("o1", "13.35.0", "777", "m"),
        JulgamentoOrfao("o2", "13.34.0", None, "m"),
    )

    resultado = reconstruir_estado(_deps(_git_com_orfaos(), estado), "13.34.0")

    assert resultado.orfaos == ["o1"]
    assert _commits_por_chamado(estado) == {"123456": ["c1"]}
