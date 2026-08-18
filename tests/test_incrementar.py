"""Testes do `atualizar`, agora contra o estado (nao ha mais lock)."""

from __future__ import annotations

import datetime

import pytest

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import CommitRef, RepoInfo, VersaoInfo, VersionType
from motor.engine.atualizar import (
    AtualizarStatus,
    atualizar,
    atualizar_abort,
    atualizar_continue,
)
from motor.engine.deps import Deps
from motor.errors import MotorError

D = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
D1 = D + datetime.timedelta(minutes=1)

UM = {
    "255514": [
        CommitRef(hash_origem="a0", parent="m0", chamado="255514", commit_date=D,
                  msg="ch255514 corrige logs")
    ]
}
DOIS = UM | {
    "255515": [
        CommitRef(hash_origem="a1", parent="a0", chamado="255515", commit_date=D1,
                  msg="ch255515 outra correcao")
    ]
}


class _GitQueTagueiaNoFetch(FakeGit):
    """FakeGit em que a tag da 13.7.0 so existe DEPOIS do fetch.

    Espelha o git de verdade: `fetch` e o unico ponto em que a tag criada em
    outra maquina entra no ref store local.
    """

    def fetch(self, remote: str) -> None:
        super().fetch(remote)
        self.tags["13.7.0"] = True


def _git(classe=FakeGit) -> FakeGit:
    """Grafo: m0 e a raiz e a base da 13.7.0; a0 e a1 so existem no master.

    Com as versoes em m0, a0 e a1 sao faltantes de verdade na 13.7.0 — e o que
    permite afirmar que foram cherry-picked, e nao herdados da base.
    """
    g = classe()
    g.add_commit("m0", "", "raiz", D)
    g.add_commit("a0", "m0", "ch255514 corrige logs", D)
    g.add_commit("a1", "a0", "ch255515 outra correcao", D1)
    g.set_branch("master", "a1")
    g.set_branch("origin/master", "a1")
    g.set_branch("13.6.0", "m0")
    g.set_branch("13.7.0", "m0")
    return g


def _estado() -> FakeEstado:
    return FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})


def _deps(git, estado, chamados: list[str], commits: dict) -> Deps:
    return Deps(
        git=git,
        tasks=FakeTaskSource(chamados={"13.7.0": chamados}),
        estado=estado,
        repo="r",
        _commit_source=FakeCommitSource(por_chamado=commits),
    )


def test_atualizar_aplica_tudo():
    g = _git()
    estado = _estado()

    resultado = atualizar(_deps(g, estado, ["255514"], UM), "13.7.0")

    assert resultado.status == AtualizarStatus.DONE, f"status = {resultado.status!r}, quer DONE"
    assert [c.hash_origem for c in resultado.aplicados] == ["a0"]
    assert g.remotes.get("13.7.0") is True, "esperava push apos lote fechar sem conflito"
    assert g.removed_worktrees == ["13.7.0"], "esperava worktree removida apos lote fechar sem conflito"
    assert "13.7.0" in g.branches, "worktree_remove nao pode apagar a branch, so o checkout local"
    # o verificar gravou 'pendente' (a presenca dele e de ANTES dos picks); e o
    # atualizar que regrava 'aplicado' no fim do lote.
    assert [
        (a.chamado, a.estado, a.commits) for a in estado.atribuicoes("r", "13.7.0")
    ] == [("255514", "aplicado", ["a0"])]


def test_atualizar_nao_marca_como_aplicada_tarefa_sem_commit():
    """Chamado marcado no Tickio sem commit nenhum achado nao entregou nada, e
    um lote bem-sucedido a respeito dele nao aplicou coisa alguma. Marcar tudo
    de uma vez como 'aplicado' inventaria entrega para a tarefa que ninguem
    achou.
    """
    g = _git()
    estado = _estado()

    resultado = atualizar(_deps(g, estado, ["255514", "999999"], UM), "13.7.0")

    assert resultado.status == AtualizarStatus.DONE, f"status = {resultado.status!r}, quer DONE"
    assert [(a.chamado, a.estado) for a in estado.atribuicoes("r", "13.7.0")] == [
        ("255514", "aplicado"),
        ("999999", "pendente"),
    ]


def test_atualizar_bloqueia_com_suspeita_de_conteudo():
    """Nao pode cherry-pickar de novo um commit suspeito de ja ter sido
    aplicado manualmente (sem -x) com conteudo divergente - repetiria o
    conflito que o operador ja resolveu na mao. Supervisionado: levanta erro
    em vez de tentar sozinho.
    """
    g = _git()
    g.add_commit("alvo0", "m0", "ch255514 corrige logs", D)  # mesma msg que a0
    g.set_branch("13.7.0", "alvo0")
    g.file_changes["a0"] = frozenset({"a.txt"})
    g.file_changes["alvo0"] = frozenset({"a.txt"})
    estado = _estado()

    with pytest.raises(MotorError, match="suspeitos"):
        atualizar(_deps(g, estado, ["255514"], UM), "13.7.0")

    assert "13.7.0" not in g.remotes, "nao esperava push com suspeita nao resolvida"


