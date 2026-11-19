"""FonteGitlab: plugin `TaskSource` do GitLab Issues (`[tarefas] fonte = "gitlab"`)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum

import httpx

from monitor_versoes_gitlab.api import (
    CAMINHO_EU,
    CAMPO_TOKEN,
    URL_PADRAO,
    ApiGitlab,
    VarGitlab,
    caminho_projeto,
)
from motor.config import TABELA_AMBIENTE, Tabela
from motor.config_edicao import Campo, Escopo, TipoCampo
from motor.domain.referencia import Referencia
from motor.errors import ErroDeEntrada, RespostaInvalida

__all__ = ["ChaveTarefas", "FonteGitlab", "VarGitlab"]

_ALFABETO_NUMERICO = "0-9"
_TODOS = "all"
_VERDADE = "true"


class _Param(StrEnum):
    """Parâmetros de query da API REST."""

    TITLE = "title"
    ANCESTRAIS = "include_ancestors"
    MILESTONE = "milestone"
    ESCOPO = "scope"


class _Recurso(StrEnum):
    MILESTONES = "milestones"
    ISSUES = "issues"


class _Campo(StrEnum):
    """Campos do JSON de issues."""

    IID = "iid"


class ChaveTarefas(StrEnum):
    """Chaves do `[tarefas]` que este plugin lê."""

    PROJETO = "projeto"
    URL = "url"


def _iid(item: object) -> int:
    iid = item.get(_Campo.IID) if isinstance(item, dict) else None
    if not isinstance(iid, int) or isinstance(iid, bool):
        raise RespostaInvalida(f"item do GitLab sem iid inteiro: {item!r}")
    return iid


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
            padrao=URL_PADRAO,
            exemplo="https://gitlab.empresa.com",
        ),
        CAMPO_TOKEN,
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
        self._api = ApiGitlab(
            url=tarefas.get(ChaveTarefas.URL),
            tabela=Tabela.TAREFAS,
            token=self._token,
            client=client,
            reaproveitar=False,
            dica_projeto=self._dica_projeto,
        )

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

    def _dica_projeto(self, _projeto: str) -> str:
        return f"confira [{Tabela.TAREFAS}] {ChaveTarefas.PROJETO}" + (
            "" if self._token() else f" ou defina [{TABELA_AMBIENTE}] {VarGitlab.TOKEN}"
        )

    def _listar(
        self, recurso: _Recurso, params: Mapping[str, str], projeto: str
    ) -> list[object]:
        itens = self._api.listar(
            caminho_projeto(projeto) + f"/{recurso}", params, projeto
        )
        assert itens is not None  # sem `ausente`, 404 levanta
        return itens

    @property
    def referencia(self) -> Referencia:
        return Referencia("#{id}", _ALFABETO_NUMERICO)

    def verificar_credenciais(self) -> str | None:
        if not self._token():
            return f"sem {VarGitlab.TOKEN}: acesso anônimo, nada a verificar"
        self._api.obter(self._api.url(CAMINHO_EU), None, None)
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
