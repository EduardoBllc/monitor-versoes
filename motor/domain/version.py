"""Compatibilidade: delega aos esquemas ate os consumidores migrarem."""

from __future__ import annotations

from motor.esquemas import _xyz
from motor.esquemas.vendabem import VendaBem


def inferir_base(numero: str, versoes_existentes: list[str]) -> str:
    """Base de uma versao (docs/decisoes/009-inferencia-de-base.md)."""
    return VendaBem().base(numero, versoes_existentes, "master")


def chave(numero: str) -> tuple[int, int, int]:
    return _xyz.parse(numero)


def validar_versao(valor: str) -> str:
    """Numero X.Y.Z, como o motor ordena versoes."""
    return _xyz.validar(valor)


def versoes_abertas(todas: list[str], tags: list[str]) -> list[str]:
    """Em construcao = existe como versao e nao tem tag homonima.

    `todas` vem de GitRepo.list_version_branches(), que ja devolve
    refs/heads/ UNIAO refs/tags/ filtrado por X.Y.Z; `tags` vem de
    list_version_tags(). A diferenca e o conjunto aberto.
    """
    return sorted(set(todas) - set(tags), key=chave)
