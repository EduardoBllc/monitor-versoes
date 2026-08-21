from __future__ import annotations

import httpx
import pytest

from motor.adapters.tasksource.tickio import TickioRest, _extrair_chamados
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida


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


def test_aceita_envelope_real_do_tickio():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ws/token/":
            return httpx.Response(200, json={"access": "tok"})
        return httpx.Response(200, json={
            "sistema_id": 1,
            "sistema": "VB Web",
            "versao": "15.0.0",
            "total": 2,
            "chamados": [243353, 249991],
        })

    assert _fonte(handler).fetch("15.0.0") == ["243353", "249991"]


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

    with pytest.raises(BackendIndisponivel, match="autenticando no Tickio"):
        _fonte(handler).fetch("13.34.0")


def test_erro_na_listagem_vira_motorerror():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ws/token/":
            return httpx.Response(200, json={"access": "tok"})
        return httpx.Response(500, text="boom")

    with pytest.raises(BackendIndisponivel, match="500"):
        _fonte(handler).fetch("13.34.0")


def test_rejeita_corpo_em_formato_desconhecido():
    """Um dict sem lista conhecida nao deve virar lista vazia silenciosa."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ws/token/":
            return httpx.Response(200, json={"access": "tok"})
        return httpx.Response(200, json={"detail": "nao encontrado"})

    with pytest.raises(RespostaInvalida):
        _fonte(handler).fetch("13.34.0")


def test_rejeita_item_sem_numero_de_chamado():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ws/token/":
            return httpx.Response(200, json={"access": "tok"})
        return httpx.Response(200, json=[{"titulo": "sem numero aqui"}])

    with pytest.raises(RespostaInvalida):
        _fonte(handler).fetch("13.34.0")


def test_repr_nao_vaza_senha_nem_jwt():
    """--debug sobe o logging para DEBUG: qualquer repr desta dataclass (dump
    de deps, repr de excecao) imprimiria a credencial e o JWT em claro."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ws/token/":
            return httpx.Response(200, json={"access": "jwt-secreto"})
        return httpx.Response(200, json=[])

    client = httpx.Client(transport=httpx.MockTransport(handler),
                          base_url="http://testserver")
    fonte = TickioRest(base_url="http://testserver", usuario="u",
                       senha="senha-secreta", sistema_id=1, client=client)
    fonte.fetch("13.34.0")

    # os dois valores estao no objeto — sem isto o teste passaria por vazio
    assert (fonte.senha, fonte._access) == ("senha-secreta", "jwt-secreto")
    assert "senha-secreta" not in repr(fonte)
    assert "jwt-secreto" not in repr(fonte)


def test_formato_inesperado_e_resposta_invalida_nao_backend_fora():
    """A secao 10 do desenho registra que o corpo de resposta do Tickio nunca
    foi observado. Distinguir "respondeu lixo" de "nao respondeu" e o que
    permite ao operador saber se o problema e rede ou contrato.
    """
    with pytest.raises(RespostaInvalida):
        _extrair_chamados({"forma": "nao reconhecida"})


def test_variavel_faltando_e_erro_de_entrada_nao_backend():
    fonte = TickioRest(base_url="", usuario="", senha="", sistema_id=7)

    with pytest.raises(ErroDeEntrada, match="faltando no .env"):
        fonte.fetch("13.34.0")


def test_base_url_malformada_ao_autenticar_vira_errodeentrada_nao_invalidurl():
    """httpx.InvalidURL nao herda de httpx.HTTPError (verificado em 0.28.1) — sem
    a captura extra, um TICKIO_BASE_URL com porta invalida escapava do
    `except httpx.HTTPError` como traceback em vez de erro de entrada.
    """
    fonte = TickioRest(base_url="http://h:porta", usuario="u", senha="p", sistema_id=1)

    with pytest.raises(ErroDeEntrada, match="TICKIO_BASE_URL"):
        fonte.fetch("13.34.0")


def test_base_url_malformada_ao_buscar_chamados_vira_errodeentrada_nao_invalidurl():
    """Mesmo defeito no segundo site (busca de chamados, depois de autenticado)."""
    fonte = TickioRest(base_url="http://h:porta", usuario="u", senha="p", sistema_id=1)
    fonte._access = "token-ja-obtido"  # pula _autenticar, exercita o GET de chamados

    with pytest.raises(ErroDeEntrada, match="TICKIO_BASE_URL"):
        fonte.fetch("13.34.0")
