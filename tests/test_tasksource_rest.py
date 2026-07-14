"""Transcrição de internal/adapters/tasksource/rest_test.go.

Usa httpx.MockTransport em vez de um servidor real (httptest.Server).
"""

from __future__ import annotations

import httpx
import pytest

from motor.adapters.tasksource.rest import CF_NUMERO_CHAMADO, ClickUpRest
from motor.errors import MotorError


def test_clickup_rest_fetch():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "tok123"
        return httpx.Response(
            200,
            json={
                "tasks": [
                    {
                        "id": "1",
                        "name": "Logs pedidos ecommerce",
                        "custom_id": "VB-2354",
                        "custom_fields": [
                            {"id": CF_NUMERO_CHAMADO, "value": "255514"},
                        ],
                    }
                ]
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://testserver"
    )
    fonte = ClickUpRest(
        base_url="http://testserver",
        token="tok123",
        client=client,
    )
    tasks = fonte.fetch("13.7.0")

    assert len(tasks) == 1
    assert tasks[0].chamado == "255514"
    assert tasks[0].task == "VB-2354"


def test_clickup_rest_erro_http():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://testserver"
    )
    fonte = ClickUpRest(
        base_url="http://testserver", token="invalido", client=client
    )
    with pytest.raises(MotorError):
        fonte.fetch("13.7.0")
