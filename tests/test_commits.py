from __future__ import annotations

import datetime

from motor.domain.commits import extrair_chamado, match_exato, ordenar_por_grafo
from motor.domain.types import CommitRef


def test_extrair_chamado():
    assert extrair_chamado("ch123456 corrige calculo de frete") == "123456"
    assert extrair_chamado("sem identificador nenhum") is None


def test_match_exato_respeita_word_boundary():
    candidatos = [
        CommitRef(hash_origem="a", msg="ch5514 alfa"),
        CommitRef(hash_origem="b", msg="ch255514 beta"),
    ]
    achados = match_exato(candidatos, "5514")
    assert [c.hash_origem for c in achados] == ["a"]

    # a colisao que o \b realmente evita e de prefixo: "123" nao pode casar
    # dentro de "1234" (sem boundary, "ch123" e substring valida de "ch1234").
    candidatos_prefixo = [
        CommitRef(hash_origem="c", msg="ch123 fix"),
        CommitRef(hash_origem="d", msg="ch1234 other fix"),
    ]
    achados_prefixo = match_exato(candidatos_prefixo, "123")
    assert [c.hash_origem for c in achados_prefixo] == ["c"]


def test_match_exato_sem_chamado_nao_casa_nada():
    candidatos = [CommitRef(hash_origem="a", msg="ch5514 alfa")]
    assert match_exato(candidatos, "") == []


def test_match_exato_ignora_caixa_do_prefixo():
    # "CH254473." existe no historico real tanto quanto "ch254473." — o prefixo
    # e digitado a mao. O `-i` de search_commits traz o candidato; perde-lo aqui
    # so mudaria o lugar do falso-negativo.
    candidatos = [
        CommitRef(hash_origem="a", msg="CH254473. mais tempos para sessoes"),
        CommitRef(hash_origem="b", msg="Ch2544731 outro chamado"),
    ]
    assert [c.hash_origem for c in match_exato(candidatos, "254473")] == ["a"]


def test_extrair_chamado_ignora_caixa():
    assert extrair_chamado("CH254473 - ajuste") == "254473"


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
