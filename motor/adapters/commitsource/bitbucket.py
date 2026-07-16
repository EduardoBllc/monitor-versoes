"""BitbucketPRCommitSource: descobre commits de uma task via PRs do Bitbucket Cloud.

Mais robusto que o grep de mensagem: associa commit->task pela PR (título que
começa com o VB-id, ou nome da branch de origem que contém o VB-id), não pela
formatação do trailer que o dev pode errar. Considera só PRs MERGED e só
commits que já estão na master (is_ancestor) — commit fora da master não entra.

API Bitbucket Cloud 2.0:
  GET /2.0/repositories/{ws}/{repo}/pullrequests?q=...&state=MERGED&pagelen=50
  GET /2.0/repositories/{ws}/{repo}/pullrequests/{id}/commits
Auth: Authorization: Bearer <token>. Paginação pelo campo `next`.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

import httpx

from motor.domain.types import CommitRef, TargetSet, TaskTarget
from motor.errors import MotorError
from motor.ports import GitRepo

_BASE_URL_PADRAO = "https://api.bitbucket.org/2.0"

# git@bitbucket.org:ws/repo.git  |  https://user@bitbucket.org/ws/repo(.git)
_PADRAO_REMOTE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")


def parse_workspace_repo(url: str) -> tuple[str, str]:
    """Extrai (workspace, repo) da URL do remote origin."""
    # remove o penúltimo segmento so quando ha host embutido: pega os dois
    # ultimos segmentos de path (ws/repo).
    m = _PADRAO_REMOTE.search(url.strip())
    if m is None:
        raise MotorError(f"nao consegui extrair workspace/repo de {url!r}")
    return m.group(1), m.group(2)


@dataclass
class BitbucketPRCommitSource:
    token: str
    workspace: str
    repo: str
    git: GitRepo
    base_url: str = ""
    master_ref: str = "master"
    client: httpx.Client | None = None

    def resolve(self, tasks: list[TaskTarget]) -> TargetSet:
        resultado: TargetSet = {}
        for t in tasks:
            if not t.task:  # sem VB-id nao tem como casar PR
                continue
            commits = self._commits_da_task(t)
            if commits:
                resultado[t.chamado] = TaskTarget(
                    chamado=t.chamado, task=t.task, titulo=t.titulo, commits=commits
                )
        return resultado

    def _commits_da_task(self, t: TaskTarget) -> list[CommitRef]:
        client = self.client if self.client is not None else httpx.Client()
        base = self.base_url or _BASE_URL_PADRAO
        vb = t.task

        prs_url = f"{base}/repositories/{self.workspace}/{self.repo}/pullrequests"
        params = {
            "state": "MERGED",
            "q": f'title ~ "{vb}" OR source.branch.name ~ "{vb}"',
            "pagelen": 50,
        }

        vistos: set[str] = set()
        commits: list[CommitRef] = []
        for pr in self._paginar(client, prs_url, params):
            if not self._pr_casa(pr, vb):
                continue
            pr_id = pr.get("id")
            commits_url = f"{prs_url}/{pr_id}/commits"
            for c in self._paginar(client, commits_url, None):
                h = c.get("hash", "")
                if not h or h in vistos:
                    continue
                if not self.git.is_ancestor(h, self.master_ref):
                    continue  # so o que ja esta na master
                vistos.add(h)
                commits.append(self._para_commit_ref(c, t))
        commits.sort(key=lambda c: c.commit_date)
        return commits

    @staticmethod
    def _pr_casa(pr: dict, vb: str) -> bool:
        titulo = pr.get("title") or ""
        if titulo.startswith(vb):
            return True
        branch = ((pr.get("source") or {}).get("branch") or {}).get("name") or ""
        return vb in branch

    @staticmethod
    def _para_commit_ref(c: dict, t: TaskTarget) -> CommitRef:
        parents = c.get("parents") or []
        parent = parents[0].get("hash", "") if parents else ""
        data_raw = c.get("date", "")
        try:
            data = datetime.datetime.fromisoformat(data_raw) if data_raw else datetime.datetime.min
        except ValueError:
            data = datetime.datetime.min
        return CommitRef(
            hash_origem=c.get("hash", ""),
            parent=parent,
            chamado=t.chamado,
            task=t.task,
            titulo=t.titulo,
            commit_date=data,
            msg=c.get("message", ""),
        )

    def _paginar(self, client: httpx.Client, url: str, params: dict | None):
        """Itera os `values` de uma resposta paginada, seguindo `next`."""
        while url:
            try:
                resp = client.get(url, params=params, headers={"Authorization": f"Bearer {self.token}"})
            except httpx.HTTPError as e:
                raise MotorError(f"chamando Bitbucket {url}: {e}") from e
            if resp.status_code != 200:
                raise MotorError(f"Bitbucket respondeu {resp.status_code} em {url}: {resp.text}")
            try:
                corpo = resp.json()
            except ValueError as e:
                raise MotorError(f"decodificando resposta do Bitbucket em {url}: {e}") from e
            yield from corpo.get("values", [])
            url = corpo.get("next", "")
            params = None  # `next` ja traz a query embutida
