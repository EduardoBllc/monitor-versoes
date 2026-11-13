"""BitbucketPrs: plugin `HostPr` do Bitbucket Cloud (`[prs] fonte = "bitbucket"`).

Só fala com a API: varredura, índice, casamento com a referência, cache e
filtro pela principal são do núcleo (`PrCommitSource`,
docs/decisoes/036-fonte-de-pr-plugavel.md).

Montar não é usar: o construtor não lê credencial nem toca o git. Token,
e-mail e o `workspace/repo` (da URL do `origin`) saem na primeira chamada.

API Bitbucket Cloud 2.0:
  GET /2.0/repositories/{ws}/{repo}/pullrequests?q=...&state=MERGED&pagelen=50
  GET /2.0/repositories/{ws}/{repo}/pullrequests/{id}/commits
Auth: Authorization: Basic base64(email:token). Paginação pelo campo `next`.
"""

from __future__ import annotations

import base64
import contextlib
import datetime
import os
import re
from collections.abc import Callable, Iterator, Mapping
from enum import StrEnum
from typing import Any

import httpx

from motor.config import TABELA_AMBIENTE
from motor.config_edicao import Campo, Escopo, TipoCampo
from motor.domain.types import SEM_DATA, CommitRef, PrIndex
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida

# Corpo de JSON da API: dict de chaves str para qualquer coisa. Não é um dict
# tipado — a issue #42 registra que o contrato ainda não foi observado.
JSON = dict[str, Any]

_BASE_URL_PADRAO = "https://api.bitbucket.org/2.0"

# git@bitbucket.org:ws/repo.git  |  https://user@bitbucket.org/ws/repo(.git)
_PADRAO_REMOTE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")


class Var(StrEnum):
    """Variáveis do `[ambiente]` que este plugin lê."""

    TOKEN = "BITBUCKET_TOKEN"
    EMAIL = "BITBUCKET_EMAIL"


def _cabecalho_basic(email: str, token: str) -> str:
    credenciais = base64.b64encode(f"{email}:{token}".encode()).decode()
    return f"Basic {credenciais}"


def parse_workspace_repo(url: str) -> tuple[str, str]:
    """Extrai (workspace, repo) da URL do remote origin."""
    # pega os dois últimos segmentos de path (ws/repo), com ou sem host embutido.
    m = _PADRAO_REMOTE.search(url.strip())
    if m is None:
        raise RespostaInvalida(f"nao consegui extrair workspace/repo de {url!r}")
    return m.group(1), m.group(2)


