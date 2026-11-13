"""Domínio do conflito de 3 vias: estágios do índice e regra de marcador."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, StrEnum, auto

# 7 caracteres exatos, depois fim de linha ou espaço (como o git emite).
_MARCADOR = re.compile(r"(<{7}|\|{7}|={7}|>{7})( |\r?$)")


class _Marcador(StrEnum):
    INICIO = "<" * 7
    BASE = "|" * 7
    MEIO = "=" * 7
    FIM = ">" * 7


class _Secao(Enum):
    OURS = auto()
    BASE = auto()
    THEIRS = auto()


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


@dataclass(frozen=True)
class LadosDoBloco:
    """Os lados de um bloco aberto, cada um com a quebra final de cada linha."""

    ordem: int
    base: str | None
    ours: str
    theirs: str


@dataclass(frozen=True)
class PedidoAoProvedor:
    caminho: str
    mensagem: str
    chamado: str | None
    blocos: list[LadosDoBloco]


@dataclass(frozen=True)
class PropostaDeBloco:
    ordem: int
    conteudo: str
    justificativa: str


def blocos(texto: str) -> list[LadosDoBloco]:
    """Blocos abertos do texto, com a mesma regra do `blocos()` da web."""
    achados: list[LadosDoBloco] = []
    secoes: dict[_Secao, list[str]] | None = None
    secao = _Secao.OURS

    def juntar(s: _Secao) -> str | None:
        assert secoes is not None
        return None if s not in secoes else "".join(f"{x}\n" for x in secoes[s])

    for linha in texto.split("\n"):
        achou = _MARCADOR.match(linha)
        m = _Marcador(achou.group(1)) if achou else None
        if m is _Marcador.INICIO:
            secoes = {_Secao.OURS: []}
            secao = _Secao.OURS
        elif secoes is None:
            continue
        elif m is _Marcador.BASE and secao is _Secao.OURS:
            secao = _Secao.BASE
            secoes[secao] = []
        elif m is _Marcador.MEIO and secao is not _Secao.THEIRS:
            secao = _Secao.THEIRS
            secoes[secao] = []
        elif m is _Marcador.FIM and secao is _Secao.THEIRS:
            achados.append(
                LadosDoBloco(
                    ordem=len(achados),
                    base=juntar(_Secao.BASE),
                    ours=juntar(_Secao.OURS) or "",
                    theirs=juntar(_Secao.THEIRS) or "",
                )
            )
            secoes = None
        else:
            secoes[secao].append(linha)
    return achados
