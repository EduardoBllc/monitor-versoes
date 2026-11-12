"""Domínio do conflito de 3 vias: estágios do índice e regra de marcador."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

# 7 caracteres exatos, depois fim de linha ou espaço (como o git emite).
_MARCADOR = re.compile(r"(<{7}|\|{7}|={7}|>{7})( |\r?$)")


class TipoArquivo(StrEnum):
    CONTEUDO = "conteudo"
    MODIFICADO_APAGADO = "modificado_apagado"
    OUTRO = "outro"


@dataclass(frozen=True)
class Estagios:
    base: str | None
    ours: str | None
    theirs: str | None
    disco: str | None
    binario: bool


def marcadores_restantes(texto: str) -> list[int]:
    return [n for n, linha in enumerate(texto.split("\n"), 1) if _MARCADOR.match(linha)]


def tipo_do_arquivo(e: Estagios) -> TipoArquivo:
    if e.binario:
        return TipoArquivo.OUTRO
    if e.ours is not None and e.theirs is not None:
        return TipoArquivo.CONTEUDO
    if (e.ours is None) != (e.theirs is None) and e.base is not None:
        return TipoArquivo.MODIFICADO_APAGADO
    return TipoArquivo.OUTRO
