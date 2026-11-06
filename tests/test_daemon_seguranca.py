import asyncio
from http import HTTPMethod, HTTPStatus

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from motor.daemon.seguranca import proteger

PORTA = 8765
OUTRA_PORTA = PORTA + 1
ORIGEM_ESTRANHA = "http://evil.com"
ORIGENS_ACEITAS = [f"http://127.0.0.1:{PORTA}", f"http://localhost:{PORTA}"]


@pytest.fixture
def cliente() -> TestClient:
    app = FastAPI()

    @app.get("/x")
    def ler() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/x")
    def mutar() -> dict[str, bool]:
        return {"ok": True}

    proteger(app, PORTA)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORTA}")


def test_host_estranho_e_recusado(cliente: TestClient) -> None:
    resposta = cliente.get("/x", headers={"host": "evil.com"})
    assert resposta.status_code == HTTPStatus.FORBIDDEN
    assert resposta.json()["tipo"] == "recusa"


@pytest.mark.parametrize("origem", ORIGENS_ACEITAS)
def test_localhost_e_127_sao_aceitos(cliente: TestClient, origem: str) -> None:
    host = origem.removeprefix("http://")
    assert cliente.get("/x", headers={"host": host}).status_code == HTTPStatus.OK


def test_post_com_origin_de_outro_site_e_recusado(cliente: TestClient) -> None:
    resposta = cliente.post("/x", headers={"origin": "http://evil.com"})
    assert resposta.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize("headers", [{}, *({"origin": o} for o in ORIGENS_ACEITAS)])
def test_post_sem_origin_ou_da_mesma_origem_passa(
    cliente: TestClient, headers: dict[str, str]
) -> None:
    assert cliente.post("/x", headers=headers).status_code == HTTPStatus.OK


@pytest.mark.parametrize(
    "host",
    [
        f"127.0.0.1:{PORTA}.evil.com",
        "127.0.0.1",
        f"127.0.0.1:{OUTRA_PORTA}",
    ],
)
def test_host_parecido_e_recusado(cliente: TestClient, host: str) -> None:
    resposta = cliente.get("/x", headers={"host": host})
    assert resposta.status_code == HTTPStatus.FORBIDDEN


def test_requisicao_sem_host_e_recusada(cliente: TestClient) -> None:
    mensagens: list[dict[str, object]] = []

    async def receber() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def enviar(mensagem: dict[str, object]) -> None:
        mensagens.append(mensagem)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": HTTPMethod.GET,
        "scheme": "http",
        "path": "/x",
        "raw_path": b"/x",
        "query_string": b"",
        "headers": [],
        "server": ("127.0.0.1", PORTA),
        "client": ("127.0.0.1", 1),
    }
    asyncio.run(cliente.app(scope, receber, enviar))  # type: ignore[arg-type]
    assert mensagens[0]["status"] == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize(
    "origem",
    ["null", f"http://127.0.0.1:{OUTRA_PORTA}", f"https://127.0.0.1:{PORTA}"],
)
def test_post_com_origin_parecida_e_recusado(cliente: TestClient, origem: str) -> None:
    resposta = cliente.post("/x", headers={"origin": origem})
    assert resposta.status_code == HTTPStatus.FORBIDDEN


def test_delete_com_origin_de_outro_site_e_recusado(cliente: TestClient) -> None:
    resposta = cliente.delete("/x", headers={"origin": ORIGEM_ESTRANHA})
    assert resposta.status_code == HTTPStatus.FORBIDDEN


def test_get_com_origin_de_outro_site_passa(cliente: TestClient) -> None:
    resposta = cliente.get("/x", headers={"origin": ORIGEM_ESTRANHA})
    assert resposta.status_code == HTTPStatus.OK
