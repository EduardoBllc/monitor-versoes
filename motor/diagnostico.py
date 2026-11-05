"""Diagnóstico da instalação: checa cada peça e diz qual falhou e como corrigir.

Tudo chega por parâmetro (ambiente, abertura de sessão, cliente HTTP, `head` do
alembic, config central), para ser testável sem banco real nem rede. Não tem efeito colateral:
não escreve no banco, não roda git, não exige repo cadastrado.
"""

from __future__ import annotations

import enum
import os
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from motor.adapters.commitsource.bitbucket import verificar_credenciais
from motor.adapters.estado.postgres import PostgresEstado
from motor.config import ConfigProjeto
from motor.errors import MotorError, formatar_com_notas
from motor.montagem import instanciar_fonte_tarefas


class Estado(enum.Enum):
    OK = "OK"
    FALHA = "FALHA"
    NAO_VERIFICADA = "não verificada"
    NAO_CONFIGURADO = "não configurado"


@dataclass(frozen=True)
class Resultado:
    peca: str
    estado: Estado
    detalhe: str = ""
    correcao: str = ""


def falhou(resultados: list[Resultado]) -> bool:
    """Só `FALHA` conta; `não verificada` e `não configurado` não."""
    return any(r.estado is Estado.FALHA for r in resultados)


_VARIAVEIS_BANCO = (
    "DATABASE_HOST",
    "DATABASE_PORT",
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
)


def _falha(peca: str, erro: MotorError, correcao: str) -> Resultado:
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


# Seis parâmetros, cinco nomeados: cada um é uma peça injetada para o teste
# rodar sem banco, rede nem arquivo de config reais.
def diagnosticar(  # noqa: PLR0913
    env: Mapping[str, str],
    *,
    abrir_sessao: Callable[..., AbstractContextManager[Session]],
    head: str,
    ambiente: str,
    config_central: Callable[[], ConfigProjeto],
    cliente: httpx.Client | None = None,
) -> list[Resultado]:
    arquivo = ".env.development" if ambiente == "development" else ".env"
    migrar = "make migrate-dev" if ambiente == "development" else "make migrate"

    problemas = _problemas_do_banco(env)

    resultados = [
        Resultado(
            "Variáveis",
            Estado.FALHA,
            "ausentes ou inválidas: " + ", ".join(problemas),
            f"preencher no {arquivo}",
        )
        if problemas
        else Resultado("Variáveis", Estado.OK, "todas preenchidas")
    ]
    resultados += _banco(
        abrir_sessao, problemas, head, migrar, _backend(env) == "sqlite"
    )
    resultados.append(_projects_dir(env))
    resultados.append(_tarefas(config_central))
    resultados.append(_bitbucket(env, cliente))
    return resultados


def _banco_fora(peca: str, erro: MotorError, dica: str) -> list[Resultado]:
    """Banco fora implica Migração não verificada."""
    return [
        _falha(peca, erro, dica),
        Resultado("Migração", Estado.NAO_VERIFICADA, f"{peca} indisponível"),
    ]


def _banco(
    abrir_sessao: Callable[..., AbstractContextManager[Session]],
    problemas_banco: list[str],
    head: str,
    migrar: str,
    sqlite: bool = False,
) -> list[Resultado]:
    peca = "SQLite" if sqlite else "Postgres"
    if problemas_banco:
        motivo = "variáveis do banco inválidas"
        return [
            Resultado(peca, Estado.NAO_VERIFICADA, motivo),
            Resultado("Migração", Estado.NAO_VERIFICADA, motivo),
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
                return [postgres, _falha("Migração", e, dica_banco)]
    except MotorError as e:
        return _banco_fora(peca, e, dica_banco)
    if revisao is None:
        migracao = Resultado(
            "Migração", Estado.FALHA, "banco sem migração aplicada", migrar
        )
    elif revisao != head:
        migracao = Resultado(
            "Migração",
            Estado.FALHA,
            f"banco na revisão {revisao}, esperado {head}",
            migrar,
        )
    else:
        migracao = Resultado("Migração", Estado.OK, f"revisão {head}")
    return [postgres, migracao]


def _projects_dir(env: Mapping[str, str]) -> Resultado:
    valor = env.get("PROJECTS_DIR", "").strip()
    if not valor:
        return Resultado(
            "PROJECTS_DIR", Estado.NAO_CONFIGURADO, "--repo aceita caminho absoluto"
        )
    if os.path.isdir(valor):
        return Resultado("PROJECTS_DIR", Estado.OK, valor)
    return Resultado(
        "PROJECTS_DIR",
        Estado.FALHA,
        f"diretório não existe: {valor}",
        "criar o diretório ou corrigir a variável",
    )


def _tarefas(config_central: Callable[[], ConfigProjeto]) -> Resultado:
    """A fonte de tarefas do `config.toml` central: o diagnóstico não tem repo.

    Credencial só é conferida se o plugin oferece `verificar_credenciais`.
    """
    plugins = "conferir [tarefas] fonte e os plugins instalados"
    try:
        config = config_central()
    except MotorError as e:
        return _falha("Tarefas", e, plugins)
    if config.fonte_tarefas is None:
        return Resultado(
            "Tarefas",
            Estado.NAO_CONFIGURADO,
            "sem [tarefas] fonte no config.toml central",
            "definir [tarefas] fonte no config.toml central",
        )
    try:
        fonte = instanciar_fonte_tarefas(config)
    except MotorError as e:
        return _falha("Tarefas", e, plugins)
    verificar = getattr(fonte, "verificar_credenciais", None)
    if not callable(verificar):
        return Resultado(
            "Tarefas", Estado.NAO_VERIFICADA, "a fonte não oferece verificação"
        )
    try:
        verificar()
    except MotorError as e:
        return _falha("Tarefas", e, "conferir as credenciais da fonte no .env")
    return Resultado("Tarefas", Estado.OK, "credenciais aceitas")


def _bitbucket(env: Mapping[str, str], cliente: httpx.Client | None) -> Resultado:
    token = env.get("BITBUCKET_TOKEN", "")
    if not token:
        return Resultado("Bitbucket", Estado.NAO_CONFIGURADO, "sem BITBUCKET_TOKEN")
    try:
        verificar_credenciais(token, env.get("BITBUCKET_EMAIL", ""), client=cliente)
    except MotorError as e:
        return _falha(
            "Bitbucket",
            e,
            "conferir BITBUCKET_TOKEN/BITBUCKET_EMAIL "
            "(o token precisa de escopo de leitura de conta)",
        )
    return Resultado("Bitbucket", Estado.OK, "credencial aceita")


def formatar(resultado: Resultado) -> str:
    linha = f"{resultado.estado.value}  {resultado.peca}"
    if resultado.detalhe:
        linha += f": {resultado.detalhe}"
    if resultado.correcao:
        linha += f" -> {resultado.correcao}"
    return linha


__all__ = [
    "Estado",
    "Resultado",
    "diagnosticar",
    "falhou",
    "formatar",
]
