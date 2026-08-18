from __future__ import annotations

import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from motor.adapters.estado.postgres import PostgresEstado
from motor.domain.types import Atribuicao, VersaoInfo, VersionType
from motor.errors import MotorError

pytestmark = pytest.mark.integracao


def _semear_repo(sessao) -> None:
    sessao.execute(
        text(
            "insert into repo (nome, tickio_sistema_id) values ('vendabemweb', 1)"
        )
    )
    sessao.execute(
        text(
            "insert into repo_alias (nome, repo_id) select 'vbweb', id from repo"
        )
    )
    sessao.commit()


def _info(numero: str) -> VersaoInfo:
    return VersaoInfo(
        numero=numero,
        tipo=VersionType.AJUSTADA,
        base_ref="13.33.0",
        base_commit="aaa111",
    )


def test_resolver_repo_por_alias(sessao_postgres):
    _semear_repo(sessao_postgres)
    estado = PostgresEstado(sessao=sessao_postgres)

    assert estado.resolver_repo("vbweb").nome == "vendabemweb"
    assert estado.resolver_repo("vbweb").tickio_sistema_id == 1


def test_resolver_repo_desconhecido(sessao_postgres):
    estado = PostgresEstado(sessao=sessao_postgres)
    with pytest.raises(MotorError, match="insert into repo"):
        estado.resolver_repo("nunca-visto")


def test_ciclo_de_atribuicoes(sessao_postgres):
    _semear_repo(sessao_postgres)
    estado = PostgresEstado(sessao=sessao_postgres)
    estado.registrar_versao("vendabemweb", _info("13.34.0"))

    # dois chamados, cada um com seus proprios hashes: exercita o
    # agrupamento commits-por-chamado, nao so o caso trivial de um so.
    estado.substituir_atribuicoes("vendabemweb", "13.34.0", [
        Atribuicao(chamado="123456", marcada="13.34.0", estado="aplicado",
                   commits=["aaa", "bbb"]),
        Atribuicao(chamado="789012", marcada="13.34.0", estado="pendente",
                   commits=["ccc"]),
    ])

    lidas = estado.atribuicoes("vendabemweb", "13.34.0")
    assert [a.chamado for a in lidas] == ["123456", "789012"]
    assert sorted(lidas[0].commits) == ["aaa", "bbb"]
    assert sorted(lidas[1].commits) == ["ccc"]


def test_trigger_recusa_escrita_em_versao_liberada(sessao_postgres):
    """A invariante central do congelamento. Um fake nao prova isto — a trigger
    tem que existir no banco de verdade."""
    _semear_repo(sessao_postgres)
    estado = PostgresEstado(sessao=sessao_postgres)
    estado.registrar_versao("vendabemweb", _info("13.34.0"))
    estado.substituir_atribuicoes("vendabemweb", "13.34.0", [
        Atribuicao(chamado="123456", marcada="13.34.0", estado="aplicado",
                   commits=["aaa"]),
    ])
    estado.marcar_liberadas("vendabemweb", {"13.34.0": datetime.datetime(2026, 8, 1)})

    with pytest.raises(MotorError, match="imutavel"):
        estado.substituir_atribuicoes("vendabemweb", "13.34.0", [
            Atribuicao(chamado="999111", marcada="13.34.0", estado="pendente",
                       commits=["ccc"]),
        ])

    # e o snapshot antigo continua intacto
    assert [a.chamado for a in estado.atribuicoes("vendabemweb", "13.34.0")] == ["123456"]


