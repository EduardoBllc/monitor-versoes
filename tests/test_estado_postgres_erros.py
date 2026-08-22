"""Traducao de erro do banco no PostgresEstado, sem banco de verdade.

Separado de test_estado_postgres.py, que e todo @integracao: estes casos sao
sobre qual excecao o adapter captura, e a garantia "MotorError e mensagem
limpa, qualquer outra excecao e bug com traceback" tem de valer na suite que
roda sem container.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import Session

from motor.adapters.estado.postgres import (
    ERRCODE_VERSAO_CONGELADA,
    PostgresEstado,
)
from motor.errors import (
    BackendIndisponivel,
    MotorError,
    RecusaDeInvariante,
    RespostaInvalida,
)


class _OrigComSqlstate(Exception):
    """psycopg poe sqlstate na excecao original; o adapter ramifica por ele."""

    def __init__(self, mensagem: str, sqlstate: str) -> None:
        super().__init__(mensagem)
        self.sqlstate = sqlstate


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
    do adapter e saia como "Erro interno fatal (bug)" com traceback de psycopg
    — a confusao operador-vs-bug que o motor promete nao fazer.
    """
    sessao = _SessaoQueFalha(
        InterfaceError("select 1", None, Exception("connection already closed"))
    )

    with pytest.raises(MotorError) as e:
        PostgresEstado(sessao=_como_sessao(sessao)).exclusoes("vendabemweb")

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
        PostgresEstado(sessao=_como_sessao(sessao)).exclusoes("vendabemweb")

    assert "docker compose up -d" in str(e.value)


def test_conexao_morta_ganha_a_dica_do_compose():
    """Sem sqlstate = o servidor nunca respondeu, e o unico caso em que "suba o
    container" ajuda. InterfaceError cai aqui, nao no ramo genERico.
    """
    sessao = _SessaoQueFalha(
        InterfaceError("select 1", None, Exception("connection already closed"))
    )

    with pytest.raises(BackendIndisponivel, match="docker compose up -d"):
        PostgresEstado(sessao=_como_sessao(sessao)).exclusoes("vendabemweb")


def test_deadlock_nao_e_reportado_como_banco_inacessivel():
    """psycopg mapeia deadlock (40P01) e statement timeout (57014) para
    OperationalError tambem. Ramificar por tipo mandava os dois para "banco
    inacessivel ... docker compose up -d" — banco que respondeu, e a resposta foi
    erro de execucao. Mandar o operador subir container que ja esta de pe.
    """
    sessao = _SessaoQueFalha(
        OperationalError("update ...", None, _OrigComSqlstate("deadlock detected", "40P01"))
    )

    with pytest.raises(MotorError) as e:
        PostgresEstado(sessao=_como_sessao(sessao)).exclusoes("vendabemweb")

    assert "deadlock detected" in str(e.value)
    assert "docker compose" not in str(e.value), (
        f"mensagem = {str(e.value)!r}; deadlock nao e banco fora do ar"
    )


def test_congelamento_identificado_pelo_errcode_nao_pelo_texto():
    """A trigger levanta com errcode MV001. Antes o adapter procurava
    "imutavel" no texto, entao reescrever a mensagem da trigger — que vive numa
    migracao, outro arquivo — quebrava esta traducao em silencio.
    """
    sessao = _SessaoQueFalha(
        OperationalError(
            "insert ...",
            None,
            # texto deliberadamente SEM "imutavel": so o errcode identifica
            _OrigComSqlstate("versao travada (versao_id=3)", ERRCODE_VERSAO_CONGELADA),
        )
    )

    with pytest.raises(RecusaDeInvariante, match="remarque a tarefa para a proxima versao"):
        PostgresEstado(sessao=_como_sessao(sessao)).exclusoes("vendabemweb")


class _SessaoQueDevolve:
    """Sessao cuja sequencia de scalar() devolve as linhas dadas, na ordem.

    Diferente de _SessaoQueFalha: aqui a leitura tem sucesso — o caminho de
    RespostaInvalida nao passa por excecao do banco, passa por dado bom que
    chegou fora do dominio esperado.
    """

    def __init__(self, *linhas: object) -> None:
        self._linhas = list(linhas)

    def scalar(self, stmt: object) -> object:
        return self._linhas.pop(0)


def test_tipo_de_versao_invalido_no_banco_vira_resposta_invalida():
    """versao() traduz o texto da coluna pelo dict reverso; um valor fora do
    trio conhecido (fechada/ajustada/cliente) e resposta fora do contrato,
    nao excecao do banco — RespostaInvalida, nao MotorError puro.
    """
    sessao = _SessaoQueDevolve(SimpleNamespace(id=1), SimpleNamespace(tipo="bugado"))

    with pytest.raises(RespostaInvalida, match="bugado"):
        PostgresEstado(sessao=cast(Session, sessao)).versao("vendabemweb", "13.34.0")
