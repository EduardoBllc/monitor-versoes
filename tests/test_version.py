"""Porte de internal/domain/version_test.go."""

import pytest

from motor.domain.types import VersionType
from motor.domain.version import (
    chave,
    fontes_de_alvo,
    inferir_base,
    inferir_tipo,
    versoes_abertas,
    worktrees_a_remover,
)
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


# --- worktrees_a_remover: politica do GC de worktrees ---
#
# `existentes` sao as worktrees de versao em disco; `mru` e a lista de uso
# recente (mais recente primeiro) lida do arquivo local pelo adapter. A ordem
# aqui e a unica coisa que decide o que morre, entao cada caso abaixo fixa uma
# regra dela.


def test_worktrees_a_remover_mru_manda_sobre_semver():
    # 12.4.0 e a mais antiga por semver, mas foi usada por ultimo: fica.
    remover = worktrees_a_remover(
        ["13.9.0", "13.10.0", "12.4.0"],
        mru=["12.4.0", "13.9.0"],
        manter=2,
        atual="12.4.0",
    )
    assert remover == ["13.10.0"]


def test_worktrees_a_remover_nao_registrada_cai_depois_por_semver_desc():
    # 13.1.0 esta no mru; 13.2.0 e 13.3.0 nao. As desconhecidas entram atras,
    # entre si da mais nova para a mais velha — 13.2.0 e a primeira a sair.
    remover = worktrees_a_remover(
        ["13.1.0", "13.2.0", "13.3.0"], mru=["13.1.0"], manter=2, atual=""
    )
    assert remover == ["13.2.0"]


def test_worktrees_a_remover_preserva_atual_mesmo_sendo_a_mais_antiga():
    # Sem mru nenhum (arquivo ausente): cai em semver desc, mas `atual` e
    # intocavel — a operacao em curso acabou de usar essa worktree.
    remover = worktrees_a_remover(
        ["12.4.0", "14.0.0", "14.1.0"], mru=[], manter=1, atual="12.4.0"
    )
    assert remover == ["14.1.0", "14.0.0"]


def test_worktrees_a_remover_manter_zero_remove_tudo_inclusive_atual():
    # manter=0 e o comportamento antigo do motor: worktree nao sobrevive ao run.
    remover = worktrees_a_remover(
        ["13.1.0", "13.2.0"], mru=["13.2.0"], manter=0, atual="13.2.0"
    )
    assert remover == ["13.2.0", "13.1.0"]


def test_worktrees_a_remover_ignora_mru_de_worktree_que_nao_existe_mais():
    # O arquivo de mru guarda historico; worktree removida continua listada la.
    remover = worktrees_a_remover(
        ["13.1.0"], mru=["13.9.0", "13.1.0"], manter=1, atual=""
    )
    assert remover == []


def test_worktrees_a_remover_nada_quando_manter_cobre_todas():
    remover = worktrees_a_remover(
        ["13.1.0", "13.2.0"], mru=["13.1.0"], manter=5, atual="13.1.0"
    )
    assert remover == []
