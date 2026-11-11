"""Catálogo de campos da config central e leitura dela para edição pela UI."""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from motor import plugins
from motor.config import (
    _BACKENDS,
    CHAVE_CAMINHO,
    SECAO_REPOS,
    TABELA_AMBIENTE,
    caminho_config_global,
)
from motor.errors import ErroDeEntrada, MotorError
from motor.montagem import GRUPO_ATRIBUICOES, GRUPO_ESQUEMAS, GRUPO_TAREFAS

ORIGEM_MOTOR = "motor"
_GRUPOS = (GRUPO_TAREFAS, GRUPO_ESQUEMAS, GRUPO_ATRIBUICOES)


class Escopo(StrEnum):
    GERAL = "geral"
    REPO = "repo"
    AMBIENTE = "ambiente"


class TipoCampo(StrEnum):
    TEXTO = "texto"
    INTEIRO = "inteiro"
    ESCOLHA = "escolha"


@dataclass(frozen=True)
class Campo:
    escopo: Escopo
    tabela: str | None
    chave: str
    tipo: TipoCampo
    rotulo: str
    segredo: bool = False
    opcoes: tuple[str, ...] = ()
    origem: str = ORIGEM_MOTOR


@dataclass(frozen=True)
class ValorLido:
    repo: str | None
    tabela: str | None
    chave: str
    valor: str | int | bool | None
    definido: bool
    editavel: bool


@dataclass(frozen=True)
class ConfigEditavel:
    campos: list[Campo]
    valores: list[ValorLido]
    repos: list[str]
    versao: str


def _c(
    escopo: Escopo,
    tabela: str | None,
    chave: str,
    tipo: TipoCampo,
    rotulo: str,
    **extra: object,
) -> Campo:
    return Campo(escopo, tabela, chave, tipo, rotulo, **extra)  # type: ignore[arg-type]


_G, _R, _A = Escopo.GERAL, Escopo.REPO, Escopo.AMBIENTE
_TX, _IN, _ES = TipoCampo.TEXTO, TipoCampo.INTEIRO, TipoCampo.ESCOLHA

#: Campo -> grupo cujos entry points e valores `modulo:Classe` em uso são as opções.
_GRUPO_DO_CAMPO = {
    ("versao", "esquema"): GRUPO_ESQUEMAS,
    ("versao", "atribuicao"): GRUPO_ATRIBUICOES,
    ("tarefas", "fonte"): GRUPO_TAREFAS,
}

_CAMPOS_MOTOR = (
    _c(_G, "versao", "esquema", _ES, "Esquema de versão"),
    _c(_G, "versao", "atribuicao", _ES, "Atribuição"),
    _c(_G, "liberacao", "tag", _TX, "Tag de liberação"),
    _c(_G, "branches", "versao", _TX, "Branch de versão"),
    _c(_G, "branches", "principal", _TX, "Branch principal"),
    _c(_G, "referencia", "padrao", _TX, "Padrão de referência"),
    _c(_G, "tarefas", "fonte", _ES, "Fonte de tarefas"),
    _c(_R, None, CHAVE_CAMINHO, _TX, "Caminho"),
    _c(_R, "versao", "piso", _TX, "Piso de versão"),
    _c(
        _A,
        TABELA_AMBIENTE,
        "DATABASE_BACKEND",
        _ES,
        "Backend do banco",
        opcoes=_BACKENDS,
    ),
    *(
        _c(_A, TABELA_AMBIENTE, k, _TX, r)
        for k, r in (
            ("DATABASE_HOST", "Host do banco"),
            ("DATABASE_NAME", "Nome do banco"),
            ("DATABASE_USER", "Usuário do banco"),
            ("DATABASE_SQLITE_PATH", "Arquivo do SQLite"),
            ("BITBUCKET_EMAIL", "E-mail do Bitbucket"),
        )
    ),
    _c(_A, TABELA_AMBIENTE, "DATABASE_PORT", _IN, "Porta do banco"),
    _c(_A, TABELA_AMBIENTE, "WORKTREES_MANTIDAS", _IN, "Worktrees mantidas"),
    _c(_A, TABELA_AMBIENTE, "DATABASE_PASSWORD", _TX, "Senha do banco", segredo=True),
    _c(_A, TABELA_AMBIENTE, "BITBUCKET_TOKEN", _TX, "Token do Bitbucket", segredo=True),
)


