from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

load_dotenv()


@pytest.fixture(autouse=True)
def _sem_dotenv_dentro_do_main(monkeypatch):
    """Guarda estrutural do "sem rede": desliga o load_dotenv() do main().

    Sem ela, `main()` repovoa o ambiente a cada invocacao e toda variavel que um
    teste apagou com `monkeypatch.delenv` volta do .env de verdade — foi assim
    que um teste de credencial ausente saiu para o host real do Tickio na Task
    12. A disciplina de autor (usar `setenv("")` em vez de `delenv`) nao e
    guarda: ela vale ate o proximo teste escrito sem lembrar dela.

    Nao muda nada de fato: o `load_dotenv()` de nivel de modulo acima ja povoou
    o ambiente no momento da coleta.
    """
    import motor.__main__ as cli

    monkeypatch.setattr(cli, "load_dotenv", None)


_TRUNCATE_TUDO = (
    "truncate atribuicao_commit, atribuicao, versao, exclusao, "
    "sem_entrega, repo_alias, repo restart identity cascade"
)


@pytest.fixture
def sessao_postgres():
    """Sessao contra o Postgres real. Pula quando o banco nao esta configurado
    ou nao responde (container parado) — a suite tem que rodar sem banco.

    Limpa no setup E no teardown. Só no setup, cada teste comecava limpo mas a
    rodada inteira deixava as linhas do ultimo teste para tras, entao "o banco
    esta com zero linhas" so era verdade se alguem truncasse a mao — e uma vez
    custou investigar linhas residuais que ninguem sabia de onde vinham.
    """
    if not os.environ.get("DATABASE_HOST"):
        pytest.skip("DATABASE_HOST ausente — banco nao configurado")

    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    from motor.config import database_url

    def _limpar(engine) -> None:
        with engine.connect() as conn:
            conn.execute(text(_TRUNCATE_TUDO))
            conn.commit()

    engine = create_engine(database_url())
    try:
        _limpar(engine)
    except OperationalError:
        engine.dispose()
        pytest.skip("Postgres inalcancavel — suba com: docker compose up -d")

    fabrica = sessionmaker(engine)
    try:
        with fabrica() as sessao:
            yield sessao
        _limpar(engine)
    finally:
        engine.dispose()
