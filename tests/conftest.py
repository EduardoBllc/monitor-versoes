from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

load_dotenv()


@pytest.fixture
def sessao_postgres():
    """Sessao contra o Postgres real. Pula quando o banco nao esta configurado
    ou nao responde (container parado) — a suite tem que rodar sem banco."""
    if not os.environ.get("DATABASE_HOST"):
        pytest.skip("DATABASE_HOST ausente — banco nao configurado")

    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    from motor.config import database_url

    engine = create_engine(database_url())
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "truncate atribuicao_commit, atribuicao, versao, exclusao, "
                    "sem_entrega, repo_alias, repo restart identity cascade"
                )
            )
            conn.commit()
    except OperationalError:
        engine.dispose()
        pytest.skip("Postgres inalcancavel — suba com: docker compose up -d")

    fabrica = sessionmaker(engine)
    with fabrica() as sessao:
        yield sessao
    engine.dispose()
