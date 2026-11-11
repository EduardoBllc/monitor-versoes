from __future__ import annotations

import threading
from typing import cast

import pytest

from motor.daemon.erros import ErroApi, TipoErro, erro_api
from motor.daemon.execucoes import EstadoExecucao, Execucoes, Operacao
from motor.engine.atualizar import AtualizarResult, AtualizarStatus
from motor.errors import (
    BackendIndisponivel,
    ErroDeEntrada,
    MotorError,
    NaoEncontrado,
    RecusaDeInvariante,
    RepoOcupado,
    RespostaInvalida,
)
from motor.progresso import Progresso, RelatorProgresso

ESPERA_S = 5.0


@pytest.mark.parametrize(
    ("erro", "status", "tipo"),
    [
        (ErroDeEntrada("x"), 422, TipoErro.ENTRADA),
        (NaoEncontrado("x"), 404, TipoErro.NAO_ENCONTRADO),
        (RecusaDeInvariante("x"), 409, TipoErro.RECUSA),
        (BackendIndisponivel("x"), 503, TipoErro.BACKEND),
        (RespostaInvalida("x"), 502, TipoErro.RESPOSTA),
        (MotorError("x"), 500, TipoErro.MOTOR),
        (RepoOcupado("r", 1), 409, TipoErro.OCUPADO),
    ],
)
def test_erro_api_mapeia_cada_tipo(
    erro: Exception, status: int, tipo: TipoErro
) -> None:
    erro.add_note("ctx")
    http, corpo = erro_api(erro)
    assert (http, corpo.tipo) == (status, tipo)
    assert "ctx" in corpo.mensagem


def test_erro_nao_motor_vira_interno_sem_vazar_texto() -> None:
    http, corpo = erro_api(RuntimeError("segredo"))
    assert (http, corpo.tipo) == (500, TipoErro.INTERNO)
    assert "segredo" not in corpo.mensagem
    assert isinstance(corpo, ErroApi)


def test_registro_nao_recusa_execucao_simultanea_no_mesmo_repo() -> None:
    """ "Ocupado" é só o lock do clone (decisão 032), não o registro."""
    liberar = threading.Event()

    def alvo(_: RelatorProgresso) -> None:
        liberar.wait(ESPERA_S)

    execucoes = Execucoes()
    try:
        execucoes.iniciar("a", "1.0.0", Operacao.VERIFICAR, alvo)
        primeira = execucoes._threads["a"]
        execucoes.iniciar("a", "1.0.0", Operacao.PREVIA, alvo)
        segunda = execucoes._threads["a"]
    finally:
        liberar.set()
    primeira.join(ESPERA_S)
    segunda.join(ESPERA_S)
    assert not primeira.is_alive() and not segunda.is_alive()


def _conclui(_: RelatorProgresso) -> None:
    return None


def _levanta(_: RelatorProgresso) -> None:
    raise NaoEncontrado("sumiu")


@pytest.mark.parametrize("alvo", [_conclui, _levanta], ids=["conclui", "levanta"])
def test_execucao_solta_a_trava_ao_terminar(tmp_path, alvo) -> None:
    from motor.trava import travar

    clone = str(tmp_path)
    execucoes = Execucoes()
    execucoes.iniciar("a", "1.0.0", Operacao.VERIFICAR, alvo, travar("a", clone))
    assert execucoes.aguardar("a", ESPERA_S)
    with travar("a", clone):
        pass


def test_execucao_conclui_com_resultado_e_progresso() -> None:
    resultado = AtualizarResult(AtualizarStatus.DONE)
    relatado = Progresso("x")

    def alvo(relatar: RelatorProgresso) -> AtualizarResult:
        relatar(relatado)
        return resultado

    execucoes = Execucoes()
    execucoes.iniciar("a", "1.0.0", Operacao.ATUALIZAR, alvo)
    assert execucoes.aguardar("a", ESPERA_S)
    atual = execucoes.atual("a")
    assert atual is not None
    assert atual.estado is EstadoExecucao.CONCLUIDA
    assert atual.resultado is resultado
    assert atual.progresso == relatado


def test_execucao_que_falha_guarda_erro_e_libera_o_repo() -> None:
    def falha(_: RelatorProgresso) -> None:
        raise NaoEncontrado("sumiu")

    execucoes = Execucoes()
    execucoes.iniciar("a", "1.0.0", Operacao.VERIFICAR, falha)
    assert execucoes.aguardar("a", ESPERA_S)
    atual = execucoes.atual("a")
    assert atual is not None
    assert atual.estado is EstadoExecucao.FALHOU
    assert atual.erro is not None
    assert atual.erro.tipo is TipoErro.NAO_ENCONTRADO

    execucoes.iniciar("a", "1.0.0", Operacao.VERIFICAR, lambda _: None)
    assert execucoes.aguardar("a", ESPERA_S)


def _concluir(
    execucoes: Execucoes,
    operacao: Operacao,
    status: AtualizarStatus | None = None,
    versao: str = "1.0.0",
) -> None:
    def alvo(_: RelatorProgresso) -> AtualizarResult | None:
        if status is None:
            raise RecusaDeInvariante("ainda em conflito")
        return AtualizarResult(status)

    execucoes.iniciar("a", versao, operacao, alvo)
    assert execucoes.aguardar("a", ESPERA_S)


def _pendentes(execucoes: Execucoes) -> list[tuple[str, AtualizarStatus]]:
    return [
        (e.versao, cast(AtualizarResult, e.resultado).status)
        for e in execucoes.pendencias("a")
    ]


def test_bloqueio_sobrevive_a_continuar_que_falha_e_a_verificar() -> None:
    execucoes = Execucoes()
    _concluir(execucoes, Operacao.ATUALIZAR, AtualizarStatus.BLOCKED)
    _concluir(execucoes, Operacao.CONTINUAR)
    _concluir(execucoes, Operacao.VERIFICAR, AtualizarStatus.DONE)
    _concluir(execucoes, Operacao.ATUALIZAR, AtualizarStatus.DONE, versao="2.0.0")
    assert _pendentes(execucoes) == [("1.0.0", AtualizarStatus.BLOCKED)]


def test_continuar_vazio_substitui_o_bloqueio() -> None:
    execucoes = Execucoes()
    _concluir(execucoes, Operacao.CRIAR, AtualizarStatus.BLOCKED)
    _concluir(execucoes, Operacao.CONTINUAR, AtualizarStatus.VAZIO)
    assert _pendentes(execucoes) == [("1.0.0", AtualizarStatus.VAZIO)]


def test_abortar_que_falha_limpa_o_bloqueio_resolvido_fora_da_web() -> None:
    execucoes = Execucoes()
    _concluir(execucoes, Operacao.ATUALIZAR, AtualizarStatus.BLOCKED)
    _concluir(execucoes, Operacao.ABORTAR)
    assert _pendentes(execucoes) == []


@pytest.mark.parametrize(
    ("operacao", "resultado"),
    [
        (Operacao.CONTINUAR, AtualizarResult(AtualizarStatus.DONE)),
        (Operacao.ABORTAR, None),
    ],
)
def test_continuar_concluido_ou_abortar_limpa_o_bloqueio(
    operacao: Operacao, resultado: AtualizarResult | None
) -> None:
    execucoes = Execucoes()
    _concluir(execucoes, Operacao.ATUALIZAR, AtualizarStatus.BLOCKED)
    execucoes.iniciar("a", "1.0.0", operacao, lambda _: resultado)
    assert execucoes.aguardar("a", ESPERA_S)
    assert _pendentes(execucoes) == []
