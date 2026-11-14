"""FonteJira: plugin `TaskSource` do Jira Cloud (`[tarefas] fonte = "jira"`)."""

from __future__ import annotations

import base64
import os
import re
from collections.abc import Mapping
from enum import StrEnum

import httpx

from motor.config import TABELA_AMBIENTE, Tabela
from motor.config_edicao import Campo, Escopo, TipoCampo
from motor.domain.referencia import Referencia
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida

_ALFABETO_NUMERICO = "0-9"
_CAMINHO_BUSCA = "/rest/api/3/search/jql"
_CAMINHO_EU = "/rest/api/3/myself"
_POR_PAGINA = 100
# Jira Cloud só atende HTTPS.
_PREFIXO_URL = "https://"


class _Param(StrEnum):
    """Parâmetros de query da API de busca."""

    JQL = "jql"
    FIELDS = "fields"
    MAX_RESULTS = "maxResults"
    PAGINA = "nextPageToken"


class _Campo(StrEnum):
    """Campos do JSON de resposta da busca."""

    ISSUES = "issues"
    KEY = "key"
    ULTIMA = "isLast"
    PROXIMA = "nextPageToken"


def _literal(valor: str) -> str:
    """Valor como literal entre aspas da JQL."""
    return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'


class ChaveTarefas(StrEnum):
    """Chaves do `[tarefas]` que este plugin lê."""

    URL = "url"
    PROJETO = "projeto"


class VarJira(StrEnum):
    """Variáveis do `[ambiente]` que este plugin lê."""

    EMAIL = "JIRA_EMAIL"
    TOKEN = "JIRA_TOKEN"


class FonteJira:
    """`TaskSource` do Jira Cloud."""

    campos_config = (
        Campo(
            Escopo.GERAL,
            Tabela.TAREFAS,
            ChaveTarefas.URL,
            TipoCampo.TEXTO,
            "URL do Jira",
            descricao="Endereço do site Jira Cloud",
            exemplo="https://empresa.atlassian.net",
        ),
        Campo(
            Escopo.GERAL,
            Tabela.TAREFAS,
            ChaveTarefas.PROJETO,
            TipoCampo.TEXTO,
            "Projeto do Jira",
            descricao="Chave do projeto, prefixo das tarefas",
            exemplo="PROJ",
        ),
        Campo(
            Escopo.AMBIENTE,
            TABELA_AMBIENTE,
            VarJira.EMAIL,
            TipoCampo.TEXTO,
            "E-mail do Jira",
            descricao="E-mail da conta do Jira",
            exemplo="voce@empresa.com",
        ),
        Campo(
            Escopo.AMBIENTE,
            TABELA_AMBIENTE,
            VarJira.TOKEN,
            TipoCampo.TEXTO,
            "Token do Jira",
            segredo=True,
            descricao="API token da conta do Jira",
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
        return "FonteJira()"

    def _exigir(self, chave: ChaveTarefas | VarJira) -> str:
        """Valor da chave em `[tarefas]` ou no ambiente; vazio conta como ausente."""
        if isinstance(chave, ChaveTarefas):
            bruto = self._tarefas.get(chave)
        else:
            env = os.environ if self._env is None else self._env
            bruto = env.get(chave)
        valor = bruto.strip() if isinstance(bruto, str) else ""
        if not valor:
            lida = " e ".join(self._arquivos) or "nenhuma"
            tabela = (
                Tabela.TAREFAS if isinstance(chave, ChaveTarefas) else TABELA_AMBIENTE
            )
            raise ErroDeEntrada(f"faltando [{tabela}] {chave} (config lida: {lida})")
        return valor

    @property
    def referencia(self) -> Referencia:
        projeto = self._exigir(ChaveTarefas.PROJETO)
        return Referencia(f"{projeto}-{{id}}", _ALFABETO_NUMERICO)

    def _get(
        self, caminho: str, params: Mapping[str, str], contexto: str
    ) -> httpx.Response:
        """GET autenticado, com rede, status e JSON traduzidos para erros do motor."""
        base = self._exigir(ChaveTarefas.URL).rstrip("/")
        # Sem esquema, o httpx levanta UnsupportedProtocol (HTTPError): sairia como Jira fora.
        if not base.lower().startswith(_PREFIXO_URL):
            raise ErroDeEntrada(
                f"[{Tabela.TAREFAS}] {ChaveTarefas.URL} deve começar com "
                f"{_PREFIXO_URL}: {base!r}"
            )
        credenciais = f"{self._exigir(VarJira.EMAIL)}:{self._exigir(VarJira.TOKEN)}"
        auth = "Basic " + base64.b64encode(credenciais.encode()).decode()
        try:
            if self._client is not None:
                resp = self._client.get(
                    base + caminho, params=params, headers={"Authorization": auth}
                )
            else:
                with httpx.Client() as client:
                    resp = client.get(
                        base + caminho, params=params, headers={"Authorization": auth}
                    )
        except httpx.InvalidURL as e:
            raise ErroDeEntrada(f"URL do Jira inválida: {base!r}: {e}") from e
        except httpx.HTTPError as e:
            raise BackendIndisponivel(f"chamando o Jira: {e}") from e
        status = resp.status_code
        if status in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            raise ErroDeEntrada(
                f"Jira recusou a credencial ({status}): "
                f"confira {VarJira.EMAIL} e {VarJira.TOKEN}"
            )
        if status == httpx.codes.BAD_REQUEST:
            raise ErroDeEntrada(f"Jira rejeitou a consulta {contexto}: {resp.text}")
        if status != httpx.codes.OK:
            raise BackendIndisponivel(f"Jira respondeu {status}")
        return resp

    def verificar_credenciais(self) -> None:
        self._get(_CAMINHO_EU, {}, "de credencial")

    def fetch(self, versao: str, /) -> list[str]:
        projeto = self._exigir(ChaveTarefas.PROJETO)
        jql = f"project = {_literal(projeto)} AND fixVersion = {_literal(versao)}"
        contexto = f"(versão {versao!r}, projeto {projeto!r})"
        chave = re.compile(rf"{re.escape(projeto)}-([0-9]+)", re.IGNORECASE)
        params: dict[str, str] = {
            _Param.JQL: jql,
            _Param.FIELDS: _Campo.KEY,
            _Param.MAX_RESULTS: str(_POR_PAGINA),
        }
        ids: list[str] = []
        while True:
            resp = self._get(_CAMINHO_BUSCA, params, contexto)
            try:
                corpo = resp.json()
            except ValueError as e:
                raise RespostaInvalida(f"decodificando resposta do Jira: {e}") from e
            if not isinstance(corpo, dict) or not isinstance(
                corpo.get(_Campo.ISSUES), list
            ):
                raise RespostaInvalida(
                    f"resposta do Jira em formato inesperado: {corpo!r}"
                )
            for issue in corpo[_Campo.ISSUES]:
                bruta = issue.get(_Campo.KEY) if isinstance(issue, dict) else None
                m = chave.fullmatch(bruta) if isinstance(bruta, str) else None
                if m is None:
                    raise RespostaInvalida(f"chave de tarefa inesperada: {bruta!r}")
                ids.append(m.group(1))
            if corpo.get(_Campo.ULTIMA):
                return list(dict.fromkeys(ids))
            proxima = corpo.get(_Campo.PROXIMA)
            if not isinstance(proxima, str) or not proxima:
                raise RespostaInvalida("Jira indicou mais páginas sem nextPageToken")
            if proxima == params.get(_Param.PAGINA):
                raise RespostaInvalida("Jira repetiu o nextPageToken já enviado")
            params = {**params, _Param.PAGINA: proxima}
