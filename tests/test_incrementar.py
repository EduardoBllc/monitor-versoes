import datetime

import pytest

from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import TaskTarget
from motor.engine.deps import Deps
from motor.engine.atualizar import (
    AtualizarStatus,
    atualizar,
    atualizar_abort,
    atualizar_continue,
)
from motor.errors import MotorError
from motor.services.lock_store import LockStore


def _service_lock_store(g: FakeGit, tmp_path) -> LockStore:
    return LockStore(git=g, lock_dir=str(tmp_path))


def _setup_incremento_basico(tmp_path) -> tuple[FakeGit, FakeTaskSource]:
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("origin/master", "origem1")
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")
    (tmp_path / "13.7.0.lock").write_bytes(
        b"""{
        "versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
        "tasks":{}
        }"""
    )

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")]
    return g, tasks


def test_atualizar_aplica_tudo(tmp_path):
    g, tasks = _setup_incremento_basico(tmp_path)

    resultado = atualizar(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")

    assert resultado.status == AtualizarStatus.DONE, f"status = {resultado.status!r}, quer DONE"
    assert g.remotes.get("13.7.0") is True, "esperava push apos lote fechar sem conflito"
    assert g.removed_worktrees == ["13.7.0"], "esperava worktree removida apos lote fechar sem conflito"
    assert "13.7.0" in g.branches, "worktree_remove nao pode apagar a branch, so o checkout local"

    lock_store = _service_lock_store(g, tmp_path)
    lock = lock_store.ler("13.7.0")
    assert (
        len(lock.tasks["255514"].commits) == 1
    ), f"lock apos atualizar = {lock.tasks!r}"


def test_atualizar_bloqueia_com_suspeita_de_conteudo(tmp_path):
    """Nao pode cherry-pickar de novo um commit suspeito de ja ter sido
    aplicado manualmente (sem -x) com conteudo divergente - repetiria o
    conflito que o operador ja resolveu na mao. Supervisionado: levanta erro
    em vez de tentar sozinho.
    """
    g, tasks = _setup_incremento_basico(tmp_path)
    g.add_commit("alvo1", "base-tip", "fix: ch255514 corrige logs", datetime.datetime.now(datetime.timezone.utc))
    g.set_branch("13.7.0", "alvo1")
    g.file_changes["origem1"] = frozenset({"a.txt"})
    g.file_changes["alvo1"] = frozenset({"a.txt"})

    with pytest.raises(MotorError):
        atualizar(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")

    assert "13.7.0" not in g.remotes, "nao esperava push com suspeita nao resolvida"


def test_atualizar_para_em_conflito(tmp_path):
    g, tasks = _setup_incremento_basico(tmp_path)
    g.conflict_on["origem1"] = True

    resultado = atualizar(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")

    assert (
        resultado.status == AtualizarStatus.BLOCKED
    ), f"status = {resultado.status!r}, quer BLOCKED"
    assert resultado.blocked_commit == "origem1", (
        f"blocked_commit = {resultado.blocked_commit!r}, quer origem1"
    )
    assert "13.7.0" not in g.remotes, "nao esperava push com lote bloqueado por conflito"
    assert g.removed_worktrees == [], (
        "nao esperava remover a worktree com lote bloqueado - --continue precisa dela"
    )


def test_atualizar_abort_remove_worktree(tmp_path):
    g, tasks = _setup_incremento_basico(tmp_path)
    g.conflict_on["origem1"] = True
    atualizar(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")

    atualizar_abort(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")

    assert g.removed_worktrees == ["13.7.0"], "esperava worktree removida apos abort"
    assert "13.7.0" in g.branches, "worktree_remove nao pode apagar a branch, so o checkout local"


def test_atualizar_continue_registra_no_lock(tmp_path):
    g, tasks = _setup_incremento_basico(tmp_path)
    g.conflict_on["origem1"] = True

    atualizar(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")

    resultado = atualizar_continue(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")

    assert resultado.status == AtualizarStatus.DONE, f"status = {resultado.status!r}, quer DONE"

    lock_store = _service_lock_store(g, tmp_path)
    lock = lock_store.ler("13.7.0")
    assert (
        len(lock.tasks["255514"].commits) == 1
    ), f"lock apos continue = {lock.tasks!r}"


def test_atualizar_continue_preserva_commits_anteriores(tmp_path):
    """Cobre um lote de 2 commits onde o SEGUNDO conflita. O primeiro ja foi
    cherry-picked pra branch (e so nao esta no lock ainda, porque atualizar
    escreve o lock em lote, no fim). atualizar_continue precisa recuperar
    OS DOIS commits do git (via LockStore.reconstruir), nao so o que acabou de
    ser resolvido - senao o registro do primeiro chamado se perde pra sempre
    do lock, mesmo estando correto no historico do git.
    """
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    t1 = t0 + datetime.timedelta(minutes=1)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("origem2", "origem1", "fix: ch255515 outra correcao VB-9999", t1)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("origin/master", "origem2")
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")
    (tmp_path / "13.7.0.lock").write_bytes(
        b"""{
        "versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
        "tasks":{}
        }"""
    )
    g.conflict_on["origem2"] = True

    tasks = FakeTaskSource()
    tasks.tasks["13.7.0"] = [
        TaskTarget(chamado="255514", task="VB-2354", titulo="Logs"),
        TaskTarget(chamado="255515", task="VB-9999", titulo="Outra"),
    ]

    resultado = atualizar(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")
    assert resultado.status == AtualizarStatus.BLOCKED and resultado.blocked_commit == "origem2", (
        f"resultado inicial = {resultado!r}, quer BLOCKED em origem2"
    )

    resultado = atualizar_continue(Deps(git=g, tasks=tasks, lock_dir=str(tmp_path)), "13.7.0")
    assert resultado.status == AtualizarStatus.DONE, f"status = {resultado.status!r}, quer DONE"

    lock_store = _service_lock_store(g, tmp_path)
    lock = lock_store.ler("13.7.0")
    assert len(lock.tasks["255514"].commits) == 1, (
        f"lock.tasks[255514] = {lock.tasks['255514']!r}, "
        "o commit aplicado antes do conflito nao pode se perder"
    )
    assert (
        len(lock.tasks["255515"].commits) == 1
    ), f"lock.tasks[255515] = {lock.tasks['255515']!r}, quer 1 commit"
