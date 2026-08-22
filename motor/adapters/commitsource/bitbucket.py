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

from motor.domain.types import SEM_DATA, CommitRef, PrIndex
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida
from motor.ports import EstadoRepo, GitRepo
from motor.progresso import Progresso, RelatorProgresso, silencioso

# Corpo de JSON da API: dict de chaves str para qualquer coisa. Nao e um dict
# tipado — a §10 do desenho registra que o contrato ainda nao foi observado.
JSON = dict[str, Any]

_BASE_URL_PADRAO = "https://api.bitbucket.org/2.0"

# git@bitbucket.org:ws/repo.git  |  https://user@bitbucket.org/ws/repo(.git)
_PADRAO_REMOTE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")


def _padrao_do_chamado(chamado: str) -> re.Pattern[str]:
    """`ch<numero>` com fronteira a direita.

    O `(?!\\d)` e o conserto de um bug antigo: com `startswith`/`in` crus, o
    chamado 255514 casava com a PR de 2555145 — nada via onde o numero
    terminava, e o chamado curto roubava a entrega do longo.
    """
    return re.compile(re.escape("ch" + chamado) + r"(?!\d)")


def _casa(pr: PrIndex, padrao: re.Pattern[str]) -> bool:
    # match no titulo (ancorado, como o startswith de antes) e search na branch,
    # onde o termo pode estar em qualquer posicao.
    return padrao.match(pr.titulo) is not None or padrao.search(pr.branch) is not None


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
    # Obrigatorios: o indice local de PRs vive no estado, e sem ele esta fonte
    # nao tem o que ler. Quem nao tem banco monta so o grep (ver montagem.py).
    # `repo_estado` e o nome canonico no banco, que nao e necessariamente o
    # `repo` do Bitbucket — e para isso que aliases existem.
    estado: EstadoRepo = field(kw_only=True)
    repo_estado: str = field(kw_only=True)

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
        # Fecha so o que criamos: cliente injetado pertence a quem injetou.
        with contextlib.ExitStack() as pilha:
            client = self.client
            if client is None:
                client = pilha.enter_context(httpx.Client())

            self.progresso(Progresso("varrendo PRs do Bitbucket"))
            self._varrer(client)
            indice = self.estado.prs_indexadas(self.repo_estado)

            for posicao, chamado in enumerate(chamados, start=1):
                # Relata antes de filtrar: o total e o tamanho do lote pedido, e
                # uma barra que pula numeros por causa de chamado vazio confunde
                # mais do que informa.
                self.progresso(
                    Progresso(
                        "commits dos chamados no Bitbucket", posicao, len(chamados)
                    )
                )
                if not chamado:  # sem numero nao tem como casar PR
                    continue
                commits = self._commits_do_chamado(client, chamado, indice)
                if commits:
                    resultado[chamado] = commits
        return resultado

    def _varrer(self, client: httpx.Client) -> None:
        """Uma passada que descobre tudo que mergeou desde a ultima.

        Substitui uma busca por chamado (27 requests numa versao real) por uma
        pergunta so. O que responde "quais PRs casam com ch1234" passa a ser o
        indice local, nao a API.
        """
        # Marca = inicio da varredura, nao o maior `updated_on` visto. PR
        # mergeada DURANTE esta varredura pode nao aparecer nela; com o inicio
        # como marca, o `updated_on` dela e maior e a proxima janela a pega.
        inicio = datetime.datetime.now(datetime.timezone.utc)
        marca = self.estado.marca_varredura(self.repo_estado)

        params: dict[str, object] = {
            "state": "MERGED",
            "sort": "updated_on",
            "pagelen": 50,
        }
        if marca is not None:
            # `>=` e nao `>`: reentregar PR ja conhecida e upsert, e a sobreposicao
            # e o que cobre quem mergeou no meio da varredura anterior.
            params["q"] = f'updated_on >= "{marca.isoformat()}"'
        # Sem marca = nunca varrido: baixa o historico inteiro. Filtrar por data
        # aqui deixaria de fora toda PR anterior, e o chamado com PR antiga
        # apareceria como sem entrega.

        # Extrai (e valida a forma) antes de filtrar: `pr.get("id")` num item
        # que nao e dict estouraria AttributeError cru, escapando do contrato.
        indices = [self._para_pr_index(pr) for pr in self._paginar(client, self._prs_url(), params)]
        prs = [indice for indice in indices if indice.pr_id]
        # Indice e marca na mesma escrita: paginacao que levantou no meio nunca
        # chega aqui, entao a marca nao avanca por cima de um indice furado.
        self.estado.gravar_varredura(self.repo_estado, prs, inicio)

    def _prs_url(self) -> str:
        base = self.base_url or _BASE_URL_PADRAO
        workspace, repo = self._workspace_repo()
        return f"{base}/repositories/{workspace}/{repo}/pullrequests"

    def _commits_do_chamado(
        self, client: httpx.Client, chamado: str, indice: list[PrIndex]
    ) -> list[CommitRef]:
        padrao = _padrao_do_chamado(chamado)
        pr_ids = [pr.pr_id for pr in indice if _casa(pr, padrao)]

        por_pr = self.estado.commits_de_pr(self.repo_estado, pr_ids)
        # So as PRs que casam com um chamado pedido vao na API. O indice tem
        # 1118 PRs num repo real; buscar os commits de todas encostaria no limite
        # de taxa para responder pergunta que ninguem fez.
        novas = {
            pr_id: self._buscar_commits(client, pr_id)
            for pr_id in pr_ids
            if pr_id not in por_pr
        }
        # ponytail: PR cujos commits sao todos merge commit grava vazio e vira
        # miss em todo run. Custa 1 request por run e nao tem PR assim na
        # pratica; se aparecer, o conserto e uma linha-sentinela por PR.
        if novas:
            self.estado.gravar_commits_de_pr(self.repo_estado, novas)
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
                # o chamado vem do casamento, nao da PR: duas tarefas podem
                # apontar para a mesma PR, entao ele e carimbado aqui.
                commits.append(replace(c, chamado=chamado))
        commits.sort(key=lambda c: c.commit_date)
        return commits

    def _buscar_commits(self, client: httpx.Client, pr_id: int) -> list[CommitRef]:
        return [
            self._para_commit_ref(c)
            for c in self._paginar(client, f"{self._prs_url()}/{pr_id}/commits", None)
            # merge commit: cherry-pick -x nao aceita sem -m, e o conteudo ja vem
            # pelos pais individuais. Numero de pais e propriedade do commit,
            # nunca muda — por isso filtra antes de cachear.
            if c.get("hash") and len(c.get("parents") or []) <= 1
        ]

    @staticmethod
    def _para_pr_index(pr: JSON) -> PrIndex:
        """Titulo e branch crus: o casamento e predicado, nao extracao.

        Guarda de forma herdada de `_pr_casa`: e aqui, na extracao do JSON cru
        da API, que o formato inesperado tem que ser pego — depois deste ponto
        o resto do modulo so ve `PrIndex` ja validado.
        """
        if not isinstance(pr, dict):
            raise RespostaInvalida(f"PR do Bitbucket em formato inesperado: {pr!r}")
        titulo = pr.get("title") or ""
        if not isinstance(titulo, str):
            raise RespostaInvalida(f"title da PR do Bitbucket em formato inesperado: {titulo!r}")
        bruto = pr.get("updated_on", "")
        try:
            quando = datetime.datetime.fromisoformat(bruto) if bruto else SEM_DATA
        except ValueError:
            quando = SEM_DATA
        return PrIndex(
            # get com default 0, nao pr["id"]: PR sem id e descartada pelo
            # filtro de pr_id em `_varrer`, nao um erro de forma.
            pr_id=pr.get("id") or 0,
            titulo=titulo,
            branch=((pr.get("source") or {}).get("branch") or {}).get("name") or "",
            updated_on=quando,
        )

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
