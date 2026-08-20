from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(
    Path(__file__).resolve().parents[1] / ".env.development",
    override=True,
)


@pytest.fixture(autouse=True)
def _sem_dotenv_dentro_do_main(monkeypatch):
    """Guarda estrutural do "sem rede": desliga o load_dotenv() do main().

    Sem ela, `main()` repovoa o ambiente a cada invocacao e toda variavel que um
    teste apagou com `monkeypatch.delenv` volta do `.env` de produção — foi assim
    que um teste de credencial ausente saiu para o host real do Tickio na Task
    12. A disciplina de autor (usar `setenv("")` em vez de `delenv`) nao e
    guarda: ela vale ate o proximo teste escrito sem lembrar dela.

    Nao muda nada de fato: o `.env.development` de nivel de modulo acima ja
    povoou o ambiente no momento da coleta.
    """
    import motor.__main__ as cli

    monkeypatch.setattr(cli, "load_dotenv", None)


_TRUNCATE_TUDO = (
    "truncate atribuicao_commit, atribuicao, versao, exclusao, "
    "sem_entrega, repo_alias, repo restart identity cascade"
)

_BANCO_DEVELOPMENT = {
    "DATABASE_HOST": "localhost",
    "DATABASE_PORT": "5434",
    "DATABASE_NAME": "monitor_versoes_development",
    "DATABASE_USER": "motor_development",
}


def _exigir_banco_development() -> None:
    atual = {chave: os.environ.get(chave, "") for chave in _BANCO_DEVELOPMENT}
    if atual != _BANCO_DEVELOPMENT:
        pytest.fail(
            "recusado: testes destrutivos exigem o banco definido em "
            ".env.development"
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
    _exigir_banco_development()

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
        pytest.skip(
            "Postgres inalcancavel — suba com: "
            "docker compose --env-file .env.development up -d"
        )

    fabrica = sessionmaker(engine)
    try:
        with fabrica() as sessao:
            yield sessao
        _limpar(engine)
    finally:
        engine.dispose()
