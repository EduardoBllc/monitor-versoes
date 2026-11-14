"""FonteJira: plugin `TaskSource` do Jira Cloud (`[tarefas] fonte = "jira"`)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum

import httpx

from motor.config import TABELA_AMBIENTE
from motor.config_edicao import Campo, Escopo, TipoCampo
from motor.domain.referencia import Referencia
from motor.errors import ErroDeEntrada

TABELA_TAREFAS = "tarefas"
_ALFABETO_NUMERICO = "0-9"


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
            TABELA_TAREFAS,
            ChaveTarefas.URL,
            TipoCampo.TEXTO,
            "URL do Jira",
            descricao="Endereço do site Jira Cloud",
            exemplo="https://empresa.atlassian.net",
        ),
        Campo(
            Escopo.GERAL,
            TABELA_TAREFAS,
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
            onde = "[tarefas]" if isinstance(chave, ChaveTarefas) else "[ambiente]"
            raise ErroDeEntrada(
                f'[tarefas] fonte = "jira" sem {chave}: defina-a em {onde} do '
                f"config.toml (config lida: {lida})"
            )
        return valor

    @property
    def referencia(self) -> Referencia:
        projeto = self._exigir(ChaveTarefas.PROJETO)
        return Referencia(f"{projeto}-{{id}}", _ALFABETO_NUMERICO)

    def fetch(self, versao: str, /) -> list[str]:
        raise NotImplementedError
