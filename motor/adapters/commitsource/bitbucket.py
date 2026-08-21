"""BitbucketPRCommitSource: descobre commits de uma tarefa via PRs do Bitbucket Cloud.

Mais robusto que o grep de mensagem: associa commit->chamado pela PR (título
que começa com `ch<chamado>`, ou nome da branch de origem que contém
`ch<chamado>`), não pela formatação do trailer que o dev pode errar.
Considera só PRs MERGED e só commits que já estão na master (is_ancestor) —
commit fora da master não entra.

O `workspace/repo` sai da URL do remote `origin` na primeira busca — construir
esta fonte nao toca o git.

API Bitbucket Cloud 2.0:
  GET /2.0/repositories/{ws}/{repo}/pullrequests?q=...&state=MERGED&pagelen=50
  GET /2.0/repositories/{ws}/{repo}/pullrequests/{id}/commits
Auth: Authorization: Basic base64(email:token). Paginação pelo campo `next`.
"""

from __future__ import annotations

import base64
import datetime
import re
import contextlib
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import Any

import httpx

from motor.domain.types import SEM_DATA, CommitRef
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida
from motor.ports import EstadoRepo, GitRepo
from motor.progresso import Progresso, RelatorProgresso, silencioso

# Corpo de JSON da API: dict de chaves str para qualquer coisa. Nao e um dict
# tipado — a §10 do desenho registra que o contrato ainda nao foi observado.
JSON = dict[str, Any]

_BASE_URL_PADRAO = "https://api.bitbucket.org/2.0"

# git@bitbucket.org:ws/repo.git  |  https://user@bitbucket.org/ws/repo(.git)
_PADRAO_REMOTE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")


def parse_workspace_repo(url: str) -> tuple[str, str]:
    """Extrai (workspace, repo) da URL do remote origin."""
    # remove o penúltimo segmento so quando ha host embutido: pega os dois
    # ultimos segmentos de path (ws/repo).
    m = _PADRAO_REMOTE.search(url.strip())
    if m is None:
        raise RespostaInvalida(f"nao consegui extrair workspace/repo de {url!r}")
    return m.group(1), m.group(2)


