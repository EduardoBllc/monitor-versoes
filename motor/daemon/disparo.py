"""Disparo das inscrições vencidas pelo daemon."""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial

from fastapi import FastAPI

from motor.inscricoes import caminho_arquivo, disparar_subprocesso, rodar
from motor.montagem import montar_notificador

log = logging.getLogger(__name__)

INTERVALO_DISPARO_S = 60


def laco(
    parar: threading.Event, executar_rodada: Callable[[], None], intervalo_s: float
) -> None:
    """Roda `executar_rodada` na entrada e a cada `intervalo_s`, até `parar`."""
    while not parar.is_set():
        try:
            executar_rodada()
        except Exception:
            log.exception("rodada de disparo das inscrições falhou")
        parar.wait(intervalo_s)


def rodada(env: Mapping[str, str]) -> None:
    """Dispara as inscrições vencidas agora, cada filho com `env`."""
    rodar(
        caminho_arquivo(),
        datetime.now(UTC),
        partial(disparar_subprocesso, env=env),
        montar_notificador(),
    )


def ligar_disparo(app: FastAPI, rodada: Callable[[], None]) -> None:
    """Faz o app disparar as inscrições numa thread enquanto estiver de pé."""

    @asynccontextmanager
    async def ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
        parar = threading.Event()
        app.state.disparo = threading.Thread(
            target=laco, args=(parar, rodada, INTERVALO_DISPARO_S), daemon=True
        )
        app.state.disparo.start()
        try:
            yield
        finally:
            # Sem join: o filho em curso pode durar até o limite de 1h.
            parar.set()

    # Substitui o lifespan do app: se o criar_app ganhar um, encadear aqui.
    app.router.lifespan_context = ciclo_de_vida
