"""`revisao_migracao` com SQLite em memória (a suíte de integração exige Docker)."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from motor.adapters.estado.postgres import PostgresEstado


def _sessao() -> Session:
    return Session(create_engine("sqlite://"))


def test_devolve_a_revisao_gravada():
    with _sessao() as sessao:
        sessao.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
        sessao.execute(text("INSERT INTO alembic_version VALUES ('abc123')"))
        assert PostgresEstado(sessao=sessao).revisao_migracao() == "abc123"


def test_sem_a_tabela_devolve_none():
    with _sessao() as sessao:
        assert PostgresEstado(sessao=sessao).revisao_migracao() is None


def test_tabela_vazia_devolve_none():
    with _sessao() as sessao:
        sessao.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
        assert PostgresEstado(sessao=sessao).revisao_migracao() is None
