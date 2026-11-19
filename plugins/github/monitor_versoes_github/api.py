"""Código do host GitHub compartilhado pela fonte de tarefas e pela de PR.

URL base, cabeçalhos, token, `GET`, paginação pelo `Link` e tradução de status
são um só para as duas partes do pacote (docs/decisoes/044-plugins-por-host.md).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Mapping
from enum import StrEnum

import httpx

from motor.config import TABELA_AMBIENTE, Tabela
from motor.config_edicao import Campo, Escopo, TipoCampo
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida

API_PADRAO = "https://api.github.com"
CHAVE_API_URL = "api_url"
CAMINHO_EU = "/user"
POR_PAGINA = "per_page"
_PREFIXO_URL = "https://"
_ITENS_POR_PAGINA = 100
_ACCEPT = "application/vnd.github+json"
# Não a 2026-03-10: a 2022-11-28 é a que todo GitHub Enterprise Server atende (suporte até 2028).
_VERSAO_API = "2022-11-28"
_RATE_LIMIT_ESGOTADO = "0"
_LINK_PROXIMA = "next"
_LINK_URL = "url"


class _Cabecalho(StrEnum):
    ACCEPT = "Accept"
    VERSAO_API = "X-GitHub-Api-Version"
    AUTH = "Authorization"
    RESTANTE = "x-ratelimit-remaining"
    RETRY_AFTER = "retry-after"


class VarGithub(StrEnum):
    """Variáveis do `[ambiente]` que este plugin lê."""

    TOKEN = "GITHUB_TOKEN"


# Um só campo para as duas partes do pacote: o texto vale para os dois papéis.
CAMPO_TOKEN = Campo(
    Escopo.AMBIENTE,
    TABELA_AMBIENTE,
    VarGithub.TOKEN,
    TipoCampo.TEXTO,
    "Token do GitHub",
    segredo=True,
    descricao="Token com leitura das issues e dos pull requests do repositório",
    aviso_vazio=(
        "Obrigatório para a fonte de PR; nas tarefas, sem token o GitHub limita "
        "a 60 requisições por hora e buscas de versões grandes podem falhar"
    ),
)


def _sob_a_base(url: httpx.URL, base: httpx.URL) -> bool:
    return (url.scheme, url.host, url.port) == (
        base.scheme,
        base.host,
        base.port,
    ) and url.raw_path.startswith(base.raw_path.rstrip(b"/") + b"/")


def _traduzir_status(
    resp: httpx.Response,
    token: str,
    repo: str | None,
    tabela: Tabela,
    dica_repo: str,
) -> None:
    """Status de erro da API como erro do motor, na ordem da tabela da spec."""
    status = resp.status_code
    alvo, ao_alvo = (
        (f"o repo {repo!r}", f"ao repo {repo!r}") if repo else ("a conta", "à conta")
    )
    if status == httpx.codes.TOO_MANY_REQUESTS or (
        status == httpx.codes.FORBIDDEN
        and (
            resp.headers.get(_Cabecalho.RESTANTE) == _RATE_LIMIT_ESGOTADO
            or _Cabecalho.RETRY_AFTER in resp.headers
        )
    ):
        raise BackendIndisponivel(
            f"GitHub atingiu o limite de requisições ({status}); tente mais tarde"
            + ("" if token else f" ou defina {VarGithub.TOKEN}")
        )
    if status == httpx.codes.UNAUTHORIZED:
        if token:
            raise ErroDeEntrada(
                f"GitHub recusou a credencial ({status}): confira {VarGithub.TOKEN}"
            )
        raise ErroDeEntrada(
            f"GitHub exige autenticação para {alvo}: "
            f"defina [{TABELA_AMBIENTE}] {VarGithub.TOKEN}"
        )
    if status == httpx.codes.FORBIDDEN:
        raise ErroDeEntrada(
            f"sem acesso {ao_alvo} ({status}): confira o {VarGithub.TOKEN}"
        )
    if status == httpx.codes.NOT_FOUND:
        if repo is None:
            raise ErroDeEntrada(
                f"a API do GitHub não foi encontrada ({status}): "
                f"confira [{tabela}] {CHAVE_API_URL}"
            )
        # Repo privado pedido sem token também responde 404.
        raise ErroDeEntrada(
            f"{alvo} não foi encontrado ou o token não tem acesso: {dica_repo}"
        )
    if status != httpx.codes.OK:
        raise BackendIndisponivel(f"GitHub respondeu {status}")


class ApiGithub:
    """Cliente da API REST do GitHub, com os erros traduzidos para o motor.

    `reaproveitar=True` cria um cliente na primeira requisição e o mantém até
    `fechar()`; `False` abre um por requisição. Cliente injetado é de quem
    injetou: nunca é fechado aqui.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        api_url: object,
        tabela: Tabela,
        token: Callable[[], str],
        client: httpx.Client | None,
        reaproveitar: bool,
        dica_repo: Callable[[str], str],
    ) -> None:
        self._api_url = api_url
        self._tabela = tabela
        self._token = token
        self._client = client
        self._injetado = client
        self._reaproveitar = reaproveitar
        self._dica_repo = dica_repo
        # `commits_da_pr` roda em várias threads, e a primeira chamada pode ser
        # concorrente.
        self._trava = threading.Lock()

    def base(self) -> str:
        bruto = self._api_url.strip() if isinstance(self._api_url, str) else ""
        base = (bruto or API_PADRAO).rstrip("/")
        # Sem esquema, o httpx levanta UnsupportedProtocol (HTTPError): sairia como GitHub fora.
        if not base.lower().startswith(_PREFIXO_URL):
            raise ErroDeEntrada(
                f"[{self._tabela}] {CHAVE_API_URL} deve começar com "
                f"{_PREFIXO_URL}: {base!r}"
            )
        return base

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
        repo: str | None,
        *,
        ausente: bool = False,
    ) -> httpx.Response | None:
        """GET com rede e status traduzidos; `ausente=True` devolve None no 404."""
        token = self._token()
        headers: dict[str, str] = {
            _Cabecalho.ACCEPT: _ACCEPT,
            _Cabecalho.VERSAO_API: _VERSAO_API,
        }
        if token:
            headers[_Cabecalho.AUTH] = f"Bearer {token}"
        try:
            client = self._cliente()
            if client is not None:
                resp = client.get(url, params=params, headers=headers)
            else:
                with httpx.Client() as proprio:
                    resp = proprio.get(url, params=params, headers=headers)
        except httpx.InvalidURL as e:
            raise ErroDeEntrada(f"URL do GitHub inválida: {url!r}: {e}") from e
        except httpx.HTTPError as e:
            raise BackendIndisponivel(f"chamando o GitHub: {e}") from e
        if ausente and resp.status_code == httpx.codes.NOT_FOUND:
            return None
        _traduzir_status(
            resp, token, repo, self._tabela, self._dica_repo(repo) if repo else ""
        )
        return resp

    def obter(
        self, url: str, params: Mapping[str, str] | None, repo: str | None
    ) -> httpx.Response:
        """`get` sem o caso ausente: sempre devolve a resposta."""
        resp = self.get(url, params, repo)
        assert resp is not None  # sem `ausente`, 404 levanta
        return resp

    @staticmethod
    def json(resp: httpx.Response) -> object:
        try:
            return resp.json()
        except ValueError as e:
            raise RespostaInvalida(f"decodificando resposta do GitHub: {e}") from e

    def paginas(
        self, caminho: str, params: Mapping[str, str], repo: str
    ) -> Iterator[list[object]]:
        """Uma lista paginada pelo cabeçalho `Link`, página a página."""
        base = self.base()
        url: str | httpx.URL = base + caminho
        pedido: Mapping[str, str] | None = {
            **params,
            POR_PAGINA: str(_ITENS_POR_PAGINA),
        }
        pedidas: set[httpx.URL] = set()
        while True:
            resp = self.obter(str(url), pedido, repo)
            pedidas.add(resp.request.url)
            corpo = self.json(resp)
            if not isinstance(corpo, list):
                raise RespostaInvalida(
                    f"resposta do GitHub em formato inesperado: {corpo!r}"
                )
            yield corpo
            bruta = resp.links.get(_LINK_PROXIMA, {}).get(_LINK_URL)
            if bruta is None:
                return
            try:
                proxima = httpx.URL(bruta)
            except httpx.InvalidURL as e:
                raise RespostaInvalida(
                    f"GitHub mandou página inválida {bruta!r}"
                ) from e
            # O token iria junto: só segue página sob a api_url configurada.
            if not _sob_a_base(proxima, httpx.URL(base)):
                raise RespostaInvalida(
                    f"GitHub apontou página fora de {base}: {bruta!r}"
                )
            if proxima in pedidas:
                raise RespostaInvalida(f"GitHub repetiu a página {bruta!r}")
            # A URL do `Link` já traz todos os parâmetros.
            url, pedido = proxima, None

    def listar(
        self, caminho: str, params: Mapping[str, str], repo: str
    ) -> list[object]:
        """Todos os itens de uma lista paginada."""
        return [
            item for pagina in self.paginas(caminho, params, repo) for item in pagina
        ]
