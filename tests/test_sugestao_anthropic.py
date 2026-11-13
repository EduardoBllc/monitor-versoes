"""Provedor `anthropic` sobre um transporte falso do SDK: sem rede e sem chave real."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from enum import StrEnum
from http import HTTPStatus

import anthropic
import httpx2
import pytest

from motor.adapters.sugestao import anthropic as modulo
from motor.adapters.sugestao.anthropic import (
    CHAVE_MODELO,
    ESQUEMA,
    INSTRUCAO,
    MAX_TOKENS,
    MODELO_PADRAO,
    Formato,
    Papel,
    Parada,
    ProvedorAnthropic,
    Var,
)
from motor.config import TABELA_AMBIENTE, Chave
from motor.domain.conflito import LadosDoBloco, PedidoAoProvedor, PropostaDeBloco
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida
from motor.montagem import GRUPO_SUGESTAO
from motor.plugins import carregar_plugin

CHAVE = "sk-SEGREDO"
NOME_PLUGIN = "anthropic"
ARQUIVO = "/cfg/config.toml"
OUTRO_MODELO = "claude-sonnet-5-5"
# O 529 da API (`overloaded_error`) não está no HTTPStatus.
STATUS_SOBRECARGA = 529

Handler = Callable[[httpx2.Request], httpx2.Response]


class _Tipo(StrEnum):
    """`type` dos objetos e dos erros que a API devolve."""

    MENSAGEM = "message"
    ERRO = "error"
    TEXTO = "text"
    AUTENTICACAO = "authentication_error"
    NAO_ENCONTRADO = "not_found_error"
    LIMITE = "rate_limit_error"
    SOBRECARGA = "overloaded_error"


class _Resposta(StrEnum):
    """Valores da resposta que o provedor não precisa nomear."""

    ASSISTENTE = "assistant"
    MAX_TOKENS = "max_tokens"


PEDIDO = PedidoAoProvedor(
    caminho="app/x.py",
    mensagem="fix: corrige o cálculo do frete (T-12)",
    chamado="T-12",
    blocos=[
        LadosDoBloco(ordem=0, base="a = 1\n", ours="a = 2\n", theirs="a = 3\n"),
        LadosDoBloco(ordem=2, base=None, ours="b = 1\n", theirs="b = 2\nc = 3\n"),
    ],
)

CONTEUDO_ESPERADO = {
    "caminho": "app/x.py",
    "mensagem": "fix: corrige o cálculo do frete (T-12)",
    "chamado": "T-12",
    "blocos": [
        {"ordem": 0, "base": "a = 1\n", "ours": "a = 2\n", "theirs": "a = 3\n"},
        {"ordem": 2, "ours": "b = 1\n", "theirs": "b = 2\nc = 3\n"},
    ],
}

PROPOSTAS = [
    PropostaDeBloco(ordem=0, conteudo="a = 3\n", justificativa="o commit corrige a"),
    PropostaDeBloco(ordem=2, conteudo="", justificativa="o commit remove b"),
]


@pytest.fixture(autouse=True)
def _chave_sem_espera(monkeypatch):
    monkeypatch.setenv(Var.CHAVE, CHAVE)
    monkeypatch.setattr(modulo, "MAX_RETRIES", 0)


def _provedor(handler: Handler, **sugestao: object) -> ProvedorAnthropic:
    cliente = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    return ProvedorAnthropic(
        sugestao={Chave.PROVEDOR: NOME_PLUGIN, **sugestao},
        arquivos=(ARQUIVO,),
        http_client=cliente,
    )


def _mensagem(texto: str, parada: str = Parada.FIM) -> httpx2.Response:
    return httpx2.Response(
        HTTPStatus.OK,
        json={
            "id": "msg_1",
            "type": _Tipo.MENSAGEM,
            "role": _Resposta.ASSISTENTE,
            "model": MODELO_PADRAO,
            "content": [{"type": _Tipo.TEXTO, "text": texto}],
            "stop_reason": parada,
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )


def _blocos(*blocos: dict[str, object]) -> str:
    return json.dumps({"blocos": list(blocos)})


def _propostas_em_json() -> str:
    return _blocos(*(vars(p) for p in PROPOSTAS))


def _erro(status: int, tipo: _Tipo) -> Handler:
    corpo = {"type": _Tipo.ERRO, "error": {"type": tipo, "message": "falhou"}}
    return lambda _: httpx2.Response(status, json=corpo)


def _responde(resposta: httpx2.Response) -> Handler:
    return lambda _: resposta


def _sem_rede(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("sem rede", request=request)


@pytest.mark.parametrize(
    ("sugestao", "modelo"),
    [({}, MODELO_PADRAO), ({CHAVE_MODELO: OUTRO_MODELO}, OUTRO_MODELO)],
)
def test_monta_a_chamada_com_a_chave_e_o_modelo(sugestao, modelo):
    pedidos: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        pedidos.append(request)
        return _mensagem(_propostas_em_json())

    _provedor(handler, **sugestao).propor(PEDIDO)

    [request] = pedidos
    # O SDK 2.x manda a `api_key` como Bearer, não no `x-api-key`.
    assert request.headers["authorization"] == f"Bearer {CHAVE}"
    corpo = json.loads(request.content)
    assert set(corpo) == {"model", "max_tokens", "system", "messages", "output_config"}
    assert corpo["model"] == modelo
    assert corpo["max_tokens"] == MAX_TOKENS
    assert corpo["system"] == INSTRUCAO
    assert corpo["output_config"] == {
        "format": {"type": Formato.ESQUEMA_JSON, "schema": ESQUEMA}
    }
    [mensagem] = corpo["messages"]
    assert mensagem["role"] == Papel.USUARIO
    assert json.loads(mensagem["content"]) == CONTEUDO_ESPERADO


def test_sem_tarefa_o_campo_nao_vai():
    pedidos: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        pedidos.append(request)
        return _mensagem(_propostas_em_json())

    _provedor(handler).propor(
        PedidoAoProvedor(PEDIDO.caminho, PEDIDO.mensagem, None, PEDIDO.blocos)
    )

    [mensagem] = json.loads(pedidos[0].content)["messages"]
    assert "chamado" not in json.loads(mensagem["content"])


def test_resposta_vira_proposta_por_bloco():
    provedor = _provedor(_responde(_mensagem(_propostas_em_json())))

    assert provedor.propor(PEDIDO) == PROPOSTAS


def test_sem_chave_pede_o_ambiente_e_nao_chama(monkeypatch):
    monkeypatch.setenv(Var.CHAVE, "")
    pedidos: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        pedidos.append(request)
        return _mensagem(_propostas_em_json())

    with pytest.raises(ErroDeEntrada) as erro:
        _provedor(handler).propor(PEDIDO)

    assert f"[{TABELA_AMBIENTE}]" in str(erro.value)
    assert Var.CHAVE in str(erro.value)
    assert pedidos == []


@pytest.mark.parametrize(
    ("handler", "esperado"),
    [
        (_sem_rede, BackendIndisponivel),
        (_erro(STATUS_SOBRECARGA, _Tipo.SOBRECARGA), BackendIndisponivel),
        (_erro(HTTPStatus.TOO_MANY_REQUESTS, _Tipo.LIMITE), BackendIndisponivel),
        (_erro(HTTPStatus.UNAUTHORIZED, _Tipo.AUTENTICACAO), ErroDeEntrada),
        (_erro(HTTPStatus.NOT_FOUND, _Tipo.NAO_ENCONTRADO), ErroDeEntrada),
        (_responde(_mensagem("", Parada.RECUSA)), RespostaInvalida),
        (_responde(_mensagem("{", _Resposta.MAX_TOKENS)), RespostaInvalida),
        (_responde(_mensagem("não é JSON")), RespostaInvalida),
        (
            _responde(_mensagem(_blocos({"ordem": 0, "conteudo": "x"}))),
            RespostaInvalida,
        ),
    ],
)
def test_falhas_da_api_por_tipo(handler, esperado):
    with pytest.raises(esperado) as erro:
        _provedor(handler).propor(PEDIDO)

    assert CHAVE not in str(erro.value)


def test_chave_nao_vaza():
    provedor = _provedor(_erro(HTTPStatus.UNAUTHORIZED, _Tipo.AUTENTICACAO))

    with pytest.raises(ErroDeEntrada) as erro:
        provedor.propor(PEDIDO)

    assert CHAVE not in repr(provedor)
    assert CHAVE not in str(erro.value)


def test_sem_sdk_pede_o_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)

    with pytest.raises(ErroDeEntrada) as erro:
        ProvedorAnthropic(sugestao={Chave.PROVEDOR: NOME_PLUGIN}, arquivos=())

    assert "monitor-versoes[anthropic]" in str(erro.value)


def test_sem_sdk_a_classe_carrega_e_declara_a_chave(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    # Sem o módulo em cache, a carga refaz o import do plugin sem o SDK.
    monkeypatch.delitem(sys.modules, modulo.__name__)

    classe = carregar_plugin(GRUPO_SUGESTAO, NOME_PLUGIN)

    assert Var.CHAVE in [c.chave for c in vars(classe)["campos_config"]]
