"""Diagnóstico da instalação: checa cada peça e diz qual falhou e como corrigir.

Tudo chega por parâmetro (ambiente, abertura de sessão, cliente HTTP, `head` do
alembic), para ser testável sem banco real nem rede. Não tem efeito colateral:
não escreve no banco, não roda git, não exige repo cadastrado.
"""

from __future__ import annotations

import enum
import os
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass

import httpx
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from motor.adapters.commitsource.bitbucket import verificar_credenciais
from motor.adapters.estado.postgres import PostgresEstado
from motor.adapters.tasksource.tickio import TickioRest
from motor.errors import MotorError, formatar_com_notas


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
_VARIAVEIS_TICKIO = ("TICKIO_BASE_URL", "TICKIO_USER", "TICKIO_PASSWORD")


def head_do_alembic(raiz: str) -> str:
    """Revisão `head` dos scripts do alembic em `raiz` (onde vive `alembic.ini`)."""
    config = Config(os.path.join(raiz, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(raiz, "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None  # o repo sempre tem ao menos uma migração
    return head


def _falha(peca: str, erro: MotorError, correcao: str) -> Resultado:
    return Resultado(peca, Estado.FALHA, formatar_com_notas(erro), correcao)


def _variaveis_ausentes(env: Mapping[str, str], nomes: tuple[str, ...]) -> list[str]:
    return [n for n in nomes if not env.get(n, "").strip()]


def _problemas_do_banco(env: Mapping[str, str]) -> list[str]:
    problemas = _variaveis_ausentes(env, _VARIAVEIS_BANCO)
    porta = env.get("DATABASE_PORT", "")
    if porta and not porta.isdigit():
        problemas.append("DATABASE_PORT (esperado número)")
    return problemas


def diagnosticar(
    env: Mapping[str, str],
    *,
    abrir_sessao: Callable[[], AbstractContextManager[Session]],
    head: str,
    ambiente: str,
    cliente: httpx.Client | None = None,
) -> list[Resultado]:
    arquivo = ".env.development" if ambiente == "development" else ".env"
    migrar = "make migrate-dev" if ambiente == "development" else "make migrate"

    problemas_banco = _problemas_do_banco(env)
    ausentes_tickio = _variaveis_ausentes(env, _VARIAVEIS_TICKIO)
    problemas = problemas_banco + ausentes_tickio

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
    resultados += _banco(abrir_sessao, problemas_banco, head, migrar)
    resultados.append(_projects_dir(env))
    resultados.append(_tickio(env, ausentes_tickio, cliente))
    resultados.append(_bitbucket(env, cliente))
    return resultados


def _banco(
    abrir_sessao: Callable[[], AbstractContextManager[Session]],
    problemas_banco: list[str],
    head: str,
    migrar: str,
) -> list[Resultado]:
    if problemas_banco:
        motivo = "variáveis do banco inválidas"
        return [
            Resultado("Postgres", Estado.NAO_VERIFICADA, motivo),
            Resultado("Migração", Estado.NAO_VERIFICADA, motivo),
        ]
    dica_banco = "docker compose up -d e conferir DATABASE_*"
    try:
        with abrir_sessao() as sessao:
            estado = PostgresEstado(sessao=sessao)
            try:
                estado.verificar_conexao()
            except MotorError as e:
                return [
                    _falha("Postgres", e, dica_banco),
                    Resultado(
                        "Migração", Estado.NAO_VERIFICADA, "Postgres indisponível"
                    ),
                ]
            postgres = Resultado("Postgres", Estado.OK, "conexão funciona")
            try:
                revisao = estado.revisao_migracao()
            except MotorError as e:
                return [postgres, _falha("Migração", e, dica_banco)]
    except MotorError as e:
        return [
            _falha("Postgres", e, dica_banco),
            Resultado("Migração", Estado.NAO_VERIFICADA, "Postgres indisponível"),
        ]
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


def _tickio(
    env: Mapping[str, str], ausentes: list[str], cliente: httpx.Client | None
) -> Resultado:
    if ausentes:
        return Resultado(
            "Tickio", Estado.NAO_VERIFICADA, "variáveis ausentes (ver Variáveis)"
        )
    fonte = TickioRest(
        base_url=env["TICKIO_BASE_URL"],
        usuario=env["TICKIO_USER"],
        senha=env["TICKIO_PASSWORD"],
        sistema_id=0,
        client=cliente,
    )
    try:
        fonte.verificar_credenciais()
    except MotorError as e:
        return _falha("Tickio", e, "conferir TICKIO_*")
    return Resultado("Tickio", Estado.OK, "autenticação aceita")


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
    "head_do_alembic",
]
