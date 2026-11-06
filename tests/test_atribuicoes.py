"""Politicas de atribuicao: de quais versoes vem as tarefas do alvo."""

import datetime

import pytest

from motor.atribuicoes import Composta, Exata, liberadas_apos_corte
from motor.domain.types import ContextoAtribuicao
from motor.plugins import carregar_plugin
from tests.versionamento import Escalonado

_ORDENAR = Escalonado().ordenar


def _quando(mes: int) -> datetime.datetime:
    return datetime.datetime(2026, mes, 1, tzinfo=datetime.UTC)


def _contexto(
    abertas: list[str],
    liberadas: dict[str, datetime.datetime] | None = None,
    piso: str | None = None,
) -> ContextoAtribuicao:
    return ContextoAtribuicao(
        ordenar=_ORDENAR,
        abertas=abertas,
        liberadas=liberadas or {},
        corte=_quando(3),
        piso=piso,
    )


@pytest.mark.parametrize("nome,classe", [("exata", Exata), ("composta", Composta)])
def test_politica_embutida_e_entry_point(nome, classe):
    assert carregar_plugin("monitor_versoes.atribuicoes", nome) is classe


# Cenario canonico da distribuicao (docs/decisoes/005-alvo-distribuicao-entre-versoes.md).
# Cada linha e um passo do fluxo real.
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
    (
        "14.0.1",
        ["13.33.1", "13.35.0", "14.0.1", "14.1.0"],
        ["13.33.1", "13.35.0", "14.0.1"],
    ),
    (
        "14.1.0",
        ["13.33.1", "13.35.0", "14.0.1", "14.1.0"],
        ["13.33.1", "13.35.0", "14.0.1", "14.1.0"],
    ),
]


@pytest.mark.parametrize("alvo,abertas,esperado", CENARIO)
def test_composta_cenario_canonico(alvo, abertas, esperado):
    assert Composta().fontes(alvo, _contexto(abertas)) == esperado


def test_composta_inclui_o_proprio_alvo_quando_ainda_nao_tem_branch():
    # `criar` chama antes da branch existir
    assert Composta().fontes("14.1.0", _contexto(["13.33.1", "14.0.0"])) == [
        "13.33.1",
        "14.0.0",
        "14.1.0",
    ]


def test_composta_respeita_o_piso_do_repo():
    # 13.1.0 do vb2web: branch legada sem tag que o rastreador nao conhece
    contexto = _contexto(["13.1.0", "15.2.0"], piso="14.0.0")
    assert Composta().fontes("15.2.0", contexto) == ["15.2.0"]


def test_composta_sem_piso_nao_corta_nada():
    assert Composta().fontes("13.34.0", _contexto(["5.2.0", "13.0.0", "13.34.0"])) == [
        "5.2.0",
        "13.0.0",
        "13.34.0",
    ]


def test_composta_traz_liberada_posterior_ao_corte():
    contexto = _contexto(["13.33.1", "15.0.0"], liberadas={"14.6.0": _quando(5)})

    assert Composta().fontes("15.0.0", contexto) == ["13.33.1", "14.6.0", "15.0.0"]


def test_liberadas_apos_corte_entra_so_com_liberacao_posterior_ao_corte():
    """As tres faixas tem de conviver num teste: a premissa velha
    (docs/decisoes/005-alvo-distribuicao-entre-versoes.md) era que
    liberada nunca conta, e ela erra so numa das faixas. Separadas, o caso que
    volta a passar sozinho e justamente o que reintroduz o bug.
    """
    datas = {
        "13.34.0": _quando(1),  # liberada antes do corte: conteudo veio pela base
        "14.6.0": _quando(5),  # liberada depois do corte: entrega que o alvo nao herdou
        "14.5.0": _quando(3),  # tag exatamente no corte: ja e ancestral do alvo
    }

    assert liberadas_apos_corte(_ORDENAR, "15.0.0", datas, _quando(3)) == ["14.6.0"]


def test_liberadas_apos_corte_ignora_liberada_maior_que_o_alvo():
    datas = {"14.6.0": _quando(5), "15.1.0": _quando(6)}

    assert liberadas_apos_corte(_ORDENAR, "15.0.0", datas, _quando(3)) == ["14.6.0"]


def test_liberadas_apos_corte_ordena_pelo_esquema_nao_por_texto():
    datas = {"13.10.0": _quando(5), "13.9.0": _quando(5)}

    assert liberadas_apos_corte(_ORDENAR, "14.0.0", datas, _quando(3)) == [
        "13.9.0",
        "13.10.0",
    ]


def test_exata_ignora_aberta_menor_e_liberada_apos_corte():
    contexto = _contexto(["13.33.1", "15.0.0"], liberadas={"14.6.0": _quando(5)})

    assert Exata().fontes("15.0.0", contexto) == ["15.0.0"]


def test_exata_alvo_abaixo_do_piso_nao_tem_fonte():
    assert Exata().fontes("13.1.0", _contexto(["13.1.0"], piso="14.0.0")) == []
