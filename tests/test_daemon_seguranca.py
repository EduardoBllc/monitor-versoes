from http import HTTPStatus

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from motor.daemon.seguranca import proteger

PORTA = 8765
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
