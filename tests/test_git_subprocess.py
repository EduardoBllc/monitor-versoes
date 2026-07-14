"""Transcrição de internal/adapters/git/subprocess_test.go.

Usa git real em tmp_path (o Go não pula esses testes, então este também não).
"""

from __future__ import annotations

import os
import subprocess

import pytest

from motor.adapters.git.subprocess import new_git_subprocess
from motor.ports import CherryPickOutcome


def _git_env() -> dict:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "teste",
            "GIT_AUTHOR_EMAIL": "teste@example.com",
            "GIT_COMMITTER_NAME": "teste",
            "GIT_COMMITTER_EMAIL": "teste@example.com",
        }
    )
    return env


def _run_git(dir_: str, *args: str) -> None:
    proc = subprocess.run(
        ["git", *args], cwd=dir_, env=_git_env(), capture_output=True, text=True
    )
    if proc.returncode != 0:
        pytest.fail(f"git {args}: {proc.returncode}: {proc.stdout}{proc.stderr}")


def _config_identidade_local(dir_: str) -> None:
    # ponytail: config local (nao --global) pra nao depender do ambiente ter
    # git user.name/email configurados - GitSubprocess nao propaga os envs
    # GIT_AUTHOR_*/GIT_COMMITTER_* pros comandos que ele mesmo dispara (só
    # este helper de teste os usa), entao a identidade precisa vir do
    # repo-config (compartilhado com as worktrees via git dir comum).
    _run_git(dir_, "config", "user.name", "teste")
    _run_git(dir_, "config", "user.email", "teste@example.com")


def init_repo_de_teste(tmp_path) -> str:
    dir_ = str(tmp_path)
    _run_git(dir_, "init", "-b", "master")
    _config_identidade_local(dir_)
    (tmp_path / "arquivo.txt").write_text("v1\n")
    _run_git(dir_, "add", "arquivo.txt")
    _run_git(dir_, "commit", "-m", "fix: ch255514 corrige logs")
    return dir_


def test_git_subprocess_write_file_noop_quando_conteudo_igual(tmp_path):
    """Cobre o achado da tarefa 21: WriteFile grava, `git add` e comita sem
    checar se há algo de fato staged. Quando o conteúdo escrito é
    byte-idêntico ao já commitado (ex: Criar grava o lock inicial,
    Incrementar tenta gravar o mesmo lock de novo por não ter Faltantes),
    `git commit` sem --allow-empty falha com "nothing to commit, working
    tree clean" e aborta a operação inteira.
    """
    repo_dir = init_repo_de_teste(tmp_path)

    g = new_git_subprocess(repo_dir)
    g.worktree_add("13.8.0", "master")

    g.write_file("13.8.0", "VERSAO.lock", b"{}", "lock inicial")
    primeiro_hash = g._output(g._worktree_dir("13.8.0"), "rev-parse", "HEAD")

    # 2a chamada com o MESMO conteudo: nada staged apos o `git add`, entao
    # `git commit` deve ser evitado (sem --allow-empty ele falharia aqui).
    g.write_file("13.8.0", "VERSAO.lock", b"{}", "lock inalterado")
    segundo_hash = g._output(g._worktree_dir("13.8.0"), "rev-parse", "HEAD")
    assert segundo_hash == primeiro_hash, (
        f"2a WriteFile com conteudo igual criou commit novo: HEAD mudou de "
        f"{primeiro_hash} para {segundo_hash}"
    )
    conteudo = g.read_file("13.8.0", "VERSAO.lock")
    assert conteudo == b"{}"

    # 3a chamada com conteudo DIFERENTE: precisa gerar commit real, provando
    # que a checagem de "nada staged" nao suprime commits legitimos.
    g.write_file("13.8.0", "VERSAO.lock", b'{"v":1}', "lock atualizado")
    terceiro_hash = g._output(g._worktree_dir("13.8.0"), "rev-parse", "HEAD")
    assert terceiro_hash != segundo_hash, (
        "3a WriteFile com conteudo diferente nao criou commit novo"
    )
    conteudo3 = g.read_file("13.8.0", "VERSAO.lock")
    assert conteudo3 == b'{"v":1}'


