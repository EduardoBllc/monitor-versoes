"""Versionamento dos testes que verificam o comportamento da VendaBem: os
testes de engine anteriores ao esquema plugavel seguem nele sem mudar o que
verificam."""

from __future__ import annotations

from motor.atribuicoes import Composta
from motor.esquemas.vendabem import VendaBem
from motor.services.versionamento import FonteVersionamento, Versionamento

_VENDABEM_COMPOSTA = Versionamento(
    esquema=VendaBem(),
    politica=Composta(),
    branch_versao="{versao}",
    principal="master",
)


def _vendabem_composta() -> Versionamento:
    return _VENDABEM_COMPOSTA


VENDABEM_COMPOSTA: FonteVersionamento = _vendabem_composta