def _mapa(valor: object) -> Mapping[str, object]:
    return valor if isinstance(valor, dict) else {}


def _secoes(dados: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    return {n: _mapa(s) for n, s in _mapa(dados.get(SECAO_REPOS)).items()}


def _em_uso(dados: Mapping[str, object], tabela: str, chave: str) -> set[str]:
    """Valores `modulo:Classe` da chave, no topo e em cada seção de repo."""
    camadas = [dados, *_secoes(dados).values()]
    valores = {_mapa(c.get(tabela)).get(chave) for c in camadas}
    return {v for v in valores if isinstance(v, str) and ":" in v}


def _campos_do_plugin(grupo: str, nome: str) -> tuple[Campo, ...]:
    try:
        declarados = getattr(plugins.carregar_plugin(grupo, nome), "campos_config", ())
    except MotorError:
        return ()
    if not isinstance(declarados, tuple) or not all(
        isinstance(c, Campo) for c in declarados
    ):
        return ()
    return tuple(replace(c, origem=nome) for c in declarados)


def catalogo_campos(dados: Mapping[str, object]) -> list[Campo]:
    """Campos do motor e os que os plugins instalados ou em uso declaram."""
    instalados = {g: plugins.nomes_instalados(g) for g in _GRUPOS}
    em_uso = {g: _em_uso(dados, *tc) for tc, g in _GRUPO_DO_CAMPO.items()}
    campos: list[Campo] = []
    for base in _CAMPOS_MOTOR:
        grupo = _GRUPO_DO_CAMPO.get((base.tabela or "", base.chave))
        opcoes = tuple(instalados[grupo] + sorted(em_uso[grupo])) if grupo else None
        campos.append(base if opcoes is None else replace(base, opcoes=opcoes))
    vistos = {(c.escopo, c.tabela, c.chave) for c in campos}
    for grupo in _GRUPOS:
        for nome in [*instalados[grupo], *sorted(em_uso[grupo])]:
            for c in _campos_do_plugin(grupo, nome):
                if (c.escopo, c.tabela, c.chave) not in vistos:
                    vistos.add((c.escopo, c.tabela, c.chave))
                    campos.append(c)
    return campos


def _valor(
    repo: str | None,
    tabela: str | None,
    chave: str,
    bruto: object,
    segredos: set[tuple[str | None, str]],
) -> ValorLido:
    if (tabela, chave) in segredos:
        return ValorLido(repo, tabela, chave, None, True, True)
    if isinstance(bruto, str | int):  # bool é int
        return ValorLido(repo, tabela, chave, bruto, True, True)
    return ValorLido(repo, tabela, chave, None, True, False)


def _valores_da_secao(
    repo: str | None, secao: Mapping[str, object], segredos: set[tuple[str | None, str]]
) -> list[ValorLido]:
    lidos: list[ValorLido] = []
    for chave, bruto in secao.items():
        if isinstance(bruto, dict):
            lidos += [_valor(repo, chave, k, v, segredos) for k, v in bruto.items()]
        elif repo is not None:
            lidos.append(_valor(repo, None, chave, bruto, segredos))
    return lidos


def ler_para_edicao() -> ConfigEditavel:
    """Lê a config central com segredos mascarados e o token de versão."""
    arquivo = caminho_config_global()
    try:
        with open(arquivo, "rb") as f:
            bruto = f.read()
    except FileNotFoundError:
        bruto = b""
    except OSError as e:
        raise ErroDeEntrada(f"{arquivo}: não foi possível ler ({e})") from e
    try:
        dados = tomllib.loads(bruto.decode())
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise ErroDeEntrada(f"{arquivo}: TOML inválido ({e})") from e
    campos = catalogo_campos(dados)
    segredos = {(c.tabela, c.chave) for c in campos if c.segredo}
    topo = {k: v for k, v in dados.items() if k != SECAO_REPOS}
    valores = _valores_da_secao(None, topo, segredos)
    secoes = _secoes(dados)
    for nome in sorted(secoes):
        valores += _valores_da_secao(nome, secoes[nome], segredos)
    return ConfigEditavel(
        campos, valores, sorted(secoes), hashlib.sha256(bruto).hexdigest()
    )
