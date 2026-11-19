"""Código do host GitLab compartilhado pela fonte de tarefas e pela de PR.

URL base, cabeçalho, token, `GET`, paginação pelo `Link` e tradução de status
são um só para as duas partes do pacote (docs/decisoes/044-plugins-por-host.md).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from enum import StrEnum
from urllib.parse import quote

import httpx

from motor.config import TABELA_AMBIENTE, Tabela
from motor.config_edicao import Campo, Escopo, TipoCampo
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida

URL_PADRAO = "https://gitlab.com"
CHAVE_URL = "url"
CAMINHO_API = "/api/v4"
CAMINHO_EU = "/user"
POR_PAGINA = "per_page"
_PREFIXO_URL = "https://"
_ITENS_POR_PAGINA = 100
_LINK_PROXIMA = "next"
_LINK_URL = "url"


class _Cabecalho(StrEnum):
    TOKEN = "PRIVATE-TOKEN"


class VarGitlab(StrEnum):
    """Variáveis do `[ambiente]` que este plugin lê."""

    TOKEN = "GITLAB_TOKEN"


# Um só campo para as duas partes do pacote: o texto vale para os dois papéis.
CAMPO_TOKEN = Campo(
    Escopo.AMBIENTE,
    TABELA_AMBIENTE,
    VarGitlab.TOKEN,
    TipoCampo.TEXTO,
    "Token do GitLab",
    segredo=True,
    descricao="Token com escopo read_api, para as issues e os merge requests do projeto",
    aviso_vazio=(
        "Obrigatório para a fonte de PR; nas tarefas, sem token uma versão "
        "inexistente (erro de digitação) aparece como versão sem tarefas, "
        "e não como erro"
    ),
)


def caminho_projeto(projeto: str) -> str:
    return f"/projects/{quote(projeto, safe='')}"


def _sob_a_base(url: httpx.URL, base: httpx.URL) -> bool:
    return (url.scheme, url.host, url.port) == (
        base.scheme,
        base.host,
        base.port,
    ) and url.raw_path.startswith(base.raw_path.rstrip(b"/") + b"/")


def _traduzir_status(
    resp: httpx.Response,
    token: str,
    projeto: str | None,
    tabela: Tabela,
    dica_projeto: str,
) -> None:
    """Status de erro da API como erro do motor, na ordem da tabela da spec."""
    status = resp.status_code
    alvo, ao_alvo = (
        (f"o projeto {projeto!r}", f"ao projeto {projeto!r}")
        if projeto
        else ("a conta", "à conta")
    )
    if status == httpx.codes.TOO_MANY_REQUESTS:
        raise BackendIndisponivel(
            f"GitLab atingiu o limite de requisições ({status}); tente mais tarde"
        )
    if status == httpx.codes.UNAUTHORIZED:
        if token:
            raise ErroDeEntrada(
                f"GitLab recusou a credencial ({status}): confira {VarGitlab.TOKEN}"
            )
        raise ErroDeEntrada(
            f"GitLab exige autenticação para {alvo}: "
            f"defina [{TABELA_AMBIENTE}] {VarGitlab.TOKEN}"
        )
    if status == httpx.codes.FORBIDDEN:
        raise ErroDeEntrada(
            f"sem acesso {ao_alvo} ({status}): confira o {VarGitlab.TOKEN}"
        )
    if status == httpx.codes.NOT_FOUND:
        if projeto is None:
            raise ErroDeEntrada(
                f"a API do GitLab não foi encontrada ({status}): "
                f"confira [{tabela}] {CHAVE_URL}"
            )
        # Projeto privado pedido sem token também responde 404.
        raise ErroDeEntrada(
            f"{alvo} não foi encontrado ou o token não tem acesso: {dica_projeto}"
        )
    if status != httpx.codes.OK:
        raise BackendIndisponivel(f"GitLab respondeu {status}")


class ApiGitlab:
    """Cliente da API REST do GitLab, com os erros traduzidos para o motor.

    `reaproveitar=True` cria um cliente na primeira requisição e o mantém até
    `fechar()`; `False` abre um por requisição. Cliente injetado é de quem
    injetou: nunca é fechado aqui.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        url: object,
        tabela: Tabela,
        token: Callable[[], str],
        client: httpx.Client | None,
        reaproveitar: bool,
        dica_projeto: Callable[[str], str],
    ) -> None:
        self._url = url
        self._tabela = tabela
        self._token = token
        self._client = client
        self._injetado = client
        self._reaproveitar = reaproveitar
        self._dica_projeto = dica_projeto
        # `commits_da_pr` roda em várias threads, e a primeira chamada pode ser
        # concorrente.
        self._trava = threading.Lock()

    def base(self) -> str:
        bruto = self._url.strip() if isinstance(self._url, str) else ""
        base = (bruto or URL_PADRAO).rstrip("/")
        # Sem esquema, o httpx levanta UnsupportedProtocol (HTTPError): sairia como GitLab fora.
        if not base.lower().startswith(_PREFIXO_URL):
            raise ErroDeEntrada(
                f"[{self._tabela}] {CHAVE_URL} deve começar com "
                f"{_PREFIXO_URL}: {base!r}"
            )
        return base

    def url(self, caminho: str) -> str:
        return self.base() + CAMINHO_API + caminho

    def _cliente(self) -> httpx.Client | None:
        """O cliente a usar, ou None para abrir um só para a requisição."""
        if self._injetado is not None or not self._reaproveitar:
            return self._injetado
        with self._trava:
            if self._client is None:
                self._client = httpx.Client()
            return self._client

    def fechar(self) -> None:
        """Fecha o cliente próprio; o injetado é de quem injetou."""
        with self._trava:
            if self._client is not None and self._client is not self._injetado:
                try:
                    self._client.close()
                finally:
                    self._client = None

    def get(
        self,
        url: str,
        params: Mapping[str, str] | None,
        projeto: str | None,
        *,
        ausente: bool = False,
    ) -> httpx.Response | None:
        """GET com rede e status traduzidos; `ausente=True` devolve None no 404."""
        token = self._token()
        headers: dict[str, str] = {_Cabecalho.TOKEN: token} if token else {}
        try:
            client = self._cliente()
            if client is not None:
                resp = client.get(url, params=params, headers=headers)
            else:
                with httpx.Client() as proprio:
                    resp = proprio.get(url, params=params, headers=headers)
        except httpx.InvalidURL as e:
            raise ErroDeEntrada(f"URL do GitLab inválida: {url!r}: {e}") from e
        except httpx.HTTPError as e:
            raise BackendIndisponivel(f"chamando o GitLab: {e}") from e
        if ausente and resp.status_code == httpx.codes.NOT_FOUND:
            return None
        _traduzir_status(
            resp,
            token,
            projeto,
            self._tabela,
            self._dica_projeto(projeto) if projeto else "",
        )
        return resp

    def obter(
        self, url: str, params: Mapping[str, str] | None, projeto: str | None
    ) -> httpx.Response:
        """`get` sem o caso ausente: sempre devolve a resposta."""
        resp = self.get(url, params, projeto)
        assert resp is not None  # sem `ausente`, 404 levanta
        return resp

    @staticmethod
    def json(resp: httpx.Response) -> object:
        try:
            return resp.json()
        except ValueError as e:
            raise RespostaInvalida(f"decodificando resposta do GitLab: {e}") from e

    def listar(
        self,
        caminho: str,
        params: Mapping[str, str],
        projeto: str,
        *,
        ausente: bool = False,
    ) -> list[object] | None:
        """Todos os itens de uma lista paginada pelo `Link`; `ausente` vale por página."""
        base = self.base()
        url: str | httpx.URL = self.url(caminho)
        pedido: Mapping[str, str] | None = {
            **params,
            POR_PAGINA: str(_ITENS_POR_PAGINA),
        }
        pedidas: set[httpx.URL] = set()
        itens: list[object] = []
        while True:
            resp = self.get(str(url), pedido, projeto, ausente=ausente)
            if resp is None:
                return None
            pedidas.add(resp.request.url)
            corpo = self.json(resp)
            if not isinstance(corpo, list):
                raise RespostaInvalida(
                    f"resposta do GitLab em formato inesperado: {corpo!r}"
                )
            itens.extend(corpo)
            bruta = resp.links.get(_LINK_PROXIMA, {}).get(_LINK_URL)
            if bruta is None:
                return itens
            try:
                proxima = httpx.URL(bruta)
            except httpx.InvalidURL as e:
                raise RespostaInvalida(
                    f"GitLab mandou página inválida {bruta!r}"
                ) from e
            # O token iria junto: só segue página sob a URL configurada.
            if not _sob_a_base(proxima, httpx.URL(base)):
                raise RespostaInvalida(
                    f"GitLab apontou página fora de {base}: {bruta!r}"
                )
            if proxima in pedidas:
                raise RespostaInvalida(f"GitLab repetiu a página {bruta!r}")
            # A URL do `Link` já traz todos os parâmetros.
            url, pedido = proxima, None
