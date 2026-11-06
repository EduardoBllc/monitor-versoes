"""Esquemas embutidos: validacao, ordem, base, tipo e sugestoes."""

import pytest

from motor.errors import ErroDeEntrada
from motor.esquemas.semver import Semver
from motor.plugins import carregar_plugin
from motor.ports import EsquemaVersao


@pytest.mark.parametrize("nome,classe", [("semver", Semver)])
def test_esquema_embutido_e_entry_point(nome, classe):
    assert carregar_plugin("monitor_versoes.esquemas", nome) is classe


@pytest.mark.parametrize("esquema", [Semver()])
def test_numero_fora_de_x_y_z_e_erro_de_entrada(esquema: EsquemaVersao):
    with pytest.raises(ErroDeEntrada):
        esquema.validar("13.7")


@pytest.mark.parametrize(
    "numero,existentes,base",
    [
        ("2.0.0", ["1.9.0"], "main"),
        # a X.Y.0 nao desce da X.(Y-1).0: sai da principal
        ("2.3.0", ["2.2.0"], "main"),
        ("2.3.2", ["2.3.1"], "2.3.1"),
        ("2.3.2", [], "2.3.0"),
    ],
)
def test_semver_base(numero, existentes, base):
    assert Semver().base(numero, existentes, "main") == base


@pytest.mark.parametrize("esquema", [Semver()])
def test_ordenar_e_numerico_nao_textual(esquema: EsquemaVersao):
    # ordem lexicografica erraria aqui: "13.9.0" > "13.10.0" como texto
    assert esquema.ordenar(
        ["14.1.0", "13.10.0", "14.0.1", "13.9.0", "13.33.1", "14.0.0"]
    ) == ["13.9.0", "13.10.0", "13.33.1", "14.0.0", "14.0.1", "14.1.0"]


@pytest.mark.parametrize("esquema", [Semver()])
def test_sugerir_parte_da_maior_existente(esquema: EsquemaVersao):
    assert esquema.sugerir(["1.2.3", "1.10.0"]) == ["1.10.1", "1.11.0", "2.0.0"]
    assert esquema.sugerir([]) == []
