"""Porte de internal/domain/version_test.go."""

import pytest

from motor.domain.types import VersionType
from motor.domain.version import inferir_base, inferir_tipo
from motor.errors import MotorError


def test_inferir_tipo():
    casos = [
        ("14.0.0", VersionType.FECHADA),
        ("13.7.0", VersionType.AJUSTADA),
        ("13.7.2", VersionType.CLIENTE),
    ]
    for numero, quer in casos:
        got = inferir_tipo(numero)
        assert got == quer, f"inferir_tipo({numero!r}) = {got}, quer {quer}"


def test_inferir_tipo_invalido():
    with pytest.raises(MotorError):
        inferir_tipo("13.7")


def test_inferir_base_fechada():
    base = inferir_base("14.0.0", [])
    assert base == "master"


def test_inferir_base_ajustada():
    existentes = ["13.5.0", "13.6.0", "13.6.1"]
    base = inferir_base("13.7.0", existentes)
    assert base == "13.6.0"


def test_inferir_base_cliente():
    existentes = ["13.6.0", "13.6.1"]

    base = inferir_base("13.6.2", existentes)
    assert base == "13.6.1"

    base2 = inferir_base("13.6.5", existentes)  # 13.6.4 nao existe
    assert base2 == "13.6.0"
