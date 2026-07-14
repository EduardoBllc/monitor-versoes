"""Porte de internal/domain/version.go."""

from __future__ import annotations

from motor.domain.types import VersionType
from motor.errors import MotorError


def _parse_versao(numero: str) -> tuple[int, int, int]:
    partes = numero.split(".")
    if len(partes) != 3:
        raise MotorError(f'versao "{numero}": esperado formato X.Y.Z')
    nums = []
    for p in partes:
        try:
            n = int(p)
        except ValueError as e:
            raise MotorError(f'versao "{numero}": componente "{p}" invalido') from e
        if n < 0:
            raise MotorError(f'versao "{numero}": componente "{p}" invalido')
        nums.append(n)
    return nums[0], nums[1], nums[2]


def inferir_tipo(numero: str) -> VersionType:
    _, y, z = _parse_versao(numero)
    if y == 0 and z == 0:
        return VersionType.FECHADA
    if z == 0:
        return VersionType.AJUSTADA
    return VersionType.CLIENTE


def inferir_base(numero: str, versoes_existentes: list[str]) -> str:
    """Resolve a base de uma versao (§7). versoes_existentes e a lista de
    branches de versao ja existentes (ex.: vindas de GitRepo.list_version_branches).
    """
    x, y, z = _parse_versao(numero)
    if y == 0 and z == 0:
        return "master"
    if z == 0:
        for cand in range(y - 1, -1, -1):
            candidato = f"{x}.{cand}.0"
            if candidato in versoes_existentes:
                return candidato
        raise MotorError(f"nenhuma base X.Y.0 encontrada abaixo de {numero}")
    candidato = f"{x}.{y}.{z - 1}"
    if candidato in versoes_existentes:
        return candidato
    return f"{x}.{y}.0"
