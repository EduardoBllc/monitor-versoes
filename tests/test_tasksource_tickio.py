from __future__ import annotations

import httpx
import pytest

from motor.adapters.tasksource.tickio import TickioRest
from motor.errors import MotorError


def _fonte(handler, **kwargs) -> TickioRest:
    client = httpx.Client(transport=httpx.MockTransport(handler),
                          base_url="http://testserver")
    return TickioRest(base_url="http://testserver", usuario="u", senha="p",
                      sistema_id=1, client=client, **kwargs)


def test_autentica_e_busca_chamados():
    chamadas = []

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append(str(request.url))
        if request.url.path == "/api/v1/ws/token/":
            return httpx.Response(200, json={"access": "tok", "refresh": "ref"})
        assert request.headers["Authorization"] == "Bearer tok"
        assert request.url.params["sistema"] == "1"
        assert request.url.params["versao"] == "13.34.0"
        return httpx.Response(200, json=[{"chamado": "123456"}, {"chamado": "999111"}])

    assert _fonte(handler).fetch("13.34.0") == ["123456", "999111"]
    assert chamadas[0].endswith("/api/v1/ws/token/")


def test_aceita_lista_crua_de_numeros():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ws/token/":
            return httpx.Response(200, json={"access": "tok"})
        return httpx.Response(200, json=[123456, "999111"])

    assert _fonte(handler).fetch("13.34.0") == ["123456", "999111"]


def test_aceita_envelope_paginado():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ws/token/":
            return httpx.Response(200, json={"access": "tok"})
        return httpx.Response(200, json={"results": [{"chamado": "123456"}],
                                         "next": None})

    assert _fonte(handler).fetch("13.34.0") == ["123456"]


def test_autentica_uma_vez_so_por_instancia():
    tokens = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ws/token/":
            tokens.append(1)
            return httpx.Response(200, json={"access": "tok"})
        return httpx.Response(200, json=[])

    fonte = _fonte(handler)
    fonte.fetch("13.34.0")
    fonte.fetch("14.0.0")
    assert len(tokens) == 1


def test_credencial_invalida_vira_motorerror():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="credenciais invalidas")

    with pytest.raises(MotorError, match="autenticando no Tickio"):
        _fonte(handler).fetch("13.34.0")


def test_erro_na_listagem_vira_motorerror():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ws/token/":
            return httpx.Response(200, json={"access": "tok"})
        return httpx.Response(500, text="boom")

    with pytest.raises(MotorError, match="500"):
        _fonte(handler).fetch("13.34.0")


def test_rejeita_corpo_em_formato_desconhecido():
    """Um dict sem 'results' nao deve virar lista vazia silenciosa: um corpo
    nao reconhecido tem que gritar, nao parecer 'nenhum chamado nesta versao'.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ws/token/":
            return httpx.Response(200, json={"access": "tok"})
        return httpx.Response(200, json={"detail": "nao encontrado"})

    with pytest.raises(MotorError, match="formato inesperado"):
        _fonte(handler).fetch("13.34.0")


def test_rejeita_item_sem_numero_de_chamado():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ws/token/":
            return httpx.Response(200, json={"access": "tok"})
        return httpx.Response(200, json=[{"titulo": "sem numero aqui"}])

    with pytest.raises(MotorError, match="sem numero de chamado"):
        _fonte(handler).fetch("13.34.0")
