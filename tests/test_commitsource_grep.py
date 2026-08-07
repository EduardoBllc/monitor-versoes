from __future__ import annotations

import datetime

from motor.adapters.commitsource.grep import GrepCommitSource
from motor.adapters.git.fake import FakeGit


def _git_com_commits(*mensagens: str) -> FakeGit:
    """FakeGit e baseado em grafo: add_commit encadeia pelo parent e set_branch
    posiciona o tip que search_commits varre."""
    d = datetime.datetime(2026, 1, 1)
    git = FakeGit()
    parent = ""
    for i, msg in enumerate(mensagens):
        hash_ = f"c{i}"
        git.add_commit(hash_, parent, msg, d)
        parent = hash_
    if mensagens:
        git.set_branch("origin/master", f"c{len(mensagens) - 1}")
    return git


def test_grep_agrupa_por_chamado_e_carimba():
    git = _git_com_commits("ch123456 alfa", "ch999111 beta")

    achados = GrepCommitSource(git=git).resolve(["123456", "999111"])

    assert set(achados) == {"123456", "999111"}
    assert [c.hash_origem for c in achados["123456"]] == ["c0"]
    assert achados["123456"][0].chamado == "123456"


def test_grep_nao_casa_chamado_como_substring():
    git = _git_com_commits("ch255514 alfa")

    assert GrepCommitSource(git=git).resolve(["5514"]) == {}

    # colisao de prefixo: "123" nao pode casar dentro de "ch1234" (search_commits
    # traz o candidato bruto por substring; match_exato precisa rejeitar aqui).
    git_prefixo = _git_com_commits("ch1234 outra correcao")

    assert GrepCommitSource(git=git_prefixo).resolve(["123"]) == {}


def test_grep_omite_chamado_sem_commit():
    git = _git_com_commits("ajuste sem identificador")

    assert GrepCommitSource(git=git).resolve(["123456"]) == {}
