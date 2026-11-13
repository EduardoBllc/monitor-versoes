"""Fontes de tarefas e hosts de PR falsos, carregados pela config como `modulo:Classe`.

Servem aos testes da montagem, da CLI, da TUI e do diagnostico: o nucleo nao
traz fonte de tarefas por entry point, e cada teste escolhe a sua pelo
`[tarefas] fonte` do `config.toml` central.
"""

from __future__ import annotations

import datetime
import os
import sys
from collections.abc import Mapping
from typing import ClassVar

from motor.domain.referencia import Referencia
from motor.domain.types import CommitRef, PrIndex
from motor.errors import ErroDeEntrada

#: Referencia de teste: o commit cita `ch<digitos>`.
REFERENCIA_CH = Referencia("ch{id}", "0-9")


def _chamados(tarefas: Mapping[str, object]) -> list[str]:
    bruto = tarefas.get("chamados", [])
    assert isinstance(bruto, list)
    return [str(c) for c in bruto]


class FonteFixa:
    """Devolve o `[tarefas] chamados` da config; guarda os kwargs recebidos e
    as versoes buscadas."""

    referencia: ClassVar[Referencia] = REFERENCIA_CH
    recebidos: ClassVar[list[dict[str, object]]] = []
    buscadas: ClassVar[list[str]] = []

    def __init__(self, **kwargs: object) -> None:
        FonteFixa.recebidos.append(dict(kwargs))
        tarefas = kwargs["tarefas"]
        assert isinstance(tarefas, Mapping)
        self.tarefas: Mapping[str, object] = tarefas

    def fetch(self, versao: str, /) -> list[str]:
        FonteFixa.buscadas.append(versao)
        return _chamados(self.tarefas)


class FonteComCredencial:
    """Exige `FONTE_FALSA_TOKEN` na busca e oferece `verificar_credenciais`."""

    referencia: ClassVar[Referencia] = REFERENCIA_CH

    def __init__(
        self, *, tarefas: Mapping[str, object], arquivos: tuple[str, ...]
    ) -> None:
        self.tarefas = tarefas

    def fetch(self, versao: str, /) -> list[str]:
        if not os.environ.get("FONTE_FALSA_TOKEN", ""):
            raise ErroDeEntrada("faltando no .env: FONTE_FALSA_TOKEN")
        return _chamados(self.tarefas)

    def verificar_credenciais(self) -> None:
        if os.environ.get("FONTE_FALSA_TOKEN", "") != "certo":
            raise ErroDeEntrada("credencial recusada")


class FonteConstrutorQuebra:
    """Construtor que recusa a config com erro do operador."""

    def __init__(self, **kwargs: object) -> None:
        raise ErroDeEntrada("construtor quebrou")

    def fetch(self, versao: str, /) -> list[str]:
        raise AssertionError("nunca instanciada")


class FonteConstrutorComBug:
    """Construtor com bug: levanta algo que nao e `MotorError`."""

    def __init__(self, **kwargs: object) -> None:
        raise RuntimeError("bug")

    def fetch(self, versao: str, /) -> list[str]:
        raise AssertionError("nunca instanciada")


# -- hosts de PR (`[prs] fonte`) ------------------------------------------------


class HostFalso:
    """Host de PR sem PR nenhuma; guarda os kwargs recebidos. Exige
    `HOST_FALSO_TOKEN` na busca e oferece `verificar_credenciais`."""

    recebidos: ClassVar[list[dict[str, object]]] = []

    def __init__(self, **kwargs: object) -> None:
        HostFalso.recebidos.append(dict(kwargs))

    def prs_mergeadas(self, desde: datetime.datetime | None, /) -> list[PrIndex]:
        if not os.environ.get("HOST_FALSO_TOKEN", ""):
            raise ErroDeEntrada("faltando no ambiente: HOST_FALSO_TOKEN")
        return []

    def commits_da_pr(self, pr_id: int, /) -> list[CommitRef]:
        return []

    def verificar_credenciais(self) -> None:
        if os.environ.get("HOST_FALSO_TOKEN", "") != "certo":
            raise ErroDeEntrada("credencial recusada")


class HostSaidaBinaria(HostFalso):
    """Host que escreve bytes que não são UTF-8 no stdout e no stderr ao verificar."""

    def verificar_credenciais(self) -> None:
        for fluxo in (sys.stdout, sys.stderr):
            fluxo.flush()
            fluxo.buffer.write(b"\xff\xfe\n")
            fluxo.buffer.flush()
        super().verificar_credenciais()


class HostSemVerificacao:
    """Host de PR que não oferece `verificar_credenciais`."""

    def __init__(self, **kwargs: object) -> None:
        pass

    def prs_mergeadas(self, desde: datetime.datetime | None, /) -> list[PrIndex]:
        return []

    def commits_da_pr(self, pr_id: int, /) -> list[CommitRef]:
        return []


class HostConstrutorComBug:
    """Construtor com bug: levanta algo que não é `MotorError`."""

    def __init__(self, **kwargs: object) -> None:
        raise RuntimeError("bug")
