"""Double em memória de TaskSource, para testes de services/engine.

Transcrição 1-pra-1 de internal/adapters/tasksource/fake.go.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from motor.domain.types import TaskTarget


@dataclass
class FakeTaskSource:
    tasks: dict[str, list[TaskTarget]] = field(default_factory=dict)
    err: Exception | None = None

    def fetch(self, versao: str) -> list[TaskTarget]:
        if self.err is not None:
            raise self.err
        return self.tasks.get(versao, [])
