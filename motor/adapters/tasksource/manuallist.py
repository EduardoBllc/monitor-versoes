"""Transcrição 1-pra-1 de internal/adapters/tasksource/manuallist.go.

ManualList lê um arquivo texto com uma task por linha:
"chamado;VB-xxxx;titulo". Fallback sempre disponível quando a API do
ClickUp não está acessível (§4).
"""

from __future__ import annotations

from dataclasses import dataclass

from motor.domain.types import TaskTarget
from motor.errors import MotorError


@dataclass
class ManualList:
    caminho: str

    def fetch(self, versao: str) -> list[TaskTarget]:
        try:
            with open(self.caminho, encoding="utf-8") as f:
                linhas = f.read().splitlines()
        except OSError as e:
            raise MotorError(f"abrindo lista manual {self.caminho}: {e}") from e

        tasks: list[TaskTarget] = []
        for linha in linhas:
            linha = linha.strip()
            if linha == "" or linha.startswith("#"):
                continue
            campos = linha.split(";", 2)
            if len(campos) < 2:
                raise MotorError(
                    f"linha invalida em {self.caminho}: {linha!r} "
                    "(esperado chamado;VB-xxxx;titulo)"
                )
            titulo = campos[2] if len(campos) == 3 else ""
            tasks.append(TaskTarget(chamado=campos[0], task=campos[1], titulo=titulo))
        return tasks
