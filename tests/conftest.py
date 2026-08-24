from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]

load_dotenv(RAIZ / ".env.development", override=True)


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
    "sem_entrega, pr_commit_cache, bitbucket_pr, bitbucket_varredura, "
    "repo_alias, repo restart identity cascade"
)


@pytest.fixture(scope="session")
def _postgres_efemero() -> Iterator[Any]:
    """Postgres descartavel, um por sessao, morto no fim dela.

    Nao existe banco de teste de pe fora da rodada — era o ponto de trocar o
    container fixo do `.env.development` por testcontainers. A fixture e lazy:
    quem roda so `tests/test_git.py` nunca toca no Docker.

    Sem Docker a suite pula os testes de integracao, como antes pulava sem o
    container de pe — `pytest` continua verde numa maquina sem Docker nenhum.
    """
    from testcontainers.community.postgres import PostgresContainer

    # Mesma imagem do compose.yml: o schema tem trigger em plpgsql e checks de
    # dominio, e divergencia de major do Postgres apareceria como teste de
    # trigger falhando por motivo que nao e o codigo.
    container = PostgresContainer("postgres:18-alpine", driver="psycopg")
    try:
        container.start()
    except Exception as erro:
        # Amplo de proposito: daemon parado, socket ausente e imagem impossivel
        # de puxar chegam aqui como excecoes de tres bibliotecas diferentes, e
        # todas significam a mesma coisa para a suite — nao ha banco.
        pytest.skip(f"Docker inalcancavel ({type(erro).__name__}) — {erro}")

    try:
        # O ambiente e o que o alembic/env.py le (via database_url()), e o
        # load_dotenv() de la nao sobrescreve variavel ja presente — mesmo
        # mecanismo do `set -a` documentado no README.
        os.environ.update(
            DATABASE_HOST=container.get_container_host_ip(),
            DATABASE_PORT=str(container.get_exposed_port(5432)),
            DATABASE_NAME=container.dbname,
            DATABASE_USER=container.username,
            DATABASE_PASSWORD=container.password,
        )
        # alembic, nao Base.metadata.create_all: as triggers de congelamento de
        # versao nascem em migration, nao no metadata. Com create_all o schema
        # sobe sem elas e os testes de trigger falham dizendo "escrita
        # permitida" — sintoma que nao aponta para a causa.
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config(str(RAIZ / "alembic.ini")), "head")
        yield container
    finally:
        container.stop()


@pytest.fixture
def sessao_postgres(_postgres_efemero: Any) -> Iterator[Any]:
    """Sessao contra o Postgres efemero da sessao de teste.

    Limpa no setup E no teardown. Só no setup, cada teste comecava limpo mas a
    rodada inteira deixava as linhas do ultimo teste para tras, entao "o banco
    esta com zero linhas" so era verdade se alguem truncasse a mao — e uma vez
    custou investigar linhas residuais que ninguem sabia de onde vinham.

    A URL vem do container, nao de `database_url()`: o TRUNCATE nao tem como
    alcancar producao porque nao le o ambiente, que qualquer teste pode ter
    apontado para outro lugar com monkeypatch. Isso substitui a guarda
    `_exigir_banco_development`, que comparava as variaveis com as do
    `.env.development` antes de truncar.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    def _limpar(engine: Any) -> None:
        with engine.connect() as conn:
            conn.execute(text(_TRUNCATE_TUDO))
            conn.commit()

    engine = create_engine(_postgres_efemero.get_connection_url())
    try:
        _limpar(engine)
        fabrica = sessionmaker(engine)
        with fabrica() as sessao:
            yield sessao
        _limpar(engine)
    finally:
        engine.dispose()
