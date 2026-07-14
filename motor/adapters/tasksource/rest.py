"""Transcrição 1-pra-1 de internal/adapters/tasksource/rest.go.

ClickUpRest usa a API "Filter Team Tasks" (GET /team/{team_id}/task) com
filtro por custom_fields — único adapter determinístico (§4). BaseURL
configurável pra apontar num transporte mockado nos testes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from motor.domain.types import TaskTarget
from motor.errors import MotorError

CAMPO_VERSAO_DESTINO = "de0124a4-a15d-401e-ab48-417803082562"

_BASE_URL_PADRAO = "https://api.clickup.com/api/v2"


@dataclass
class ClickUpRest:
    base_url: str = ""
    team_id: str = ""
    token: str = ""
    campo_chamado_id: str = ""  # custom field "Numero do chamado" - confirmar ID real no ClickUp
    client: httpx.Client | None = None

    def fetch(self, versao: str) -> list[TaskTarget]:
        client = self.client if self.client is not None else httpx.Client()
        base_url = self.base_url if self.base_url else _BASE_URL_PADRAO

        filtro = json.dumps(
            [{"field_id": CAMPO_VERSAO_DESTINO, "operator": "=", "value": versao}]
        )
        url = f"{base_url}/team/{self.team_id}/task"

        try:
            resp = client.get(
                url,
                params={"custom_fields": filtro},
                headers={"Authorization": self.token},
            )
        except httpx.HTTPError as e:
            raise MotorError(f"chamando ClickUp: {e}") from e

        if resp.status_code != 200:
            raise MotorError(f"ClickUp respondeu {resp.status_code}")

        try:
            corpo = resp.json()
        except ValueError as e:
            raise MotorError(f"decodificando resposta do ClickUp: {e}") from e

        tasks: list[TaskTarget] = []
        for t in corpo.get("tasks", []):
            tasks.append(
                TaskTarget(
                    chamado=_extrair_campo_chamado(
                        t.get("custom_fields", []), self.campo_chamado_id
                    ),
                    task=t.get("custom_id", ""),
                    titulo=t.get("name", ""),
                )
            )
        return tasks


def _extrair_campo_chamado(campos: list[dict], campo_id: str) -> str:
    for c in campos:
        if c.get("id") == campo_id:
            valor = c.get("value")
            if isinstance(valor, str):
                return valor
    return ""
