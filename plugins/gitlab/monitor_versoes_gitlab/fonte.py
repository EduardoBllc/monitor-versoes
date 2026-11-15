"""FonteGitlab: plugin `TaskSource` do GitLab Issues (`[tarefas] fonte = "gitlab"`)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from urllib.parse import quote

import httpx

from motor.config import TABELA_AMBIENTE, Tabela
from motor.config_edicao import Campo, Escopo, TipoCampo
from motor.domain.referencia import Referencia
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida

_ALFABETO_NUMERICO = "0-9"
_URL_PADRAO = "https://gitlab.com"
_PREFIXO_URL = "https://"
_CAMINHO_API = "/api/v4"
_CAMINHO_EU = "/user"
_POR_PAGINA = 100
_TODOS = "all"
_VERDADE = "true"
_LINK_PROXIMA = "next"
_LINK_URL = "url"


class _Param(StrEnum):
    """Parâmetros de query da API REST."""

    TITLE = "title"
    ANCESTRAIS = "include_ancestors"
    MILESTONE = "milestone"
    ESCOPO = "scope"
    POR_PAGINA = "per_page"


class _Recurso(StrEnum):
    MILESTONES = "milestones"
    ISSUES = "issues"


class _Campo(StrEnum):
    """Campos do JSON de issues."""

    IID = "iid"


class _Cabecalho(StrEnum):
    TOKEN = "PRIVATE-TOKEN"


class ChaveTarefas(StrEnum):
    """Chaves do `[tarefas]` que este plugin lê."""

    PROJETO = "projeto"
    URL = "url"


class VarGitlab(StrEnum):
    """Variáveis do `[ambiente]` que este plugin lê."""

    TOKEN = "GITLAB_TOKEN"


def _iid(item: object) -> int:
    iid = item.get(_Campo.IID) if isinstance(item, dict) else None
    if not isinstance(iid, int) or isinstance(iid, bool):
        raise RespostaInvalida(f"item do GitLab sem iid inteiro: {item!r}")
    return iid


def _sob_a_base(url: httpx.URL, base: httpx.URL) -> bool:
    return (url.scheme, url.host, url.port) == (
        base.scheme,
        base.host,
        base.port,
    ) and url.raw_path.startswith(base.raw_path.rstrip(b"/") + b"/")


def _traduzir_status(resp: httpx.Response, token: str, projeto: str | None) -> None:
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
                f"confira [{Tabela.TAREFAS}] {ChaveTarefas.URL}"
            )
        # Projeto privado pedido sem token também responde 404.
        raise ErroDeEntrada(
            f"{alvo} não foi encontrado ou o token não tem acesso: "
            f"confira [{Tabela.TAREFAS}] {ChaveTarefas.PROJETO}"
            + ("" if token else f" ou defina [{TABELA_AMBIENTE}] {VarGitlab.TOKEN}")
        )
    if status != httpx.codes.OK:
        raise BackendIndisponivel(f"GitLab respondeu {status}")


class FonteGitlab:
    """`TaskSource` do GitLab Issues."""

    campos_config = (
        Campo(
            Escopo.GERAL,
            Tabela.TAREFAS,
            ChaveTarefas.PROJETO,
            TipoCampo.TEXTO,
            "Projeto do GitLab",
            descricao="Caminho completo do projeto (grupo/subgrupo/nome) ou ID numérico",
            exemplo="empresa/produto",
        ),
        Campo(
            Escopo.GERAL,
            Tabela.TAREFAS,
            ChaveTarefas.URL,
            TipoCampo.TEXTO,
            "URL do GitLab",
            descricao="Só muda em GitLab self-managed",
            padrao=_URL_PADRAO,
            exemplo="https://gitlab.empresa.com",
        ),
        Campo(
            Escopo.AMBIENTE,
            TABELA_AMBIENTE,
            VarGitlab.TOKEN,
            TipoCampo.TEXTO,
            "Token do GitLab",
            segredo=True,
            descricao="Token com escopo read_api",
            aviso_vazio=(
                "Sem token, uma versão inexistente (erro de digitação) aparece "
                "como versão sem tarefas, e não como erro"
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
        return "FonteGitlab()"

    def _tarefa(self, chave: ChaveTarefas) -> str:
        bruto = self._tarefas.get(chave)
        return bruto.strip() if isinstance(bruto, str) else ""

    def _projeto(self) -> str:
        bruto = self._tarefas.get(ChaveTarefas.PROJETO)
        numerico = isinstance(bruto, int) and not isinstance(bruto, bool)
        projeto = str(bruto) if numerico else self._tarefa(ChaveTarefas.PROJETO)
        if not projeto:
            lida = " e ".join(self._arquivos) or "nenhuma"
            raise ErroDeEntrada(
                f"faltando [{Tabela.TAREFAS}] {ChaveTarefas.PROJETO} "
                f"(config lida: {lida})"
            )
        return projeto

    def _token(self) -> str:
        env = os.environ if self._env is None else self._env
        return env.get(VarGitlab.TOKEN, "").strip()

    @property
    def referencia(self) -> Referencia:
        return Referencia("#{id}", _ALFABETO_NUMERICO)

    def _base(self) -> str:
        base = (self._tarefa(ChaveTarefas.URL) or _URL_PADRAO).rstrip("/")
        # Sem esquema, o httpx levanta UnsupportedProtocol (HTTPError): sairia como GitLab fora.
        if not base.lower().startswith(_PREFIXO_URL):
            raise ErroDeEntrada(
                f"[{Tabela.TAREFAS}] {ChaveTarefas.URL} deve começar com "
                f"{_PREFIXO_URL}: {base!r}"
            )
        return base

    def _get(
        self, url: str, params: Mapping[str, str] | None, projeto: str | None
    ) -> httpx.Response:
        """GET com rede e status traduzidos para erros do motor."""
        token = self._token()
        headers: dict[str, str] = {_Cabecalho.TOKEN: token} if token else {}
        try:
            if self._client is not None:
                resp = self._client.get(url, params=params, headers=headers)
            else:
                with httpx.Client() as client:
                    resp = client.get(url, params=params, headers=headers)
        except httpx.InvalidURL as e:
            raise ErroDeEntrada(f"URL do GitLab inválida: {url!r}: {e}") from e
        except httpx.HTTPError as e:
            raise BackendIndisponivel(f"chamando o GitLab: {e}") from e
        _traduzir_status(resp, token, projeto)
        return resp

    def _listar(
        self, recurso: _Recurso, params: Mapping[str, str], projeto: str
    ) -> list[object]:
        """Todos os itens de uma lista paginada pelo cabeçalho `Link`."""
        base = self._base()
        url: str | httpx.URL = (
            f"{base}{_CAMINHO_API}/projects/{quote(projeto, safe='')}/{recurso}"
        )
        pedido: Mapping[str, str] | None = {
            **params,
            _Param.POR_PAGINA: str(_POR_PAGINA),
        }
        pedidas: set[httpx.URL] = set()
        itens: list[object] = []
        while True:
            resp = self._get(str(url), pedido, projeto)
            pedidas.add(resp.request.url)
            try:
                corpo = resp.json()
            except ValueError as e:
                raise RespostaInvalida(f"decodificando resposta do GitLab: {e}") from e
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

    def verificar_credenciais(self) -> str | None:
        if not self._token():
            return f"sem {VarGitlab.TOKEN}: acesso anônimo, nada a verificar"
        self._get(self._base() + _CAMINHO_API + _CAMINHO_EU, None, None)
        return None

    def fetch(self, versao: str, /) -> list[str]:
        projeto = self._projeto()
        # Sem token o /milestones responde 401; aí a versão inexistente sai como lista vazia.
        if self._token() and not self._listar(
            _Recurso.MILESTONES,
            {_Param.TITLE: versao, _Param.ANCESTRAIS: _VERDADE},
            projeto,
        ):
            raise ErroDeEntrada(
                f"milestone {versao!r} não existe no projeto {projeto!r}"
            )
        issues = self._listar(
            _Recurso.ISSUES, {_Param.MILESTONE: versao, _Param.ESCOPO: _TODOS}, projeto
        )
        return list(dict.fromkeys(str(_iid(i)) for i in issues))
