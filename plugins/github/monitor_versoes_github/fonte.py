"""FonteGithub: plugin `TaskSource` do GitHub Issues (`[tarefas] fonte = "github"`)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum

import httpx

from motor.config import TABELA_AMBIENTE, Tabela
from motor.config_edicao import Campo, Escopo, TipoCampo
from motor.domain.referencia import Referencia
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida

_ALFABETO_NUMERICO = "0-9"
_API_PADRAO = "https://api.github.com"
_PREFIXO_URL = "https://"
_CAMINHO_EU = "/user"
_POR_PAGINA = 100
_TODOS = "all"
_ACCEPT = "application/vnd.github+json"
# Não a 2026-03-10: a 2022-11-28 é a que todo GitHub Enterprise Server atende (suporte até 2028).
_VERSAO_API = "2022-11-28"
_RATE_LIMIT_ESGOTADO = "0"
_LINK_PROXIMA = "next"
_LINK_URL = "url"


class _Param(StrEnum):
    """Parâmetros de query da API REST."""

    STATE = "state"
    MILESTONE = "milestone"
    POR_PAGINA = "per_page"


class _Campo(StrEnum):
    """Campos do JSON de milestones e issues."""

    NUMBER = "number"
    TITLE = "title"
    PULL_REQUEST = "pull_request"


class _Cabecalho(StrEnum):
    ACCEPT = "Accept"
    VERSAO_API = "X-GitHub-Api-Version"
    AUTH = "Authorization"
    RESTANTE = "x-ratelimit-remaining"
    RETRY_AFTER = "retry-after"


class ChaveTarefas(StrEnum):
    """Chaves do `[tarefas]` que este plugin lê."""

    REPO = "repo"
    API_URL = "api_url"


class VarGithub(StrEnum):
    """Variáveis do `[ambiente]` que este plugin lê."""

    TOKEN = "GITHUB_TOKEN"


def _numero(item: object) -> int:
    numero = item.get(_Campo.NUMBER) if isinstance(item, dict) else None
    if not isinstance(numero, int) or isinstance(numero, bool):
        raise RespostaInvalida(f"item do GitHub sem número inteiro: {item!r}")
    return numero


def _traduzir_status(resp: httpx.Response, token: str, repo: str | None) -> None:
    """Status de erro da API como erro do motor, na ordem da tabela da spec."""
    status = resp.status_code
    alvo = f"o repo {repo!r}" if repo else "a conta"
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
            f"sem acesso a {alvo} ({status}): confira o {VarGithub.TOKEN}"
        )
    if status == httpx.codes.NOT_FOUND:
        raise ErroDeEntrada(
            f"{alvo} não foi encontrado ou o token não tem acesso: "
            f"confira [{Tabela.TAREFAS}] {ChaveTarefas.REPO}"
        )
    if status != httpx.codes.OK:
        raise BackendIndisponivel(f"GitHub respondeu {status}")


class FonteGithub:
    """`TaskSource` do GitHub Issues."""

    campos_config = (
        Campo(
            Escopo.GERAL,
            Tabela.TAREFAS,
            ChaveTarefas.REPO,
            TipoCampo.TEXTO,
            "Repositório do GitHub",
            descricao="Repositório das issues, no formato dono/nome",
            exemplo="empresa/produto",
        ),
        Campo(
            Escopo.GERAL,
            Tabela.TAREFAS,
            ChaveTarefas.API_URL,
            TipoCampo.TEXTO,
            "URL da API do GitHub",
            descricao="Só muda no GitHub Enterprise Server",
            padrao=_API_PADRAO,
            exemplo="https://github.empresa.com/api/v3",
        ),
        Campo(
            Escopo.AMBIENTE,
            TABELA_AMBIENTE,
            VarGithub.TOKEN,
            TipoCampo.TEXTO,
            "Token do GitHub",
            segredo=True,
            descricao="Token com leitura das issues do repositório",
            aviso_vazio=(
                "Sem token, o GitHub limita a 60 requisições por hora e buscas "
                "de versões grandes podem falhar"
            ),
        ),
    )

    def __init__(
        self,
        *,
        tarefas: Mapping[str, object],
        arquivos: tuple[str, ...],
        env: Mapping[str, str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._tarefas = tarefas
        self._arquivos = arquivos
        self._env = env
        self._client = client

    def __repr__(self) -> str:
        # Sem credencial: o repr aparece com --debug e em exceção.
        return "FonteGithub()"

    def _tarefa(self, chave: ChaveTarefas) -> str:
        bruto = self._tarefas.get(chave)
        return bruto.strip() if isinstance(bruto, str) else ""

    def _repo(self) -> str:
        repo = self._tarefa(ChaveTarefas.REPO)
        if not repo:
            lida = " e ".join(self._arquivos) or "nenhuma"
            raise ErroDeEntrada(
                f"faltando [{Tabela.TAREFAS}] {ChaveTarefas.REPO} (config lida: {lida})"
            )
        return repo

    def _token(self) -> str:
        env = os.environ if self._env is None else self._env
        return env.get(VarGithub.TOKEN, "").strip()

    @property
    def referencia(self) -> Referencia:
        return Referencia("#{id}", _ALFABETO_NUMERICO)

    def _base(self) -> str:
        base = (self._tarefa(ChaveTarefas.API_URL) or _API_PADRAO).rstrip("/")
        # Sem esquema, o httpx levanta UnsupportedProtocol (HTTPError): sairia como GitHub fora.
        if not base.lower().startswith(_PREFIXO_URL):
            raise ErroDeEntrada(
                f"[{Tabela.TAREFAS}] {ChaveTarefas.API_URL} deve começar com "
                f"{_PREFIXO_URL}: {base!r}"
            )
        return base

    def _get(
        self, url: str, params: Mapping[str, str] | None, repo: str | None
    ) -> httpx.Response:
        """GET com rede e status traduzidos para erros do motor."""
        token = self._token()
        headers: dict[str, str] = {
            _Cabecalho.ACCEPT: _ACCEPT,
            _Cabecalho.VERSAO_API: _VERSAO_API,
        }
        if token:
            headers[_Cabecalho.AUTH] = f"Bearer {token}"
        try:
            if self._client is not None:
                resp = self._client.get(url, params=params, headers=headers)
            else:
                with httpx.Client() as client:
                    resp = client.get(url, params=params, headers=headers)
        except httpx.InvalidURL as e:
            raise ErroDeEntrada(f"URL do GitHub inválida: {url!r}: {e}") from e
        except httpx.HTTPError as e:
            raise BackendIndisponivel(f"chamando o GitHub: {e}") from e
        _traduzir_status(resp, token, repo)
        return resp

    def _listar(
        self, caminho: str, params: Mapping[str, str], repo: str
    ) -> list[object]:
        """Todos os itens de uma lista paginada pelo cabeçalho `Link`."""
        url = self._base() + caminho
        pedido: Mapping[str, str] | None = {
            **params,
            _Param.POR_PAGINA: str(_POR_PAGINA),
        }
        pedidas: set[str] = set()
        itens: list[object] = []
        while True:
            resp = self._get(url, pedido, repo)
            pedidas.add(str(resp.request.url))
            try:
                corpo = resp.json()
            except ValueError as e:
                raise RespostaInvalida(f"decodificando resposta do GitHub: {e}") from e
            if not isinstance(corpo, list):
                raise RespostaInvalida(
                    f"resposta do GitHub em formato inesperado: {corpo!r}"
                )
            itens.extend(corpo)
            proxima = resp.links.get(_LINK_PROXIMA, {}).get(_LINK_URL)
            if proxima is None:
                return itens
            if proxima in pedidas:
                raise RespostaInvalida(f"GitHub repetiu a página {proxima!r}")
            # A URL do `Link` já traz todos os parâmetros.
            url, pedido = proxima, None

    def verificar_credenciais(self) -> str | None:
        if not self._token():
            return f"sem {VarGithub.TOKEN}: acesso anônimo, nada a verificar"
        self._get(self._base() + _CAMINHO_EU, None, None)
        return None

    def fetch(self, versao: str, /) -> list[str]:
        repo = self._repo()
        milestones = self._listar(
            f"/repos/{repo}/milestones", {_Param.STATE: _TODOS}, repo
        )
        numero = next(
            (
                _numero(m)
                for m in milestones
                if isinstance(m, dict) and m.get(_Campo.TITLE) == versao
            ),
            None,
        )
        if numero is None:
            raise ErroDeEntrada(f"milestone {versao!r} não existe no repo {repo!r}")
        issues = self._listar(
            f"/repos/{repo}/issues",
            {_Param.MILESTONE: str(numero), _Param.STATE: _TODOS},
            repo,
        )
        ids = [
            str(_numero(i))
            for i in issues
            if not (isinstance(i, dict) and _Campo.PULL_REQUEST in i)
        ]
        return list(dict.fromkeys(ids))
