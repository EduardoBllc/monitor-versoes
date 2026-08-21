"""Double em memoria de TaskSource, para testes de services/engine."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeTaskSource:
    # versao -> chamados marcados para ela
    chamados: dict[str, list[str]] = field(default_factory=dict)
    err: Exception | None = None

    def fetch(self, versao: str, /) -> list[str]:
        if self.err is not None:
            raise self.err
        return list(self.chamados.get(versao, []))
