"""Proteção do daemon local contra DNS rebinding (Host) e requisições de outros sites (Origin)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from http import HTTPMethod, HTTPStatus

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from motor.daemon.erros import ErroApi, TipoErro

_HOSTS = ("127.0.0.1", "localhost")
_METODOS_SEGUROS = frozenset({HTTPMethod.GET, HTTPMethod.HEAD})


def proteger(app: FastAPI, porta: int) -> None:
    hosts = {f"{h}:{porta}" for h in _HOSTS}
    origens = {f"http://{h}" for h in hosts}

    def recusar(mensagem: str) -> Response:
        corpo = asdict(ErroApi(TipoErro.RECUSA, mensagem))
        return JSONResponse(corpo, status_code=HTTPStatus.FORBIDDEN)

    @app.middleware("http")
    async def checar(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.headers.get("host") not in hosts:
            return recusar(
                "Host não permitido: o daemon só atende 127.0.0.1 e localhost"
            )
        origem = request.headers.get("origin")
        if (
            request.method not in _METODOS_SEGUROS
            and origem is not None
            and origem not in origens
        ):
            return recusar(
                "Origem não permitida: requisição de outro site foi recusada"
            )
        return await call_next(request)
