"""Engine e esquema do estado, nos dois backends (SQLite e Postgres)."""

from __future__ import annotations

import os
from typing import Any

from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from alembic import command
from motor.adapters.estado.postgres import PostgresEstado

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def normalizar_url(url: str) -> str:
    """`postgresql://` e `postgres://` vao para o driver instalado (psycopg v3)."""
    for prefixo in ("postgresql://", "postgres://"):
        if url.startswith(prefixo):
            return "postgresql+psycopg://" + url[len(prefixo) :]
    return url


def criar_engine(url: str) -> Engine:
    """Engine do estado. No SQLite liga as FKs em toda conexao: o padrao do
    SQLite e ignora-las, e o contrato "atribuicao em versao inexistente e
    recusada" depende delas."""
    engine = create_engine(normalizar_url(url))
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _ligar_fks(conexao: Any, _registro: Any) -> None:
            cursor = conexao.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def aplicar_migracoes(url: str) -> None:
    """`alembic upgrade head` por codigo, na `url` dada (nao a da config)."""
    config = Config(os.path.join(RAIZ, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(RAIZ, "alembic"))
    config.attributes["url"] = normalizar_url(url)
    command.upgrade(config, "head")


def garantir_esquema(url: str) -> bool:
    """Aplica as migrations se o banco ainda nao tem esquema.

    Devolve `True` quando aplicou. Banco ja migrado (mesmo numa revisao antiga)
    nao e tocado: a divergencia de revisao e do `motor diagnostico`.
    """
    engine = criar_engine(url)
    try:
        with Session(engine) as sessao:
            migrado = PostgresEstado(sessao=sessao).revisao_migracao() is not None
    finally:
        engine.dispose()
    if migrado:
        return False
    aplicar_migracoes(url)
    return True