def test_trigger_recusa_mover_atribuicao_para_fora_de_versao_liberada(sessao_postgres):
    """Buraco conhecido do trigger (achado e corrigido na Task 5, migracao
    eafc77e6d0ce): a primeira versao da funcao so olhava new.versao_id, e um
    UPDATE que move uma atribuicao PARA FORA de uma versao liberada (old =
    congelada, new = livre) passava o guard e esvaziava o snapshot em
    silencio. Nenhum metodo do adapter emite esse UPDATE — substituir_
    atribuicoes so faz delete+insert — entao o buraco so aparece testando a
    trigger direto via SQL, por fora do adapter."""
    _semear_repo(sessao_postgres)
    estado = PostgresEstado(sessao=sessao_postgres)
    estado.registrar_versao("vendabemweb", _info("13.34.0"))
    estado.registrar_versao(
        "vendabemweb",
        VersaoInfo(numero="13.35.0", tipo=VersionType.AJUSTADA,
                   base_ref="13.33.0", base_commit="bbb222"),
    )
    estado.substituir_atribuicoes("vendabemweb", "13.34.0", [
        Atribuicao(chamado="123456", marcada="13.34.0", estado="aplicado",
                   commits=[]),
    ])
    estado.marcar_liberadas("vendabemweb", {"13.34.0": datetime.datetime(2026, 8, 1)})

    versao_livre_id = sessao_postgres.execute(
        text("select id from versao where numero = '13.35.0'")
    ).scalar_one()

    with pytest.raises(DatabaseError, match="imutavel"):
        sessao_postgres.execute(
            text("update atribuicao set versao_id = :novo where chamado = '123456'"),
            {"novo": versao_livre_id},
        )
    sessao_postgres.rollback()

    # a atribuicao continua presa na versao liberada, nao migrou para a livre
    assert [a.chamado for a in estado.atribuicoes("vendabemweb", "13.34.0")] == ["123456"]
    assert estado.atribuicoes("vendabemweb", "13.35.0") == []


def test_marcar_liberadas_nao_reescreve_data(sessao_postgres):
    _semear_repo(sessao_postgres)
    estado = PostgresEstado(sessao=sessao_postgres)
    estado.registrar_versao("vendabemweb", _info("13.34.0"))
    # timezone.utc explicito: a coluna e timestamptz (migracao eafc77e6d0ce),
    # e um datetime naive de volta do banco nunca compara igual a um aware.
    primeira = datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc)
    estado.marcar_liberadas("vendabemweb", {"13.34.0": primeira})
    estado.marcar_liberadas(
        "vendabemweb",
        {"13.34.0": datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc)},
    )

    assert estado.versao("vendabemweb", "13.34.0").liberada_em == primeira


def test_registrar_versao_nao_sobrescreve_a_base(sessao_postgres):
    _semear_repo(sessao_postgres)
    estado = PostgresEstado(sessao=sessao_postgres)
    estado.registrar_versao("vendabemweb", _info("13.34.0"))
    # tipo diferente do primeiro registro (_info usa AJUSTADA): uma
    # implementacao que reescrevesse tipo/base_ref mas nao base_commit
    # passaria pelo assert antigo, que so checava base_commit.
    estado.registrar_versao(
        "vendabemweb",
        VersaoInfo(numero="13.34.0", tipo=VersionType.CLIENTE,
                   base_ref="master", base_commit="OUTRO"),
    )

    gravada = estado.versao("vendabemweb", "13.34.0")
    assert gravada.tipo == VersionType.AJUSTADA
    assert gravada.base_ref == "13.33.0"
    assert gravada.base_commit == "aaa111"


def test_substituir_atribuicoes_recusa_versao_liberada_com_snapshot_vazio(sessao_postgres):
    """A recusa nao pode depender so da trigger disparar: se a versao ja
    liberada nunca teve nenhuma atribuicao e a chamada tambem manda uma lista
    vazia, os deletes afetam 0 linhas e nenhum insert acontece — a trigger
    nao tem nada para vetar e o commit passaria em silencio se o adapter nao
    checasse liberada_em antes."""
    _semear_repo(sessao_postgres)
    estado = PostgresEstado(sessao=sessao_postgres)
    estado.registrar_versao("vendabemweb", _info("13.34.0"))
    estado.marcar_liberadas("vendabemweb", {"13.34.0": datetime.datetime(2026, 8, 1)})

    with pytest.raises(MotorError, match="imutavel"):
        estado.substituir_atribuicoes("vendabemweb", "13.34.0", [])


def test_sem_entrega(sessao_postgres):
    _semear_repo(sessao_postgres)
    repo_id = sessao_postgres.execute(
        text("select id from repo where nome = 'vendabemweb'")
    ).scalar_one()
    sessao_postgres.execute(
        text(
            "insert into sem_entrega (repo_id, chamado, motivo) "
            "values (:repo_id, '555444', 'chamado administrativo, sem commit')"
        ),
        {"repo_id": repo_id},
    )
    sessao_postgres.commit()

    estado = PostgresEstado(sessao=sessao_postgres)
    assert estado.sem_entrega("vendabemweb") == {
        "555444": "chamado administrativo, sem commit"
    }
