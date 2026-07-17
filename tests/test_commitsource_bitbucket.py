"""BitbucketPRCommitSource: acha commits da task via PR merged do Bitbucket Cloud.

Regra: PR MERGED cujo titulo COMECA com o VB-id, OU cuja source.branch.name
CONTEM o VB-id. So conta commit que esta na master (is_ancestor) — commit
fora da master nao entra. httpx.MockTransport no lugar de servidor real.
"""

from __future__ import annotations

import datetime

import httpx
import pytest

from motor.adapters.commitsource.bitbucket import (
    BitbucketPRCommitSource,
    parse_workspace_repo,
)
from motor.adapters.git.fake import FakeGit
from motor.domain.types import TaskTarget


@pytest.mark.parametrize(
    "url,esperado",
    [
        ("git@bitbucket.org:acme/monitor.git", ("acme", "monitor")),
        ("https://user@bitbucket.org/acme/monitor.git", ("acme", "monitor")),
        ("https://bitbucket.org/acme/monitor", ("acme", "monitor")),
    ],
)
def test_parse_workspace_repo(url, esperado):
    assert parse_workspace_repo(url) == esperado


def _git_com_master(*hashes_na_master: str) -> FakeGit:
    # encadeia os hashes numa branch master (o primeiro e a raiz).
    g = FakeGit()
    t0 = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    anterior = ""
    for h in hashes_na_master:
        g.add_commit(h, anterior, f"commit {h}", t0)
        anterior = h
    g.set_branch("master", anterior)
    return g


def _fonte(handler, git: FakeGit) -> BitbucketPRCommitSource:
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://testserver")
    return BitbucketPRCommitSource(
        base_url="http://testserver",
        token="tok123",
        email="dev@x.com",
        workspace="acme",
        repo="monitor",
        git=git,
        client=client,
    )


def _handler_pr(prs: list[dict], commits_por_pr: dict[int, list[dict]]):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Basic ZGV2QHguY29tOnRvazEyMw=="
        path = request.url.path
        if path.endswith("/pullrequests"):
            return httpx.Response(200, json={"values": prs})
        # .../pullrequests/{id}/commits
        pr_id = int(path.split("/pullrequests/")[1].split("/")[0])
        return httpx.Response(200, json={"values": commits_por_pr.get(pr_id, [])})

    return handler


def test_pr_titulo_prefixo_so_commits_na_master():
    g = _git_com_master("c1")  # c1 na master, c2 nao
    prs = [{"id": 1, "title": "VB-2354 corrige logs", "source": {"branch": {"name": "feature/x"}}}]
    commits = {
        1: [
            {"hash": "c1", "date": "2024-01-02T10:00:00+00:00", "message": "fix logs", "parents": [{"hash": "p1"}]},
            {"hash": "c2", "date": "2024-01-03T10:00:00+00:00", "message": "wip", "parents": [{"hash": "c1"}]},
        ]
    }
    fonte = _fonte(_handler_pr(prs, commits), g)

    resultado = fonte.resolve([TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")])

    tt = resultado.get("255514")
    assert tt is not None, f"esperava a task: {resultado!r}"
    hashes = [c.hash_origem for c in tt.commits]
    assert hashes == ["c1"], f"so c1 esta na master, veio {hashes}"
    assert tt.commits[0].task == "VB-2354" and tt.commits[0].chamado == "255514", "faltou carimbar"


def test_pr_casa_por_nome_da_branch():
    g = _git_com_master("c1")
    prs = [{"id": 7, "title": "corrige logs", "source": {"branch": {"name": "bugfix/VB-2354-logs"}}}]
    commits = {7: [{"hash": "c1", "date": "2024-01-02T10:00:00+00:00", "message": "fix", "parents": []}]}
    fonte = _fonte(_handler_pr(prs, commits), g)

    resultado = fonte.resolve([TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")])

    assert "255514" in resultado and resultado["255514"].commits[0].hash_origem == "c1"


def test_pr_titulo_que_nao_comeca_com_vb_e_ignorado():
    # titulo CONTEM VB-2354 mas nao COMECA com ele, e branch nao bate: ignora.
    g = _git_com_master("c1")
    prs = [{"id": 3, "title": "fix relacionado a VB-2354", "source": {"branch": {"name": "feature/x"}}}]
    commits = {3: [{"hash": "c1", "date": "2024-01-02T10:00:00+00:00", "message": "fix", "parents": []}]}
    fonte = _fonte(_handler_pr(prs, commits), g)

    resultado = fonte.resolve([TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")])

    assert resultado == {}, f"PR sem prefixo/branch batendo nao deveria contar: {resultado!r}"


def test_pr_ignora_merge_commit():
    # commit com 2 pais e merge: cherry-pick -x sem -m falha, entao nao entra na lista.
    g = _git_com_master("c1")
    prs = [{"id": 1, "title": "VB-2354 corrige logs", "source": {"branch": {"name": "feature/x"}}}]
    commits = {
        1: [
            {"hash": "merge1", "date": "2024-01-02T10:00:00+00:00", "message": "merge", "parents": [{"hash": "a"}, {"hash": "b"}]},
            {"hash": "c1", "date": "2024-01-03T10:00:00+00:00", "message": "fix", "parents": [{"hash": "p1"}]},
        ]
    }
    fonte = _fonte(_handler_pr(prs, commits), g)

    resultado = fonte.resolve([TaskTarget(chamado="255514", task="VB-2354", titulo="Logs")])

    hashes = [c.hash_origem for c in resultado["255514"].commits]
    assert hashes == ["c1"], f"merge commit nao deveria entrar: {hashes}"


def test_task_sem_vb_id_nao_consulta_bitbucket():
    chamado_handler = _handler_pr([], {})
    fonte = _fonte(chamado_handler, _git_com_master("c1"))

    resultado = fonte.resolve([TaskTarget(chamado="255514", task="", titulo="Sem VB")])

    assert resultado == {}, "task sem VB-id nao tem como casar PR"