def test_atualizar_para_em_conflito():
    g = _git()
    g.conflict_on["a0"] = True
    estado = _estado()

    resultado = atualizar(_deps(g, estado, ["255514"], UM), "13.7.0")

    assert (
        resultado.status == AtualizarStatus.BLOCKED
    ), f"status = {resultado.status!r}, quer BLOCKED"
    assert resultado.blocked_commit == "a0", (
        f"blocked_commit = {resultado.blocked_commit!r}, quer a0"
    )
    assert "13.7.0" not in g.remotes, "nao esperava push com lote bloqueado por conflito"
    assert g.removed_worktrees == [], (
        "nao esperava remover a worktree com lote bloqueado - --continue precisa dela"
    )
    assert [a.estado for a in estado.atribuicoes("r", "13.7.0")] == ["pendente"], (
        "lote bloqueado nao pode marcar a atribuicao como aplicada"
    )


def test_atualizar_abort_remove_worktree():
    g = _git()
    g.conflict_on["a0"] = True
    deps = _deps(g, _estado(), ["255514"], UM)
    atualizar(deps, "13.7.0")

    atualizar_abort(deps, "13.7.0")

    assert g.removed_worktrees == ["13.7.0"], "esperava worktree removida apos abort"
    assert "13.7.0" in g.branches, "worktree_remove nao pode apagar a branch, so o checkout local"


def test_atualizar_continue_conclui_o_lote():
    g = _git()
    g.conflict_on["a0"] = True
    estado = _estado()
    deps = _deps(g, estado, ["255514"], UM)
    atualizar(deps, "13.7.0")

    resultado = atualizar_continue(deps, "13.7.0")

    assert resultado.status == AtualizarStatus.DONE, f"status = {resultado.status!r}, quer DONE"
    assert [(a.chamado, a.estado) for a in estado.atribuicoes("r", "13.7.0")] == [
        ("255514", "aplicado")
    ]
    assert g.remotes.get("13.7.0") is True, "esperava push apos o lote fechar no continue"


def test_atualizar_continue_preserva_os_commits_do_lote_anterior():
    """Lote de 2 commits em que o SEGUNDO conflita. O primeiro ja foi
    cherry-picked pra branch antes do conflito. O continue nao reconstroi nada
    a mao: o `atualizar` que ele chama passa pelo `verificar`, que reprojeta o
    estado a partir do git de verdade — e os dois chamados voltam aplicados.
    """
    g = _git()
    g.conflict_on["a1"] = True
    estado = _estado()
    deps = _deps(g, estado, ["255514", "255515"], DOIS)

    resultado = atualizar(deps, "13.7.0")
    assert (resultado.status, resultado.blocked_commit) == (AtualizarStatus.BLOCKED, "a1"), (
        f"resultado inicial = {resultado!r}, quer BLOCKED em a1"
    )

    resultado = atualizar_continue(deps, "13.7.0")

    assert resultado.status == AtualizarStatus.DONE, f"status = {resultado.status!r}, quer DONE"
    assert [
        (a.chamado, a.estado, a.commits) for a in estado.atribuicoes("r", "13.7.0")
    ] == [
        ("255514", "aplicado", ["a0"]),
        ("255515", "aplicado", ["a1"]),
    ], "o commit aplicado antes do conflito nao pode se perder do estado"


def test_atualizar_recusa_versao_com_tag():
    git = FakeGit(branches={"13.34.0": "b1"}, tags={"13.34.0": True})
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})
    deps = Deps(git=git, tasks=FakeTaskSource(), estado=estado, repo="r",
                _commit_source=FakeCommitSource())

    with pytest.raises(MotorError, match="liberada"):
        atualizar(deps, "13.34.0")


def test_atualizar_busca_antes_de_ler_a_tag():
    """A 13.7.0 foi liberada em outra maquina: a tag so aparece no fetch.

    Pina a ORDEM, nao so o comportamento. Lendo a tag antes de buscar, a recusa
    nao dispara: o run entra no verificar, que congela a versao, e o erro que
    sobra fala de gravacao em versao imutavel — nao de tarefa a remarcar para a
    proxima versao, que e a orientacao que o operador precisa.
    """
    g = _git(classe=_GitQueTagueiaNoFetch)
    estado = _estado()
    estado.registrar_versao("r", VersaoInfo(numero="13.7.0", tipo=VersionType.AJUSTADA,
                                            base_ref="13.6.0", base_commit="m0"))

    with pytest.raises(MotorError, match="ja liberada"):
        atualizar(_deps(g, estado, ["255514"], UM), "13.7.0")

    assert g.fetched == ["origin"]
    assert g.removed_worktrees == [] and "13.7.0" not in g.remotes, (
        "recusa antes de qualquer efeito no git"
    )
