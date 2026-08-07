from __future__ import annotations

import datetime

from motor.domain.commits import extrair_chamado, match_exato, ordenar_por_data
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


def test_match_exato_sem_chamado_nao_casa_nada():
    candidatos = [CommitRef(hash_origem="a", msg="ch5514 alfa")]
    assert match_exato(candidatos, "") == []


def test_ordenar_por_data_asc():
    d = datetime.datetime(2026, 1, 1)
    commits = [
        CommitRef(hash_origem="novo", commit_date=d + datetime.timedelta(days=2)),
        CommitRef(hash_origem="velho", commit_date=d),
    ]
    assert [c.hash_origem for c in ordenar_por_data(commits)] == ["velho", "novo"]
