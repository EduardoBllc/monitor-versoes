"""Traducao de erro do banco no Estado, sem banco de verdade.

Estes casos sao sobre qual excecao o adapter captura, sem banco nenhum: a
garantia "MotorError e mensagem limpa, qualquer outra excecao e bug com
traceback" vale independente do que o banco devolve.
"""

from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import Session

from motor.adapters.estado.sqlite import (
    ERRCODE_VERSAO_CONGELADA,
    Estado,
)
from motor.errors import (
    BackendIndisponivel,
    MotorError,
    RecusaDeInvariante,
)


class _SessaoQueFalha:
    """Sessao cuja primeira leitura estoura com a excecao dada."""

    def __init__(self, erro: Exception) -> None:
        self.erro = erro
        self.rollbacks = 0

    def scalar(self, stmt: object) -> object:
        raise self.erro

    def rollback(self) -> None:
        self.rollbacks += 1


def _como_sessao(dobro: _SessaoQueFalha) -> Session:
    """Double deliberadamente parcial: o adapter so chama `scalar` e `rollback`
    no caminho de erro. Implementar a Session inteira para tres metodos usados
    seria mais codigo do que o teste inteiro.
    """
    return cast(Session, dobro)


def test_conexao_morta_no_meio_do_comando_vira_motorerror():
    """InterfaceError e IRMAO de DatabaseError sob DBAPIError, nao filho: com o
    catch em DatabaseError, uma conexao que morre no meio do comando escapava
    do adapter e saia como "Erro interno fatal (bug)" com traceback do driver
    — a confusao operador-vs-bug que o motor promete nao fazer.
    """
    sessao = _SessaoQueFalha(
        InterfaceError("select 1", None, Exception("connection already closed"))
    )

    with pytest.raises(MotorError) as e:
        Estado(sessao=_como_sessao(sessao)).exclusoes("webapp")

    assert "connection already closed" in str(e.value)
    assert sessao.rollbacks == 1


def test_congelamento_identificado_pelo_marcador_nao_pelo_texto():
    """A trigger poe MV001 na mensagem. Procurar "imutavel" no texto acoplaria
    o adapter a uma frase que vive numa migracao, outro arquivo.
    """
    import sqlite3

    sessao = _SessaoQueFalha(
        OperationalError(
            "insert ...",
            None,
            # texto deliberadamente SEM "imutavel": so o marcador identifica
            sqlite3.IntegrityError(f"{ERRCODE_VERSAO_CONGELADA}: versao travada"),
        )
    )

    with pytest.raises(
        RecusaDeInvariante, match="remarque a tarefa para a proxima versao"
    ):
        Estado(sessao=_como_sessao(sessao)).exclusoes("webapp")


# -- verificar_conexao (monitor-versoes diagnostico) -------------------------


class _SessaoExecuteFalha(_SessaoQueFalha):
    def execute(self, stmt: object) -> object:
        raise self.erro


def test_verificar_conexao_com_erro_do_sqlite_e_backend_indisponivel():
    import sqlite3

    sessao = _SessaoExecuteFalha(
        OperationalError(
            "select 1", None, sqlite3.OperationalError("unable to open database")
        )
    )

    with pytest.raises(BackendIndisponivel, match="DATABASE_SQLITE_PATH"):
        Estado(sessao=_como_sessao(sessao)).verificar_conexao()


def test_verificar_conexao_com_erro_de_fora_do_sqlite_nao_e_backend_indisponivel():
    sessao = _SessaoExecuteFalha(
        OperationalError("select 1", None, Exception("outra coisa"))
    )

    with pytest.raises(MotorError) as e:
        Estado(sessao=_como_sessao(sessao)).verificar_conexao()

    assert not isinstance(e.value, BackendIndisponivel)


def test_erro_sqlite_com_marcador_vira_recusa_de_invariante():
    import sqlite3

    from sqlalchemy.exc import IntegrityError

    class _Sessao:
        def rollback(self):
            pass

    estado = Estado(sessao=_Sessao())  # type: ignore[arg-type]
    erro = IntegrityError(
        "update", None, sqlite3.IntegrityError("MV001: versao liberada e imutavel")
    )
    with pytest.raises(RecusaDeInvariante):
        estado._traduzir_erro(erro)


def test_erro_sqlite_sem_marcador_nao_sugere_docker():
    import sqlite3

    from sqlalchemy.exc import OperationalError

    class _Sessao:
        def rollback(self):
            pass

    estado = Estado(sessao=_Sessao())  # type: ignore[arg-type]
    erro = OperationalError("select 1", None, sqlite3.OperationalError("disk I/O"))
    with pytest.raises(BackendIndisponivel) as e:
        estado._traduzir_erro(erro)
    assert "docker" not in str(e.value)
    assert "DATABASE_SQLITE_PATH" in str(e.value)