@dataclass
class BitbucketPRCommitSource:
    # repr=False: token e email formam o Basic auth — um repr desta dataclass
    # (com --debug, ou no repr de uma excecao) vazaria a credencial inteira.
    token: str = field(repr=False)
    email: str = field(repr=False)
    git: GitRepo
    # Vazios = derivados do remote na primeira busca, nao na construcao. Montar
    # nao e usar: resolver aqui faria `atualizar --abort` e `reconstruir-estado`
    # — que nunca chamam esta fonte — pagarem uma chamada de git, e quebrarem
    # num clone sem `origin`.
    workspace: str = ""
    repo: str = ""
    remote: str = "origin"
    base_url: str = ""
    master_ref: str = "master"
    client: httpx.Client | None = None
    progresso: RelatorProgresso = silencioso
    # Cache de `PR -> commits`. Opcional: sem estado a fonte funciona igual,
    # so mais lenta. `repo_estado` e o nome canonico no banco, que nao e
    # necessariamente o `repo` do Bitbucket — e para isso que aliases existem.
    estado: EstadoRepo | None = None
    repo_estado: str = ""

    def _workspace_repo(self) -> tuple[str, str]:
        """Resolve (workspace, repo) do remote uma vez por instancia."""
        if not self.workspace or not self.repo:
            self.workspace, self.repo = parse_workspace_repo(
                self.git.remote_url(self.remote)
            )
        return self.workspace, self.repo

    def _auth_header(self) -> str:
        credenciais = base64.b64encode(f"{self.email}:{self.token}".encode()).decode()
        return f"Basic {credenciais}"

    def resolve(self, chamados: list[str], /) -> dict[str, list[CommitRef]]:
        resultado: dict[str, list[CommitRef]] = {}
        for indice, chamado in enumerate(chamados, start=1):
            # Relata antes de filtrar: o total e o tamanho do lote pedido, e
            # uma barra que pula numeros por causa de chamado vazio confunde
            # mais do que informa.
            self.progresso(
                Progresso("commits dos chamados no Bitbucket", indice, len(chamados))
            )
            if not chamado:  # sem numero nao tem como casar PR
                continue
            commits = self._commits_do_chamado(chamado)
            if commits:
                resultado[chamado] = commits
        return resultado

    def _commits_do_chamado(self, chamado: str) -> list[CommitRef]:
        base = self.base_url or _BASE_URL_PADRAO
        termo = "ch" + chamado
        workspace, repo = self._workspace_repo()

        prs_url = f"{base}/repositories/{workspace}/{repo}/pullrequests"
        params = {
            "state": "MERGED",
            "q": f'title ~ "{termo}" OR source.branch.name ~ "{termo}"',
            "pagelen": 50,
        }

        # Fecha so o que criamos: cliente injetado pertence a quem injetou.
        with contextlib.ExitStack() as pilha:
            client = self.client
            if client is None:
                client = pilha.enter_context(httpx.Client())

            # A busca roda SEMPRE, mesmo com tudo em cache: e ela que descobre
            # PR de correcao mergeada depois. Cachear a busca esconderia esse
            # commit e a versao sairia verde faltando entrega.
            pr_ids = [
                pr["id"]
                for pr in self._paginar(client, prs_url, params)
                if self._pr_casa(pr, termo) and pr.get("id")
            ]

            por_pr = self._do_cache(pr_ids)
            # Unica chamada que o cache corta: os commits de PR ja vista.
            novas = {
                pr_id: self._buscar_commits(client, prs_url, pr_id)
                for pr_id in pr_ids
                if pr_id not in por_pr
            }
            self._gravar_cache(novas)
            por_pr |= novas

        vistos: set[str] = set()
        commits: list[CommitRef] = []
        for pr_id in pr_ids:
            for c in por_pr.get(pr_id, []):
                if c.hash_origem in vistos:
                    continue
                # is_ancestor fica FORA do cache: e volatil. PR mergeada numa
                # branch que ainda nao chegou na master viraria commit escondido
                # para sempre se o filtro fosse gravado junto.
                if not self.git.is_ancestor(c.hash_origem, self.master_ref):
                    continue
                vistos.add(c.hash_origem)
                # o chamado vem da busca, nao da PR: duas tarefas podem apontar
                # para a mesma PR, entao ele e carimbado aqui e nao no cache.
                commits.append(replace(c, chamado=chamado))
        commits.sort(key=lambda c: c.commit_date)
        return commits

    def _buscar_commits(
        self, client: httpx.Client, prs_url: str, pr_id: int
    ) -> list[CommitRef]:
        return [
            self._para_commit_ref(c)
            for c in self._paginar(client, f"{prs_url}/{pr_id}/commits", None)
            # merge commit: cherry-pick -x nao aceita sem -m, e o conteudo ja vem
            # pelos pais individuais. Numero de pais e propriedade do commit,
            # nunca muda — por isso filtra antes de cachear.
            if c.get("hash") and len(c.get("parents") or []) <= 1
        ]

    def _do_cache(self, pr_ids: list[int]) -> dict[int, list[CommitRef]]:
        if self.estado is None:
            return {}
        return self.estado.commits_de_pr(self.repo_estado, pr_ids)

    def _gravar_cache(self, novas: dict[int, list[CommitRef]]) -> None:
        # ponytail: PR cujos commits sao todos merge commit grava vazio e vira
        # miss em todo run. Custa 1 request por run e nao tem PR assim na
        # pratica; se aparecer, o conserto e uma linha-sentinela por PR.
        if self.estado is None or not novas:
            return
        self.estado.gravar_commits_de_pr(self.repo_estado, novas)

    @staticmethod
    def _pr_casa(pr: JSON, termo: str) -> bool:
        if not isinstance(pr, dict):
            raise RespostaInvalida(f"PR do Bitbucket em formato inesperado: {pr!r}")
        titulo = pr.get("title") or ""
        if not isinstance(titulo, str):
            raise RespostaInvalida(f"title da PR do Bitbucket em formato inesperado: {titulo!r}")
        if titulo.startswith(termo):
            return True
        branch = ((pr.get("source") or {}).get("branch") or {}).get("name") or ""
        return termo in branch

    @staticmethod
    def _para_commit_ref(c: JSON) -> CommitRef:
        """Sem `chamado`: e o que o cache guarda, e o cache e por PR."""
        parents = c.get("parents") or []
        if parents and not isinstance(parents[0], dict):
            raise RespostaInvalida(
                f"parent de commit do Bitbucket em formato inesperado: {parents[0]!r}"
            )
        parent = parents[0].get("hash", "") if parents else ""
        data_raw = c.get("date", "")
        try:
            data = datetime.datetime.fromisoformat(data_raw) if data_raw else SEM_DATA
        except ValueError:
            data = SEM_DATA
        return CommitRef(
            hash_origem=c.get("hash", ""),
            parent=parent,
            commit_date=data,
            msg=c.get("message", ""),
        )

    def _paginar(
        self, client: httpx.Client, url: str, params: JSON | None
    ) -> Iterator[JSON]:
        """Itera os `values` de uma resposta paginada, seguindo `next`."""
        while url:
            try:
                resp = client.get(url, params=params, headers={"Authorization": self._auth_header()})
            except httpx.InvalidURL as e:
                raise ErroDeEntrada(f"URL do Bitbucket invalida: {url!r}: {e}") from e
            except httpx.HTTPError as e:
                raise BackendIndisponivel(f"chamando Bitbucket {url}: {e}") from e
            if resp.status_code != 200:
                raise BackendIndisponivel(
                    f"Bitbucket respondeu {resp.status_code} em {url}: {resp.text}"
                )
            try:
                corpo = resp.json()
            except ValueError as e:
                raise RespostaInvalida(f"decodificando resposta do Bitbucket em {url}: {e}") from e
            if not isinstance(corpo, dict):
                raise RespostaInvalida(
                    f"resposta do Bitbucket em formato inesperado em {url}: {corpo!r}"
                )
            yield from corpo.get("values", [])
            url = corpo.get("next", "")
            params = None  # `next` ja traz a query embutida
