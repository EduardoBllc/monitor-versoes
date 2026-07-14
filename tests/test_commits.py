"""Porte de internal/domain/commits_test.go."""

import datetime

from motor.domain.commits import extrair_chamado, extrair_vb_id, match_exato, ordenar_por_data
from motor.domain.types import CommitRef


def test_match_exato_evita_substring():
    candidatos = [
        CommitRef(hash_origem="aaa", msg="fix: ch255514 corrige logs"),
        CommitRef(hash_origem="bbb", msg="fix: ch5514 outro chamado nao relacionado"),
    ]
    resultado = match_exato(candidatos, "255514", "")
    assert len(resultado) == 1 and resultado[0].hash_origem == "aaa"


def test_match_exato_vb_id():
    candidatos = [
        CommitRef(hash_origem="ccc", msg="VB-2354: logs pedidos ecommerce"),
        CommitRef(hash_origem="ddd", msg="nao relacionado VB-23540"),
    ]
    resultado = match_exato(candidatos, "", "VB-2354")
    assert len(resultado) == 1 and resultado[0].hash_origem == "ccc"


def test_extrair_chamado():
    chamado = extrair_chamado("fix: ch255514 corrige logs")
    assert chamado == "255514"
    assert extrair_chamado("sem chamado nenhum") is None


def test_extrair_vb_id():
    vb_id = extrair_vb_id("VB-2354: logs pedidos ecommerce")
    assert vb_id == "VB-2354"


def test_ordenar_por_data():
    t1 = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    t2 = datetime.datetime(2024, 2, 1, tzinfo=datetime.timezone.utc)
    t3 = datetime.datetime(2024, 3, 1, tzinfo=datetime.timezone.utc)
    entrada = [
        CommitRef(hash_origem="c", commit_date=t3),
        CommitRef(hash_origem="a", commit_date=t1),
        CommitRef(hash_origem="b", commit_date=t2),
    ]
    resultado = ordenar_por_data(entrada)
    quer = ["a", "b", "c"]
    for i, hash_ in enumerate(quer):
        assert resultado[i].hash_origem == hash_, f"posicao {i} = {resultado[i].hash_origem}, quer {hash_}"

    assert entrada[0].hash_origem == "c", "ordenar_por_data nao deveria mutar a lista de entrada"
