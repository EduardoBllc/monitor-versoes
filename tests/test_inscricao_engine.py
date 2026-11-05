"""`executar_inscricao` classifica o desfecho de uma execução na ordem da spec."""

from __future__ import annotations

from motor.domain.inscricao import Desfecho
from motor.engine.inscricao import executar_inscricao
from tests.test_incrementar import UM, _deps, _estado, _git

VERSAO = "13.7.0"
CHAMADOS = ["255514"]
COMMIT = "a0"
ARQUIVO_DO_CONFLITO = "arquivo-conflito.txt"


def _pendente(g, commit: str = COMMIT) -> None:
    g.conflict_on[commit] = True
    g.cherry_pick_x(commit)


def test_liberada_com_pick_pendente_encerra():
    g = _git()
    _pendente(g)
    g.tags[VERSAO] = True

    r = executar_inscricao(_deps(g, _estado(), CHAMADOS, UM), VERSAO)

    assert r.desfecho == Desfecho.ENCERRADA


def test_pick_pendente_pula_sem_atualizar():
    g = _git()
    _pendente(g)
    topo = g.branches[VERSAO]

    r = executar_inscricao(_deps(g, _estado(), CHAMADOS, UM), VERSAO)

    assert (r.desfecho, g.branches[VERSAO], VERSAO in g.remotes) == (
        Desfecho.PULADA,
        topo,
        False,
    )


def test_aplicou_traz_chamados_e_vermelhos():
    g = _git()

    r = executar_inscricao(_deps(g, _estado(), [*CHAMADOS, "999999"], UM), VERSAO)

    assert (r.desfecho, r.chamados_aplicados, r.n_aplicados, r.vermelhos) == (
        Desfecho.APLICOU,
        tuple(CHAMADOS),
        1,
        frozenset({"sem_commits:999999"}),
    )


def test_nada_a_aplicar():
    g = _git()
    deps = _deps(g, _estado(), CHAMADOS, UM)
    executar_inscricao(deps, VERSAO)

    assert executar_inscricao(deps, VERSAO).desfecho == Desfecho.NADA


def test_bloqueio_traz_commit_arquivos_e_culpados():
    g = _git()
    g.conflict_on[COMMIT] = True

    r = executar_inscricao(_deps(g, _estado(), CHAMADOS, UM), VERSAO)

    assert (r.desfecho, r.commit_bloqueado, r.arquivos, r.culpados) == (
        Desfecho.BLOQUEADA,
        COMMIT,
        (ARQUIVO_DO_CONFLITO,),
        (),
    )


def test_suspeitos_viram_erro_com_mensagem_da_recusa():
    g = _git()
    g.add_commit("alvo0", "m0", "ch255514 corrige logs", UM[CHAMADOS[0]][0].commit_date)
    g.set_branch(VERSAO, "alvo0")
    g.file_changes[COMMIT] = frozenset({"a.txt"})
    g.file_changes["alvo0"] = frozenset({"a.txt"})

    r = executar_inscricao(_deps(g, _estado(), CHAMADOS, UM), VERSAO)

    assert r.desfecho == Desfecho.ERRO
    assert COMMIT in r.mensagem
    assert r.vermelhos is None


def test_branch_inexistente_vira_erro():
    g = _git()
    del g.branches[VERSAO]

    r = executar_inscricao(_deps(g, _estado(), CHAMADOS, UM), VERSAO)

    assert r.desfecho == Desfecho.ERRO
    assert VERSAO in r.mensagem
