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
CF_NUMERO_CHAMADO = "a4211489-8198-44ed-8c0f-fd974c4755d5"
CF_CLIENTE = "f7c274bd-bcc8-4ff6-9ee3-49fdd6be37f5"
CF_DESCRICAO_ORIGINAL = "bd4074f8-07a2-4ad5-a496-411b7118b8da"
CF_MODO_PRIORIZACAO = "074ef45c-fad3-4442-a0a4-e186a44d65b3"
CF_ORIGEM_TAREFA = "804046f7-3f60-4de4-a563-e674127823b8"
CF_TIPO_TAREFA = "1ccdeac7-694e-41c6-91b1-6fa1e3266a4c"
CF_ID_TASK_ORIGEM = "b6242f67-a4ab-492e-bc27-60432289f33b"
CF_ID_DESENVOLVEDOR = "f0dfc7df-3c98-4c5e-acd0-8c2f78c47291"
CF_ID_REVISOR = "2f27aae7-28ee-4d68-8b1a-23be62c5f0da"
CF_ID_TESTADOR = "f94e783e-e2b2-4e7e-8835-9f4d80109603"

CLICKUP_TEAM_ID = "9011010669"

_BASE_URL_PADRAO = "https://api.clickup.com/api/v2"


@dataclass
class ClickUpRest:
    base_url: str = ""
    token: str = ""
    client: httpx.Client | None = None

    def fetch(self, versao: str) -> list[TaskTarget]:
        client = self.client if self.client is not None else httpx.Client()
        base_url = self.base_url if self.base_url else _BASE_URL_PADRAO

        filtro = json.dumps(
            [{"field_id": CAMPO_VERSAO_DESTINO, "operator": "=", "value": versao}]
        )
        url = f"{base_url}/team/{CLICKUP_TEAM_ID}/task"

        tasks: list[TaskTarget] = []
        page = 0

        while True:
            try:
                resp = client.get(
                    url,
                    params={"custom_fields": filtro, "page": page},
                    headers={"Authorization": self.token},
                )
            except httpx.HTTPError as e:
                raise MotorError(f"chamando ClickUp na pagina {page}: {e}") from e

            if resp.status_code != 200:
                raise MotorError(f"ClickUp respondeu {resp.status_code} na pagina {page}: {resp.text}")

            try:
                corpo = resp.json()
            except ValueError as e:
                raise MotorError(f"decodificando resposta do ClickUp na pagina {page}: {e}") from e

            for t in corpo.get("tasks", []):
                tasks.append(
                    TaskTarget(
                        chamado=_extrair_campo_chamado(
                            t.get("custom_fields", []), CF_NUMERO_CHAMADO
                        ),
                        task=t.get("custom_id") or "",
                        titulo=t.get("name") or "",
                    )
                )

            if corpo.get("last_page", True):
                break

            page += 1

        return tasks


def _extrair_campo_chamado(campos: list[dict], campo_id: str) -> str:
    for c in campos:
        if c.get("id") == campo_id:
            valor = c.get("value")
            if isinstance(valor, str):
                return valor
    return ""
