"""Traducao de erro do banco no PostgresEstado, sem banco de verdade.

Separado de test_estado_postgres.py, que e todo @integracao: estes casos sao
sobre qual excecao o adapter captura, e a garantia "MotorError e mensagem
limpa, qualquer outra excecao e bug com traceback" tem de valer na suite que
roda sem container.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import InterfaceError, OperationalError

from motor.adapters.estado.postgres import PostgresEstado
from motor.errors import MotorError


class _SessaoQueFalha:
    """Sessao cuja primeira leitura estoura com a excecao dada."""

    def __init__(self, erro: Exception) -> None:
        self.erro = erro
        self.rollbacks = 0

    def scalar(self, stmt):
        raise self.erro

    def rollback(self) -> None:
        self.rollbacks += 1


def test_conexao_morta_no_meio_do_comando_vira_motorerror():
    """InterfaceError e IRMAO de DatabaseError sob DBAPIError, nao filho: com o
    catch em DatabaseError, uma conexao que morre no meio do comando escapava
    do adapter e saia como "Erro interno fatal (bug)" com traceback de psycopg
    — a confusao operador-vs-bug que o motor promete nao fazer.
    """
    sessao = _SessaoQueFalha(
        InterfaceError("select 1", None, Exception("connection already closed"))
    )

    with pytest.raises(MotorError) as e:
        PostgresEstado(sessao=sessao).exclusoes("vendabemweb")

    assert "connection already closed" in str(e.value)
    assert sessao.rollbacks == 1


def test_banco_fora_do_ar_continua_com_a_dica_do_compose():
    """O ramo isinstance(OperationalError) continua valendo com o catch mais
    largo — OperationalError tambem e DBAPIError.
    """
    sessao = _SessaoQueFalha(
        OperationalError("select 1", None, Exception("connection refused"))
    )

    with pytest.raises(MotorError) as e:
        PostgresEstado(sessao=sessao).exclusoes("vendabemweb")

    assert "docker compose up -d" in str(e.value)
