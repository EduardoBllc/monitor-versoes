"""Esquema `semver`, o padrão quando a config não escolhe nenhum."""

from __future__ import annotations

import datetime

from motor.esquemas import _xyz
from motor.ports import GitRepo


class Semver:
    """`X.Y.Z` sem pré-release nem build.

    Base: `X.Y.0` sai da principal; `X.Y.Z` com `Z > 0` sai de `X.Y.(Z-1)` se
    existir, senão de `X.Y.0`. Sem tipo, sem nomes de branch e sem critério de
    liberação próprios: valem as camadas de config e do núcleo.
    """

    branch_versao: str | None = None
    branch_principal: str | None = None

    def validar(self, numero: str, /) -> str:
        return _xyz.validar(numero)

    def ordenar(self, numeros: list[str], /) -> list[str]:
        return _xyz.ordenar(numeros)

    def base(self, numero: str, existentes: list[str], principal: str, /) -> str:
        x, y, z = _xyz.parse(numero)
        if z == 0:
            return principal
        anterior = f"{x}.{y}.{z - 1}"
        if anterior in existentes:
            return anterior
        return f"{x}.{y}.0"

    def tipo(self, numero: str, /) -> str | None:
        return None

    def sugerir(self, existentes: list[str], /) -> list[str]:
        return _xyz.sugerir(existentes)

    def liberacoes(
        self, git: GitRepo, versoes: list[str], /
    ) -> dict[str, datetime.datetime] | None:
        return None
