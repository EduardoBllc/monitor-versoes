"""Porte de internal/domain/version_test.go."""

import pytest

from motor.domain.types import VersionType
from motor.domain.version import chave, fontes_de_alvo, inferir_base, inferir_tipo, versoes_abertas
from motor.errors import ErroDeEntrada


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
    with pytest.raises(ErroDeEntrada):
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


def test_chave_ordena_semver():
    assert chave("13.33.1") < chave("13.34.0")
    assert chave("13.34.0") < chave("14.0.0")
    assert chave("14.0.0") < chave("14.0.1")
    assert chave("14.0.1") < chave("14.1.0")
    # ordem lexicografica erraria aqui: "13.9.0" > "13.10.0" como texto
    assert chave("13.9.0") < chave("13.10.0")


def test_versoes_abertas_e_branch_sem_tag():
    todas = ["13.33.0", "13.33.1", "13.34.0", "14.0.0"]
    tags = ["13.33.0"]
    assert versoes_abertas(todas, tags) == ["13.33.1", "13.34.0", "14.0.0"]


def test_versoes_abertas_ordena_por_semver_nao_por_texto():
    todas = ["13.10.0", "13.9.0"]
    assert versoes_abertas(todas, []) == ["13.9.0", "13.10.0"]


def test_versoes_abertas_sem_nenhuma_aberta():
    assert versoes_abertas(["13.33.0"], ["13.33.0"]) == []


# Cenario canonico da spec §2. Cada linha e um passo do fluxo real.
CENARIO = [
    # (alvo, abertas, fontes esperadas)
    ("13.34.0", ["13.33.1", "13.34.0", "14.0.0"], ["13.33.1", "13.34.0"]),
    ("14.0.0", ["13.33.1", "13.34.0", "14.0.0"], ["13.33.1", "13.34.0", "14.0.0"]),
    ("13.33.1", ["13.33.1", "13.34.0", "14.0.0"], ["13.33.1"]),
    # passo 3: 13.34.0 liberada, 13.35.0 inaugurada
    ("13.35.0", ["13.33.1", "13.35.0", "14.0.0"], ["13.33.1", "13.35.0"]),
    ("14.0.0", ["13.33.1", "13.35.0", "14.0.0"], ["13.33.1", "13.35.0", "14.0.0"]),
    # passo 5: 14.0.0 liberada, 14.0.1 e 14.1.0 inauguradas
    ("13.35.0", ["13.33.1", "13.35.0", "14.0.1", "14.1.0"], ["13.33.1", "13.35.0"]),
    ("14.0.1", ["13.33.1", "13.35.0", "14.0.1", "14.1.0"],
     ["13.33.1", "13.35.0", "14.0.1"]),
    ("14.1.0", ["13.33.1", "13.35.0", "14.0.1", "14.1.0"],
     ["13.33.1", "13.35.0", "14.0.1", "14.1.0"]),
]


@pytest.mark.parametrize("alvo,abertas,esperado", CENARIO)
def test_fontes_de_alvo_cenario_canonico(alvo, abertas, esperado):
    assert fontes_de_alvo(alvo, abertas) == esperado


def test_fontes_de_alvo_inclui_o_proprio_alvo_quando_ainda_nao_tem_branch():
    # `criar` chama antes da branch existir: o alvo entra por uniao
    abertas = ["13.33.1", "14.0.0"]
    assert fontes_de_alvo("14.1.0", sorted({*abertas, "14.1.0"}, key=chave)) == [
        "13.33.1",
        "14.0.0",
        "14.1.0",
    ]


def test_fontes_de_alvo_ignora_versoes_anteriores_ao_corte():
    assert fontes_de_alvo("13.34.0", ["5.2.0", "13.0.0", "13.34.0"]) == [
        "13.0.0",
        "13.34.0",
    ]
