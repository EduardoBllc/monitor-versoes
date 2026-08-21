from __future__ import annotations

import pytest

from motor.config import database_url, worktrees_mantidas
from motor.errors import ErroDeEntrada, MotorError

COMPLETO = {
    "DATABASE_HOST": "localhost",
    "DATABASE_PORT": "5433",
    "DATABASE_NAME": "monitor_versoes",
    "DATABASE_USER": "motor",
    "DATABASE_PASSWORD": "motor",
}


def _ambiente(monkeypatch, valores):
    for chave in COMPLETO:
        monkeypatch.delenv(chave, raising=False)
    for chave, valor in valores.items():
        monkeypatch.setenv(chave, valor)


def test_database_url_monta_a_partir_das_partes(monkeypatch):
    _ambiente(monkeypatch, COMPLETO)
    assert database_url() == (
        "postgresql+psycopg://motor:motor@localhost:5433/monitor_versoes"
    )


def test_database_url_escapa_caractere_que_quebraria_a_url(monkeypatch):
    # Sem quote, "s@nha" faria a URL apontar para o host "nha" e o erro
    # observado seria "conexao recusada", nao "senha invalida".
    _ambiente(monkeypatch, {**COMPLETO, "DATABASE_PASSWORD": "s@nha//#"})
    assert "@localhost:5433/" in database_url()
    assert "s%40nha%2F%2F%23" in database_url()


def test_database_url_lista_todas_as_variaveis_faltando(monkeypatch):
    _ambiente(monkeypatch, {"DATABASE_HOST": "localhost"})
    with pytest.raises(ErroDeEntrada) as erro:
        database_url()
    assert "DATABASE_PORT" in str(erro.value)
    assert "DATABASE_PASSWORD" in str(erro.value)


def test_database_url_recusa_porta_nao_numerica(monkeypatch):
    # create_engine converte a porta na hora e levanta ValueError, que cairia no
    # ramo de bug do CLI (traceback) em vez de virar mensagem para o operador.
    _ambiente(monkeypatch, {**COMPLETO, "DATABASE_PORT": "5433a"})
    with pytest.raises(ErroDeEntrada) as erro:
        database_url()
    assert "DATABASE_PORT" in str(erro.value)


def test_sessao_postgres_recusa_banco_de_producao(monkeypatch, request):
    import sqlalchemy

    _ambiente(monkeypatch, COMPLETO)

    def nao_conectar(*args, **kwargs):
        raise AssertionError("fixture tentou conectar no banco de producao")

    monkeypatch.setattr(sqlalchemy, "create_engine", nao_conectar)

    with pytest.raises(pytest.fail.Exception, match="development"):
        request.getfixturevalue("sessao_postgres")


# -- worktrees mantidas -------------------------------------------------------
#
# setenv("") em vez de delenv: e o que um `.env` com a linha vazia produz, e a
# disciplina do conftest para variavel "ausente" (ver .claude/CLAUDE.md).


def test_worktrees_mantidas_default_quando_ausente(monkeypatch):
    monkeypatch.setenv("WORKTREES_MANTIDAS", "")
    assert worktrees_mantidas() == 3


def test_worktrees_mantidas_le_do_ambiente(monkeypatch):
    monkeypatch.setenv("WORKTREES_MANTIDAS", "7")
    assert worktrees_mantidas() == 7


def test_worktrees_mantidas_aceita_zero(monkeypatch):
    # 0 e o comportamento historico (worktree descartada a cada run), nao
    # "nao configurado" — por isso o default nao pode vir de `or`.
    monkeypatch.setenv("WORKTREES_MANTIDAS", "0")
    assert worktrees_mantidas() == 0


@pytest.mark.parametrize("valor", ["abc", "-1", "1.5", "3 worktrees"])
def test_worktrees_mantidas_recusa_valor_invalido(monkeypatch, valor):
    # Cair no default calado faria o operador achar que configurou.
    monkeypatch.setenv("WORKTREES_MANTIDAS", valor)
    with pytest.raises(MotorError, match="WORKTREES_MANTIDAS"):
        worktrees_mantidas()
