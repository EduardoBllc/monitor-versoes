"""Tempo por etapa do `verificar`, logado em DEBUG."""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Iterator
from enum import StrEnum

logger = logging.getLogger(__name__)


class Etapa(StrEnum):
    WORKTREE = "worktree"
    BASE = "base"
    TAREFAS = "tarefas"
    VARREDURA_PRS = "varredura de PRs"
    COMMITS_PRS = "commits das PRs"
    ORACULO = "oráculo de presença"
    CONFLITOS = "simulação de conflitos"
    GRAVACAO = "gravação"


@contextlib.contextmanager
def cronometrar(etapa: Etapa) -> Iterator[None]:
    inicio = time.monotonic()
    try:
        yield
    finally:
        logger.debug("etapa %s: %.3fs", etapa, time.monotonic() - inicio)
