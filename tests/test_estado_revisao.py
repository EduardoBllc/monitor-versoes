"""`revisao_migracao` com SQLite em memória."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from motor.adapters.estado.sqlite import Estado


def _sessao() -> Session:
    return Session(create_engine("sqlite://"))


def test_devolve_a_revisao_gravada():
    with _sessao() as sessao:
        sessao.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
        sessao.execute(text("INSERT INTO alembic_version VALUES ('abc123')"))
        assert Estado(sessao=sessao).revisao_migracao() == "abc123"


def test_sem_a_tabela_devolve_none():
    with _sessao() as sessao:
        assert Estado(sessao=sessao).revisao_migracao() is None


def test_tabela_vazia_devolve_none():
    with _sessao() as sessao:
        sessao.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
        assert Estado(sessao=sessao).revisao_migracao() is None
