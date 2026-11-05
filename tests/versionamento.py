"""Esquema escalonado dos testes de engine.

E fixture: a regra de base em degraus (fechada `X.0.0`, ajustada `X.Y.0`,
cliente `X.Y.Z`) sob nome neutro, para os testes de engine anteriores ao
esquema plugavel seguirem sem mudar o que verificam. A regra de producao mora
no pacote do esquema (#137).
"""

from __future__ import annotations

import datetime

from motor.atribuicoes import Composta
from motor.errors import NaoEncontrado
from motor.esquemas import _xyz
from motor.ports import GitRepo
from motor.services.versionamento import FonteVersionamento, Versionamento


class Escalonado:
    """`X.0.0` fechada, `X.Y.0` ajustada, `X.Y.Z` cliente.

    Principal `master`, branch da versao com o numero puro e liberacao pela tag
    homonima (o padrao do nucleo).
    """

    branch_versao: str | None = "{versao}"
    branch_principal: str | None = "master"

    def validar(self, numero: str, /) -> str:
        return _xyz.validar(numero)

    def ordenar(self, numeros: list[str], /) -> list[str]:
        return _xyz.ordenar(numeros)

    def base(self, numero: str, existentes: list[str], principal: str, /) -> str:
        """A fechada sai da principal; a ajustada da ajustada anterior que
        existir; a cliente da cliente anterior, senao da sua `X.Y.0`."""
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


_ESCALONADO_COMPOSTA = Versionamento(
    esquema=Escalonado(),
    politica=Composta(),
    branch_versao="{versao}",
    principal="master",
)


def _escalonado_composta() -> Versionamento:
    return _ESCALONADO_COMPOSTA


ESCALONADO_COMPOSTA: FonteVersionamento = _escalonado_composta
