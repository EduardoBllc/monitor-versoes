"""Disparo das inscrições vencidas pelo daemon."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from functools import partial

from motor.inscricoes import caminho_arquivo, disparar_subprocesso, rodar
from motor.montagem import montar_notificador

log = logging.getLogger(__name__)

INTERVALO_DISPARO_S = 60


def laco(
    parar: threading.Event, rodada: Callable[[], None], intervalo_s: float
) -> None:
    """Roda `rodada` na entrada e a cada `intervalo_s`, até `parar`."""
    while not parar.is_set():
        try:
            rodada()
        except Exception:
            log.exception("rodada de disparo das inscrições falhou")
        parar.wait(intervalo_s)


def rodada(env: Mapping[str, str]) -> None:
    rodar(
        caminho_arquivo(),
        datetime.now(UTC),
        partial(disparar_subprocesso, env=env),
        montar_notificador(),
    )
