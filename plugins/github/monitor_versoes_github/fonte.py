"""FonteGithub: plugin `TaskSource` do GitHub Issues (`[tarefas] fonte = "github"`)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum

import httpx

from monitor_versoes_github.api import (
    API_PADRAO,
    CAMINHO_EU,
    CAMPO_TOKEN,
    CHAVE_API_URL,
    ApiGithub,
    VarGithub,
)
from motor.config import TABELA_AMBIENTE, Tabela
from motor.config_edicao import Campo, Escopo, TipoCampo
from motor.domain.referencia import Referencia
from motor.errors import ErroDeEntrada, RespostaInvalida

__all__ = ["ChaveTarefas", "FonteGithub", "VarGithub"]

_ALFABETO_NUMERICO = "0-9"
_TODOS = "all"


class _Param(StrEnum):
    """Parâmetros de query da API REST."""

    STATE = "state"
    MILESTONE = "milestone"


class _Campo(StrEnum):
    """Campos do JSON de milestones e issues."""

    NUMBER = "number"
    TITLE = "title"
    PULL_REQUEST = "pull_request"


class ChaveTarefas(StrEnum):
    """Chaves do `[tarefas]` que este plugin lê."""

    REPO = "repo"
    API_URL = CHAVE_API_URL


def _numero(item: object) -> int:
    numero = item.get(_Campo.NUMBER) if isinstance(item, dict) else None
    if not isinstance(numero, int) or isinstance(numero, bool):
        raise RespostaInvalida(f"item do GitHub sem número inteiro: {item!r}")
    return numero


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
            padrao=API_PADRAO,
            exemplo="https://github.empresa.com/api/v3",
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
        self._api = ApiGithub(
            api_url=tarefas.get(ChaveTarefas.API_URL),
            tabela=Tabela.TAREFAS,
            token=self._token,
            client=client,
            reaproveitar=False,
            dica_repo=self._dica_repo,
        )

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

    def _dica_repo(self, repo: str) -> str:
        return f"confira [{Tabela.TAREFAS}] {ChaveTarefas.REPO}" + (
            "" if self._token() else f" ou defina [{TABELA_AMBIENTE}] {VarGithub.TOKEN}"
        )

    def verificar_credenciais(self) -> str | None:
        if not self._token():
            return f"sem {VarGithub.TOKEN}: acesso anônimo, nada a verificar"
        self._api.obter(self._api.base() + CAMINHO_EU, None, None)
        return None

    def fetch(self, versao: str, /) -> list[str]:
        repo = self._repo()
        milestones = self._api.listar(
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
        issues = self._api.listar(
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
