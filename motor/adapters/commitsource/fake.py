"""Doubles em memória de CommitSource e HostPr, para testes."""

from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass, field

from motor.domain.types import CommitRef, PrIndex


@dataclass
class FakeCommitSource:
    # chamado -> commits que esta fonte "acha".
    por_chamado: dict[str, list[CommitRef]] = field(default_factory=dict)
    err: Exception | None = None

    def resolve(self, chamados: list[str], /) -> dict[str, list[CommitRef]]:
        if self.err is not None:
            raise self.err
        return {c: self.por_chamado[c] for c in chamados if self.por_chamado.get(c)}


@dataclass
class FakeHostPr:
    """Host de PR em memória.

    Devolve todas as `prs` em toda varredura, sem filtrar por `desde`: a porta
    permite reentregar PR conhecida, e o teste que quer ver o filtro olha
    `desde_pedidos`.
    """

    prs: list[PrIndex] = field(default_factory=list)
    commits: dict[int, list[CommitRef]] = field(default_factory=dict)
    err: Exception | None = None
    desde_pedidos: list[datetime.datetime | None] = field(default_factory=list)
    commits_pedidos: list[int] = field(default_factory=list)
    err_por_pr: dict[int, Exception] = field(default_factory=dict)
    fechamentos: int = 0
    _trava: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    def prs_mergeadas(self, desde: datetime.datetime | None, /) -> list[PrIndex]:
        self.desde_pedidos.append(desde)
        if self.err is not None:
            raise self.err
        return list(self.prs)

    def commits_da_pr(self, pr_id: int, /) -> list[CommitRef]:
        with self._trava:
            self.commits_pedidos.append(pr_id)
        if pr_id in self.err_por_pr:
            raise self.err_por_pr[pr_id]
        return list(self.commits.get(pr_id, []))

    def fechar(self) -> None:
        self.fechamentos += 1
