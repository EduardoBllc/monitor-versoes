"""Números `X.Y.Z`, comuns aos esquemas embutidos."""

from __future__ import annotations

from motor.errors import ErroDeEntrada


def parse(numero: str) -> tuple[int, int, int]:
    partes = numero.split(".")
    if len(partes) != 3:  # noqa: PLR2004 - X.Y.Z
        raise ErroDeEntrada(f'versao "{numero}": esperado formato X.Y.Z')
    nums = []
    for p in partes:
        try:
            n = int(p)
        except ValueError as e:
            raise ErroDeEntrada(f'versao "{numero}": componente "{p}" invalido') from e
        if n < 0:
            raise ErroDeEntrada(f'versao "{numero}": componente "{p}" invalido')
        nums.append(n)
    return nums[0], nums[1], nums[2]


def validar(numero: str) -> str:
    aparado = numero.strip()
    parse(aparado)
    return aparado


def ordenar(numeros: list[str]) -> list[str]:
    """Ordem numérica. Existe porque a textual erra em '13.9.0' vs '13.10.0' — o
    único bug de ordenação que não aparece nos testes de fixture pequeno e
    aparece em produção no mês seguinte.
    """
    return sorted(numeros, key=parse)


def sugerir(existentes: list[str]) -> list[str]:
    """Os três próximos números a partir da mais alta que existe, um por
    componente.

    Ordem de uso, não de magnitude: o patch é o caso do dia a dia, o major o
    corte raro. Lista vazia (repo sem nenhuma versão) não sugere nada — a
    primeira versão de um repo é digitada, porque não há de onde derivar.
    """
    if not existentes:
        return []
    x, y, z = max(parse(numero) for numero in existentes)
    return [f"{x}.{y}.{z + 1}", f"{x}.{y + 1}.0", f"{x + 1}.0.0"]