class BitbucketPrs:
    """`HostPr` do Bitbucket Cloud."""

    campos_config = (
        Campo(
            Escopo.AMBIENTE,
            TABELA_AMBIENTE,
            Var.EMAIL,
            TipoCampo.TEXTO,
            "E-mail do Bitbucket",
            descricao="E-mail da conta do Bitbucket",
            exemplo="voce@empresa.com",
        ),
        Campo(
            Escopo.AMBIENTE,
            TABELA_AMBIENTE,
            Var.TOKEN,
            TipoCampo.TEXTO,
            "Token do Bitbucket",
            segredo=True,
            descricao="API token da conta do Bitbucket",
        ),
    )

    def __init__(
        self,
        *,
        prs: Mapping[str, object],
        arquivos: tuple[str, ...],
        remote_url: Callable[[], str],
        client: httpx.Client | None = None,
        base_url: str = "",
    ) -> None:
        self._prs = prs
        self._arquivos = arquivos
        self._remote_url = remote_url
        # Cliente injetado pertence a quem injetou; sem ele, um por requisição.
        self._client = client
        self._base_url = base_url or _BASE_URL_PADRAO
        self._workspace_repo: tuple[str, str] | None = None

    def __repr__(self) -> str:
        # Sem credencial: o repr aparece com --debug e em exceção.
        return f"BitbucketPrs(base_url={self._base_url!r})"

    def _credencial(self, var: Var) -> str:
        valor = os.environ.get(var, "").strip()
        if not valor:
            lida = " e ".join(self._arquivos) or "nenhuma"
            raise ErroDeEntrada(
                f'[prs] fonte = "bitbucket" sem {var}: defina-a no [ambiente] do '
                f"config.toml central ou no shell (config lida: {lida})"
            )
        return valor

    def _auth_header(self) -> str:
        return _cabecalho_basic(
            self._credencial(Var.EMAIL), self._credencial(Var.TOKEN)
        )

    def _prs_url(self) -> str:
        if self._workspace_repo is None:
            self._workspace_repo = parse_workspace_repo(self._remote_url())
        workspace, repo = self._workspace_repo
        return f"{self._base_url}/repositories/{workspace}/{repo}/pullrequests"

    @contextlib.contextmanager
    def _cliente(self) -> Iterator[httpx.Client]:
        if self._client is not None:
            yield self._client
            return
        with httpx.Client() as client:
            yield client

    def verificar_credenciais(self) -> None:
        """Chamada autenticada de leitura (`GET /user`), independente de repo.

        O endpoint exige escopo de leitura de conta no token. Usado pelo
        `monitor-versoes diagnostico`.
        """
        auth = self._auth_header()
        with self._cliente() as client:
            try:
                resp = client.get(
                    f"{self._base_url}/user", headers={"Authorization": auth}
                )
            except httpx.HTTPError as e:
                raise BackendIndisponivel(f"consultando o Bitbucket: {e}") from e
        if resp.status_code != httpx.codes.OK:
            raise BackendIndisponivel(
                f"Bitbucket respondeu {resp.status_code} ao validar a credencial"
            )
        try:
            resp.json()
        except ValueError as e:
            raise RespostaInvalida(f"decodificando resposta do Bitbucket: {e}") from e

    def prs_mergeadas(self, desde: datetime.datetime | None, /) -> list[PrIndex]:
        params: dict[str, object] = {
            "state": "MERGED",
            "sort": "updated_on",
            "pagelen": 50,
        }
        if desde is not None:
            params["q"] = f'updated_on >= "{desde.isoformat()}"'
        # Lista, não gerador: a paginação inteira acontece aqui, dentro do
        # cliente aberto. Extrai (e valida a forma) antes de filtrar: `.get` num
        # item que não é dict estouraria AttributeError cru.
        # Credencial antes do remote: a falta dela é o erro que o operador
        # precisa ver primeiro.
        auth = self._auth_header()
        with self._cliente() as client:
            indices = [
                self._para_pr_index(pr)
                for pr in self._paginar(client, auth, self._prs_url(), params)
            ]
        return [indice for indice in indices if indice.pr_id]

    def commits_da_pr(self, pr_id: int, /) -> list[CommitRef]:
        auth = self._auth_header()
        with self._cliente() as client:
            return [
                self._para_commit_ref(c)
                for c in self._paginar(
                    client, auth, f"{self._prs_url()}/{pr_id}/commits", None
                )
                # merge commit: cherry-pick -x não aceita sem -m, e o conteúdo
                # já vem pelos pais individuais. O núcleo cacheia o que vier,
                # então o filtro tem de ser aqui.
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
            raise RespostaInvalida(
                f"title da PR do Bitbucket em formato inesperado: {titulo!r}"
            )
        bruto = pr.get("updated_on", "")
        try:
            quando = datetime.datetime.fromisoformat(bruto) if bruto else SEM_DATA
        except ValueError:
            quando = SEM_DATA
        return PrIndex(
            # get com default 0, nao pr["id"]: PR sem id e descartada pelo
            # filtro de pr_id em `prs_mergeadas`, nao um erro de forma.
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

    @staticmethod
    def _paginar(
        client: httpx.Client, auth: str, url: str, params: JSON | None
    ) -> Iterator[JSON]:
        """Itera os `values` de uma resposta paginada, seguindo `next`."""
        while url:
            try:
                resp = client.get(url, params=params, headers={"Authorization": auth})
            except httpx.InvalidURL as e:
                raise ErroDeEntrada(f"URL do Bitbucket invalida: {url!r}: {e}") from e
            except httpx.HTTPError as e:
                raise BackendIndisponivel(f"chamando Bitbucket {url}: {e}") from e
            if resp.status_code != httpx.codes.OK:
                raise BackendIndisponivel(
                    f"Bitbucket respondeu {resp.status_code} em {url}: {resp.text}"
                )
            try:
                corpo = resp.json()
            except ValueError as e:
                raise RespostaInvalida(
                    f"decodificando resposta do Bitbucket em {url}: {e}"
                ) from e
            if not isinstance(corpo, dict):
                raise RespostaInvalida(
                    f"resposta do Bitbucket em formato inesperado em {url}: {corpo!r}"
                )
            yield from corpo.get("values", [])
            url = corpo.get("next", "")
            params = None  # `next` ja traz a query embutida
