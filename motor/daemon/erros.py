"""Erro do motor -> status HTTP e corpo `{tipo, mensagem}` da API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus

from motor.errors import (
    BackendIndisponivel,
    ErroDeEntrada,
    MotorError,
    NaoEncontrado,
    RecusaDeInvariante,
    RespostaInvalida,
    formatar_com_notas,
)

MENSAGEM_INTERNA = "erro interno do daemon; veja o log"

logger = logging.getLogger(__name__)


class TipoErro(StrEnum):
    ENTRADA = "entrada"
    NAO_ENCONTRADO = "nao_encontrado"
    RECUSA = "recusa"
    BACKEND = "backend"
    RESPOSTA = "resposta"
    MOTOR = "motor"
    OCUPADO = "ocupado"
    INTERNO = "interno"


@dataclass(frozen=True)
class ErroApi:
    tipo: TipoErro
    mensagem: str


class RepoOcupado(MotorError):
    def __init__(self, repo: str) -> None:
        super().__init__(f"repo {repo} já tem uma operação em andamento")


# Ordem irrelevante: a resolução anda pela MRO do erro, do mais específico ao MotorError.
_TABELA: dict[type[MotorError], tuple[HTTPStatus, TipoErro]] = {
    ErroDeEntrada: (HTTPStatus.UNPROCESSABLE_ENTITY, TipoErro.ENTRADA),
    NaoEncontrado: (HTTPStatus.NOT_FOUND, TipoErro.NAO_ENCONTRADO),
    RecusaDeInvariante: (HTTPStatus.CONFLICT, TipoErro.RECUSA),
    BackendIndisponivel: (HTTPStatus.SERVICE_UNAVAILABLE, TipoErro.BACKEND),
    RespostaInvalida: (HTTPStatus.BAD_GATEWAY, TipoErro.RESPOSTA),
    RepoOcupado: (HTTPStatus.CONFLICT, TipoErro.OCUPADO),
    MotorError: (HTTPStatus.INTERNAL_SERVER_ERROR, TipoErro.MOTOR),
}


def erro_api(erro: BaseException) -> tuple[HTTPStatus, ErroApi]:
    if not isinstance(erro, MotorError):
        logger.error("erro não previsto no daemon", exc_info=erro)
        return HTTPStatus.INTERNAL_SERVER_ERROR, ErroApi(
            TipoErro.INTERNO, MENSAGEM_INTERNA
        )
    for classe in type(erro).__mro__:
        if classe in _TABELA:
            status, tipo = _TABELA[classe]
            return status, ErroApi(tipo, formatar_com_notas(erro))
    raise AssertionError("MotorError sempre está na tabela")  # pragma: no cover
