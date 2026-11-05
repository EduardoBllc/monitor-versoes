"""Esquema `vendabem`: a regra de base da docs/decisoes/009-inferencia-de-base.md.

Mora aqui até a #117 levá-lo para o pacote `monitor-versoes-vendabem`. É o
único arquivo do núcleo que fala de `master` e dos tipos fechada, ajustada e
cliente.
"""

from __future__ import annotations

import datetime

from motor.errors import NaoEncontrado
from motor.esquemas import _xyz
from motor.ports import GitRepo


class VendaBem:
    """`X.0.0` fechada, `X.Y.0` ajustada, `X.Y.Z` cliente.

    Principal `master`, branch da versão com o número puro e liberação pela tag
    homônima (o padrão do núcleo).
    """

    branch_versao: str | None = "{versao}"
    branch_principal: str | None = "master"

    def validar(self, numero: str, /) -> str:
        return _xyz.validar(numero)

    def ordenar(self, numeros: list[str], /) -> list[str]:
        return _xyz.ordenar(numeros)

    def base(self, numero: str, existentes: list[str], principal: str, /) -> str:
        """A fechada sai da principal; a ajustada da ajustada anterior que
        existir; a cliente da cliente anterior, senão da sua `X.Y.0`."""
        x, y, z = _xyz.parse(numero)
        if y == 0 and z == 0:
            return principal
        if z == 0:
            for cand in range(y - 1, -1, -1):
                candidato = f"{x}.{cand}.0"
                if candidato in existentes:
                    return candidato
            raise NaoEncontrado(f"nenhuma base X.Y.0 encontrada abaixo de {numero}")
        candidato = f"{x}.{y}.{z - 1}"
        if candidato in existentes:
            return candidato
        return f"{x}.{y}.0"

    def tipo(self, numero: str, /) -> str | None:
        _, y, z = _xyz.parse(numero)
        if y == 0 and z == 0:
            return "fechada"
        if z == 0:
            return "ajustada"
        return "cliente"

    def sugerir(self, existentes: list[str], /) -> list[str]:
        return _xyz.sugerir(existentes)

    def liberacoes(
        self, git: GitRepo, versoes: list[str], /
    ) -> dict[str, datetime.datetime] | None:
        return None
