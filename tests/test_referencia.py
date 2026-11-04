from __future__ import annotations

import pytest

from motor.domain.referencia import Referencia, resolver_referencia, validar_padrao
from motor.errors import ErroDeEntrada


@pytest.mark.parametrize("padrao", ["ch{id}", "{id}", "[{id}]"])
def test_validar_padrao_aceita_template_com_um_id(padrao):
    assert validar_padrao(padrao, "origem") == padrao


@pytest.mark.parametrize("valor", ["", "ch", "{id}{id}", 1])
def test_validar_padrao_recusa_citando_valor_e_origem(valor):
    with pytest.raises(ErroDeEntrada) as e:
        validar_padrao(valor, "/tmp/config.toml")
    # O texto é requisito: diz ao operador onde e o que corrigir.
    assert "/tmp/config.toml" in str(e.value)
    assert repr(valor) in str(e.value)


def test_config_vence_a_proposta_e_herda_o_alfabeto_dela():
    ref = resolver_referencia(Referencia("ch{id}", "0-9"), "x{id}", ())
    assert ref == Referencia("x{id}", "0-9")


def test_proposta_invalida_do_adapter_e_erro_de_entrada():
    with pytest.raises(ErroDeEntrada):
        resolver_referencia(Referencia("ch"), None, ())