def test_git_subprocess_worktree_cherry_pick_e_arquivo(tmp_path):
    repo_dir = init_repo_de_teste(tmp_path)

    g = new_git_subprocess(repo_dir)
    tip = g.resolve_ref("master")

    g.worktree_add("13.7.0", "master")

    g.write_file("13.7.0", "VERSAO.lock", b"{}", "lock inicial")
    conteudo = g.read_file("13.7.0", "VERSAO.lock")
    assert conteudo == b"{}"

    ok = g.is_ancestor(tip, "13.7.0")
    assert ok, "esperava tip de master como ancestral de 13.7.0"

    existe = g.tag_exists("13.7.0")
    assert not existe, "nao esperava tag 13.7.0 ainda"


def test_git_subprocess_cherry_pick_x_rerere_auto_resolvido(tmp_path):
    """Cobre o achado crítico da revisão da tarefa 18: quando
    rerere.autoUpdate resolve e re-stagea o conflito sozinho, `git
    cherry-pick` ainda sai com erro (git nunca chama --continue por conta
    própria) e ConflictedPaths() fica vazio. CherryPickX precisa classificar
    isso como (Conflito, nil) - não como erro - usando PendingCherryPick
    (CHERRY_PICK_HEAD) em vez de ConflictedPaths para decidir.
    """
    dir_ = str(tmp_path)
    _run_git(dir_, "init", "-b", "master")
    _config_identidade_local(dir_)
    (tmp_path / "arquivo.txt").write_text("linha1\nlinha2\nlinha3\n")
    _run_git(dir_, "add", "arquivo.txt")
    _run_git(dir_, "commit", "-m", "base")

    g = new_git_subprocess(dir_)
    base_hash = g.resolve_ref("master")

    (tmp_path / "arquivo.txt").write_text("linha1\nlinha2-X\nlinha3\n")
    _run_git(dir_, "add", "arquivo.txt")
    _run_git(dir_, "commit", "-m", "muda linha2 para X")
    commit_x = g.resolve_ref("master")

    # 1a tentativa: conflito real, resolvido a mao - grava a resolucao no rerere.
    g.worktree_add("13.7.0", base_hash)
    g.write_file("13.7.0", "arquivo.txt", b"linha1\nlinha2-Y\nlinha3\n", "muda linha2 para Y")

    outcome = g.cherry_pick_x(commit_x)
    assert outcome == CherryPickOutcome.CONFLITO
    paths = g.conflicted_paths()
    assert len(paths) != 0, "esperava conflito real com arquivo ainda nao resolvido"

    with open(os.path.join(g._worktree_dir("13.7.0"), "arquivo.txt"), "w") as f:
        f.write("linha1\nlinha2-X\nlinha3\n")
    g.continue_cherry_pick()

    # 2a tentativa: mesmo conflito em branch equivalente - rerere.autoUpdate
    # deve resolver e re-stagear o arquivo sozinho, mas o cherry-pick continua
    # pendente (git nao chama --continue por conta propria).
    g.worktree_add("13.7.1", base_hash)
    g.write_file("13.7.1", "arquivo.txt", b"linha1\nlinha2-Y\nlinha3\n", "muda linha2 para Y")

    outcome2 = g.cherry_pick_x(commit_x)
    assert (
        outcome2 == CherryPickOutcome.CONFLITO
    ), "outcome2 deveria ser Conflito (git ainda espera --continue mesmo com rerere resolvendo)"
    paths2 = g.conflicted_paths()
    assert paths2 == [], f"esperava rerere ter resolvido e deixado ConflictedPaths vazio, veio {paths2}"
    _, pendente = g.pending_cherry_pick()
    assert pendente, "esperava cherry-pick pendente apos rerere auto-resolver"

    g.continue_cherry_pick()
