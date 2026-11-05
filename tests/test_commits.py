from __future__ import annotations

import datetime

import pytest

from motor.domain.commits import extrair_chamado, match_exato, ordenar_por_grafo
from motor.domain.referencia import Referencia
from motor.domain.types import CommitRef
from tests.fontes_falsas import REFERENCIA_CH

CH = REFERENCIA_CH


def test_extrair_chamado():
    assert extrair_chamado("ch123456 corrige calculo de frete", CH) == "123456"
    assert extrair_chamado("sem identificador nenhum", CH) is None


def test_match_exato_respeita_word_boundary():
    candidatos = [
        CommitRef(hash_origem="a", msg="ch5514 alfa"),
        CommitRef(hash_origem="b", msg="ch255514 beta"),
    ]
    achados = match_exato(candidatos, "5514", CH)
    assert [c.hash_origem for c in achados] == ["a"]

    # a colisao que o \b realmente evita e de prefixo: "123" nao pode casar
    # dentro de "1234" (sem boundary, "ch123" e substring valida de "ch1234").
    candidatos_prefixo = [
        CommitRef(hash_origem="c", msg="ch123 fix"),
        CommitRef(hash_origem="d", msg="ch1234 other fix"),
    ]
    achados_prefixo = match_exato(candidatos_prefixo, "123", CH)
    assert [c.hash_origem for c in achados_prefixo] == ["c"]


def test_match_exato_sem_chamado_nao_casa_nada():
    candidatos = [CommitRef(hash_origem="a", msg="ch5514 alfa")]
    assert match_exato(candidatos, "", CH) == []


def test_match_exato_ignora_caixa_do_prefixo():
    # "CH254473." existe no historico real tanto quanto "ch254473." — o prefixo
    # e digitado a mao. O `-i` de search_commits traz o candidato; perde-lo aqui
    # so mudaria o lugar do falso-negativo.
    candidatos = [
        CommitRef(hash_origem="a", msg="CH254473. mais tempos para sessoes"),
        CommitRef(hash_origem="b", msg="Ch2544731 outro chamado"),
    ]
    assert [c.hash_origem for c in match_exato(candidatos, "254473", CH)] == ["a"]


def test_extrair_chamado_ignora_caixa():
    assert extrair_chamado("CH254473 - ajuste", CH) == "254473"


def test_ordenar_por_grafo_ignora_data_e_poe_desconhecido_no_fim():
    d = datetime.datetime(2026, 1, 1)
    commits = [
        CommitRef(
            hash_origem="sumido-novo", commit_date=d + datetime.timedelta(days=3)
        ),
        CommitRef(hash_origem="filho", commit_date=d),
        CommitRef(hash_origem="sumido-velho", commit_date=d),
        CommitRef(hash_origem="pai", commit_date=d + datetime.timedelta(days=5)),
    ]
    ordem = ordenar_por_grafo(commits, ["pai", "filho"])
    # desconhecidos na ordem de entrada: "sumido-novo" veio antes, fica antes.
    assert [c.hash_origem for c in ordem] == [
        "pai",
        "filho",
        "sumido-novo",
        "sumido-velho",
    ]


# -- referencia configuravel: a tabela da fronteira (006) ---------------------

PADRAO = Referencia("{id}")
COLCHETES = Referencia("[{id}]")


@pytest.mark.parametrize(
    ("ref", "mensagem", "esperado"),
    [
        (CH, "ch254473-fix corrige", "254473"),
        (CH, "CH254473 x", "254473"),
        (PADRAO, "PAY-123 corrige", "PAY-123"),
        (COLCHETES, "[PAY-12] x", "PAY-12"),
        (COLCHETES, "a[PAY-12] x", "PAY-12"),
        # Lista manual com `ch{id}`: o alfabeto default nao para no `-`.
        (Referencia("ch{id}"), "ch254473-fix corrige", "254473-fix"),
    ],
)
def test_extrair_chamado_pela_referencia(ref, mensagem, esperado):
    assert extrair_chamado(mensagem, ref) == esperado


@pytest.mark.parametrize(
    ("ref", "chamado", "mensagem", "casa"),
    [
        (CH, "5514", "ch255514 x", False),
        (CH, "254473", "CH254473 x", True),
        (PADRAO, "PAY-12", "PAY-123 x", False),
        (PADRAO, "PAY-12", "PAY-12-x", False),
        (PADRAO, "PAY-12", "pay-12 x", True),
        (COLCHETES, "PAY-12", "[PAY-12] x", True),
        (COLCHETES, "PAY-12", "a[PAY-12] x", True),
    ],
)
def test_match_exato_pela_referencia(ref, chamado, mensagem, casa):
    candidatos = [CommitRef(hash_origem="a", msg=mensagem)]
    assert bool(match_exato(candidatos, chamado, ref)) is casa
