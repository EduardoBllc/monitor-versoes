"""Diagnóstico da instalação: checa cada peça e diz qual falhou e como corrigir.

Tudo chega por parâmetro (ambiente, abertura de sessão, cliente HTTP, `head` do
alembic, config central), para ser testável sem banco real nem rede. Não tem efeito colateral:
não escreve no banco, não roda git, não exige repo cadastrado.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from motor.adapters.commitsource.bitbucket import verificar_credenciais
from motor.adapters.estado.postgres import PostgresEstado
from motor.config import SECAO_REPOS, ConfigProjeto
from motor.errors import MotorError, formatar_com_notas
from motor.montagem import instanciar_fonte_tarefas


class Peca(enum.StrEnum):
    VARIAVEIS = "Variáveis"
    SQLITE = "SQLite"
    POSTGRES = "Postgres"
    MIGRACAO = "Migração"
    REPOS = "Repos"
    TAREFAS = "Tarefas"
    BITBUCKET = "Bitbucket"


class Estado(enum.Enum):
    OK = "OK"
    FALHA = "FALHA"
    NAO_VERIFICADA = "não verificada"
    NAO_CONFIGURADO = "não configurado"
    AVISO = "aviso"


@dataclass(frozen=True)
class Resultado:
    peca: Peca
    estado: Estado
    detalhe: str = ""
    correcao: str = ""


def falhou(resultados: list[Resultado]) -> bool:
    """Só `FALHA` conta; `aviso`, `não verificada` e `não configurado` não."""
    return any(r.estado is Estado.FALHA for r in resultados)


_VARIAVEIS_BANCO = (
    "DATABASE_HOST",
    "DATABASE_PORT",
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
)


def _falha(peca: Peca, erro: MotorError, correcao: str) -> Resultado:
    return Resultado(peca, Estado.FALHA, formatar_com_notas(erro), correcao)


def _variaveis_ausentes(env: Mapping[str, str], nomes: tuple[str, ...]) -> list[str]:
    return [n for n in nomes if not env.get(n, "").strip()]


def _backend(env: Mapping[str, str]) -> str:
    return env.get("DATABASE_BACKEND", "").strip().lower() or "sqlite"


def _problemas_do_banco(env: Mapping[str, str]) -> list[str]:
    backend = _backend(env)
    if backend == "sqlite":
        return []
    if backend != "postgres":
        return [f"DATABASE_BACKEND (aceitos: sqlite, postgres; veio {backend!r})"]
    problemas = _variaveis_ausentes(env, _VARIAVEIS_BANCO)
    porta = env.get("DATABASE_PORT", "")
    if porta and not porta.isdigit():
        problemas.append("DATABASE_PORT (esperado número)")
    return problemas


# Sete parâmetros, seis nomeados: cada um é uma peça injetada para o teste
# rodar sem banco, rede nem arquivo de config reais.
def diagnosticar(  # noqa: PLR0913
    env: Mapping[str, str],
    *,
    abrir_sessao: Callable[..., AbstractContextManager[Session]],
    head: str,
    ambiente: str,
    config_central: Callable[[], ConfigProjeto],
    repos: Callable[[], Mapping[str, str | None]],
    cliente: httpx.Client | None = None,
) -> list[Resultado]:
    arquivo = ".env.development" if ambiente == "development" else ".env"
    migrar = "make migrate-dev" if ambiente == "development" else "make migrate"

    problemas = _problemas_do_banco(env)

    resultados = [
        Resultado(
            Peca.VARIAVEIS,
            Estado.FALHA,
            "ausentes ou inválidas: " + ", ".join(problemas),
            f"preencher no {arquivo}",
        )
        if problemas
        else Resultado(Peca.VARIAVEIS, Estado.OK, "todas preenchidas")
    ]
    resultados += _banco(
        abrir_sessao, problemas, head, migrar, _backend(env) == "sqlite"
    )
    banco_ok = [
        r.estado
        for r in resultados
        if r.peca in (Peca.POSTGRES, Peca.SQLITE, Peca.MIGRACAO)
    ] == [
        Estado.OK,
        Estado.OK,
    ]
    resultados += _repos(abrir_sessao, repos, banco_ok)
    resultados.append(_tarefas(config_central))
    resultados.append(_bitbucket(env, cliente))
    return resultados


def _banco_fora(peca: Peca, erro: MotorError, dica: str) -> list[Resultado]:
    """Banco fora implica Migração não verificada."""
    return [
        _falha(peca, erro, dica),
        Resultado(Peca.MIGRACAO, Estado.NAO_VERIFICADA, f"{peca} indisponível"),
    ]


def _banco(
    abrir_sessao: Callable[..., AbstractContextManager[Session]],
    problemas_banco: list[str],
    head: str,
    migrar: str,
    sqlite: bool = False,
) -> list[Resultado]:
    peca = Peca.SQLITE if sqlite else Peca.POSTGRES
    if problemas_banco:
        motivo = "variáveis do banco inválidas"
        return [
            Resultado(peca, Estado.NAO_VERIFICADA, motivo),
            Resultado(Peca.MIGRACAO, Estado.NAO_VERIFICADA, motivo),
        ]
    if sqlite:
        dica_banco = "conferir DATABASE_SQLITE_PATH e as permissões do arquivo"
        migrar = (
            "rodar qualquer comando do motor (aplica as migrations no primeiro uso)"
        )
    else:
        dica_banco = "docker compose up -d e conferir DATABASE_*"
    try:
        # garantir=False: o diagnóstico só olha, não cria arquivo nem esquema.
        with abrir_sessao(garantir=False) as sessao:
            estado = PostgresEstado(sessao=sessao)
            try:
                estado.verificar_conexao()
            except MotorError as e:
                return _banco_fora(peca, e, dica_banco)
            postgres = Resultado(peca, Estado.OK, "conexão funciona")
            try:
                revisao = estado.revisao_migracao()
            except MotorError as e:
                return [postgres, _falha(Peca.MIGRACAO, e, dica_banco)]
    except MotorError as e:
        return _banco_fora(peca, e, dica_banco)
    if revisao is None:
        migracao = Resultado(
            Peca.MIGRACAO, Estado.FALHA, "banco sem migração aplicada", migrar
        )
    elif revisao != head:
        migracao = Resultado(
            Peca.MIGRACAO,
            Estado.FALHA,
            f"banco na revisão {revisao}, esperado {head}",
            migrar,
        )
    else:
        migracao = Resultado(Peca.MIGRACAO, Estado.OK, f"revisão {head}")
    return [postgres, migracao]


def _estado_sem_secao(
    abrir_sessao: Callable[..., AbstractContextManager[Session]], nomes: set[str]
) -> list[Resultado]:
    try:
        with abrir_sessao(garantir=False) as sessao:
            no_banco = [r.nome for r in PostgresEstado(sessao=sessao).listar_repos()]
    except MotorError as e:
        return [Resultado(Peca.REPOS, Estado.NAO_VERIFICADA, formatar_com_notas(e))]
    return [
        Resultado(
            Peca.REPOS,
            Estado.AVISO,
            f"estado de {nome!r} no banco sem seção [{SECAO_REPOS}.{nome}] "
            "no config.toml",
            "remover o estado do banco ou criar a seção",
        )
        for nome in no_banco
        if nome not in nomes
    ]


def _repos(
    abrir_sessao: Callable[..., AbstractContextManager[Session]],
    repos: Callable[[], Mapping[str, str | None]],
    banco_ok: bool,
) -> list[Resultado]:
    """Seções `[repos.<nome>]` do config.toml central contra disco e banco."""
    correcao = f"conferir [{SECAO_REPOS}.<nome>] no config.toml central"
    try:
        configurados = repos()
    except MotorError as e:
        return [_falha(Peca.REPOS, e, correcao)]
    linhas = []
    for nome, caminho in configurados.items():
        if caminho is None:
            detalhe = f"[{SECAO_REPOS}.{nome}] sem caminho"
        elif not Path(caminho).is_dir():
            detalhe = f"[{SECAO_REPOS}.{nome}] caminho não é diretório: {caminho}"
        else:
            continue
        linhas.append(Resultado(Peca.REPOS, Estado.FALHA, detalhe, correcao))
    if banco_ok:
        linhas += _estado_sem_secao(abrir_sessao, set(configurados))
    else:
        linhas.append(
            Resultado(
                Peca.REPOS,
                Estado.NAO_VERIFICADA,
                "banco indisponível: estado não conferido",
            )
        )
    if not linhas:
        return [
            Resultado(
                Peca.REPOS, Estado.OK, f"{len(configurados)} repo(s) configurado(s)"
            )
        ]
    return linhas


def _tarefas(config_central: Callable[[], ConfigProjeto]) -> Resultado:
    """A fonte de tarefas do `config.toml` central: o diagnóstico não tem repo.

    Credencial só é conferida se o plugin oferece `verificar_credenciais`.
    """
    plugins = "conferir [tarefas] fonte e os plugins instalados"
    try:
        config = config_central()
    except MotorError as e:
        return _falha(Peca.TAREFAS, e, plugins)
    if config.fonte_tarefas is None:
        return Resultado(
            Peca.TAREFAS,
            Estado.NAO_CONFIGURADO,
            "sem [tarefas] fonte no config.toml central",
            "definir [tarefas] fonte no config.toml central",
        )
    try:
        fonte = instanciar_fonte_tarefas(config)
    except MotorError as e:
        return _falha(Peca.TAREFAS, e, plugins)
    verificar = getattr(fonte, "verificar_credenciais", None)
    if not callable(verificar):
        return Resultado(
            Peca.TAREFAS, Estado.NAO_VERIFICADA, "a fonte não oferece verificação"
        )
    try:
        verificar()
    except MotorError as e:
        return _falha(Peca.TAREFAS, e, "conferir as credenciais da fonte no .env")
    return Resultado(Peca.TAREFAS, Estado.OK, "credenciais aceitas")


def _bitbucket(env: Mapping[str, str], cliente: httpx.Client | None) -> Resultado:
    token = env.get("BITBUCKET_TOKEN", "")
    if not token:
        return Resultado(Peca.BITBUCKET, Estado.NAO_CONFIGURADO, "sem BITBUCKET_TOKEN")
    try:
        verificar_credenciais(token, env.get("BITBUCKET_EMAIL", ""), client=cliente)
    except MotorError as e:
        return _falha(
            Peca.BITBUCKET,
            e,
            "conferir BITBUCKET_TOKEN/BITBUCKET_EMAIL "
            "(o token precisa de escopo de leitura de conta)",
        )
    return Resultado(Peca.BITBUCKET, Estado.OK, "credencial aceita")


def formatar(resultado: Resultado) -> str:
    linha = f"{resultado.estado.value}  {resultado.peca}"
    if resultado.detalhe:
        linha += f": {resultado.detalhe}"
    if resultado.correcao:
        linha += f" -> {resultado.correcao}"
    return linha


__all__ = [
    "Estado",
    "Peca",
    "Resultado",
    "diagnosticar",
    "falhou",
    "formatar",
]
