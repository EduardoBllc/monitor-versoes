from __future__ import annotations

import datetime

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import RepoInfo
from motor.engine.deps import Deps
from motor.engine.reconstruir_estado import ReconstructStatus, reconstruir_estado


def _deps(git, estado) -> Deps:
    return Deps(git=git, tasks=FakeTaskSource(), estado=estado, repo="r",
                commit_source=FakeCommitSource())


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
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})

    resultado = reconstruir_estado(_deps(git, estado), "13.34.0")

    assert resultado.status == ReconstructStatus.DONE
    atribuicoes = estado.atribuicoes("r", "13.34.0")
    assert [a.chamado for a in atribuicoes] == ["123456"]
    # guarda o hash de ORIGEM, nao o do pick — o pick e local desta branch
    assert atribuicoes[0].commits == ["aaa"]


def test_commit_direto_na_branch_e_sua_propria_origem():
    git = _git_com_pick("ch123456 alfa")
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})

    reconstruir_estado(_deps(git, estado), "13.34.0")

    assert estado.atribuicoes("r", "13.34.0")[0].commits == ["p1"]


def test_commit_sem_chamado_vira_orfao():
    git = _git_com_pick("ajuste solto sem identificador")
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})

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
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})

    resultado = reconstruir_estado(_deps(git, estado), "13.34.0")

    assert git.fetched == ["origin"]
    assert resultado.status == ReconstructStatus.DONE
    gravada = estado.versao("r", "13.34.0")
    assert gravada is not None
    assert gravada.base_ref == "13.33.0"
