"""Double em memória de CommitSource, para testes de services/engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from motor.domain.types import CommitRef


@dataclass
class FakeCommitSource:
    # chamado -> commits que esta fonte "acha".
    por_chamado: dict[str, list[CommitRef]] = field(default_factory=dict)
    err: Exception | None = None

    def resolve(self, chamados: list[str], /) -> dict[str, list[CommitRef]]:
        if self.err is not None:
            raise self.err
        return {
            c: self.por_chamado[c] for c in chamados if self.por_chamado.get(c)
        }
