from __future__ import annotations

import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from motor.adapters.estado.sqlite import Estado
from motor.domain.types import Atribuicao, Exclusion, VersaoInfo
from motor.errors import MotorError


def _semear_repo(sessao) -> None:
    sessao.execute(text("insert into repo (nome) values ('webapp')"))
    sessao.commit()


def _info(numero: str) -> VersaoInfo:
    return VersaoInfo(
        numero=numero,
        tipo="ajustada",
        base_ref="13.33.0",
        base_commit="aaa111",
    )


def test_ciclo_de_atribuicoes(sessao_sqlite):
    _semear_repo(sessao_sqlite)
    estado = Estado(sessao=sessao_sqlite)
    estado.registrar_versao("webapp", _info("13.34.0"))

    # dois chamados, cada um com seus proprios hashes: exercita o
    # agrupamento commits-por-chamado, nao so o caso trivial de um so.
    estado.substituir_atribuicoes(
        "webapp",
        "13.34.0",
        [
            Atribuicao(
                chamado="123456",
                marcada="13.34.0",
                estado="aplicado",
                commits=["aaa", "bbb"],
            ),
            Atribuicao(
                chamado="789012", marcada="13.34.0", estado="pendente", commits=["ccc"]
            ),
        ],
    )

    lidas = estado.atribuicoes("webapp", "13.34.0")
    assert [a.chamado for a in lidas] == ["123456", "789012"]
    assert sorted(lidas[0].commits) == ["aaa", "bbb"]
    assert sorted(lidas[1].commits) == ["ccc"]


def test_trigger_recusa_escrita_em_versao_liberada(sessao_sqlite):
    """A invariante central do congelamento. Um fake nao prova isto — a trigger
    tem que existir no banco de verdade."""
    _semear_repo(sessao_sqlite)
    estado = Estado(sessao=sessao_sqlite)
    estado.registrar_versao("webapp", _info("13.34.0"))
    estado.substituir_atribuicoes(
        "webapp",
        "13.34.0",
        [
            Atribuicao(
                chamado="123456", marcada="13.34.0", estado="aplicado", commits=["aaa"]
            ),
        ],
    )
    estado.marcar_liberadas("webapp", {"13.34.0": datetime.datetime(2026, 8, 1)})

    with pytest.raises(MotorError, match="imutavel"):
        estado.substituir_atribuicoes(
            "webapp",
            "13.34.0",
            [
                Atribuicao(
                    chamado="999111",
                    marcada="13.34.0",
                    estado="pendente",
                    commits=["ccc"],
                ),
            ],
        )

    # e o snapshot antigo continua intacto
    assert [a.chamado for a in estado.atribuicoes("webapp", "13.34.0")] == ["123456"]


def test_trigger_recusa_mover_atribuicao_para_fora_de_versao_liberada(sessao_sqlite):
    """Buraco conhecido do trigger (achado e corrigido na Task 5, migracao
    eafc77e6d0ce): a primeira versao da funcao so olhava new.versao_id, e um
    UPDATE que move uma atribuicao PARA FORA de uma versao liberada (old =
    congelada, new = livre) passava o guard e esvaziava o snapshot em
    silencio. Nenhum metodo do adapter emite esse UPDATE — substituir_
    atribuicoes so faz delete+insert — entao o buraco so aparece testando a
    trigger direto via SQL, por fora do adapter."""
    _semear_repo(sessao_sqlite)
    estado = Estado(sessao=sessao_sqlite)
    estado.registrar_versao("webapp", _info("13.34.0"))
    estado.registrar_versao(
        "webapp",
        VersaoInfo(
            numero="13.35.0",
            tipo="ajustada",
            base_ref="13.33.0",
            base_commit="bbb222",
        ),
    )
    estado.substituir_atribuicoes(
        "webapp",
        "13.34.0",
        [
            Atribuicao(
                chamado="123456", marcada="13.34.0", estado="aplicado", commits=[]
            ),
        ],
    )
    estado.marcar_liberadas("webapp", {"13.34.0": datetime.datetime(2026, 8, 1)})

    versao_livre_id = sessao_sqlite.execute(
        text("select id from versao where numero = '13.35.0'")
    ).scalar_one()

    with pytest.raises(DatabaseError, match="imutavel"):
        sessao_sqlite.execute(
            text("update atribuicao set versao_id = :novo where chamado = '123456'"),
            {"novo": versao_livre_id},
        )
    sessao_sqlite.rollback()

    # a atribuicao continua presa na versao liberada, nao migrou para a livre
    assert [a.chamado for a in estado.atribuicoes("webapp", "13.34.0")] == ["123456"]
    assert estado.atribuicoes("webapp", "13.35.0") == []


def test_marcar_liberadas_nao_reescreve_data(sessao_sqlite):
    _semear_repo(sessao_sqlite)
    estado = Estado(sessao=sessao_sqlite)
    estado.registrar_versao("webapp", _info("13.34.0"))
    # timezone.utc explicito: a coluna e timestamptz (migracao eafc77e6d0ce),
    # e um datetime naive de volta do banco nunca compara igual a um aware.
    primeira = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    estado.marcar_liberadas("webapp", {"13.34.0": primeira})
    estado.marcar_liberadas(
        "webapp",
        {"13.34.0": datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)},
    )

    gravada = estado.versao("webapp", "13.34.0")
    assert gravada is not None
    assert gravada.liberada_em == primeira


def test_registrar_versao_nao_sobrescreve_a_base(sessao_sqlite):
    _semear_repo(sessao_sqlite)
    estado = Estado(sessao=sessao_sqlite)
    estado.registrar_versao("webapp", _info("13.34.0"))
    # tipo diferente do primeiro registro (_info usa AJUSTADA): uma
    # implementacao que reescrevesse tipo/base_ref mas nao base_commit
    # passaria pelo assert antigo, que so checava base_commit.
    estado.registrar_versao(
        "webapp",
        VersaoInfo(
            numero="13.34.0",
            tipo="cliente",
            base_ref="master",
            base_commit="OUTRO",
        ),
    )

    gravada = estado.versao("webapp", "13.34.0")
    assert gravada is not None
    assert gravada.tipo == "ajustada"
    assert gravada.base_ref == "13.33.0"
    assert gravada.base_commit == "aaa111"


def test_substituir_atribuicoes_recusa_versao_liberada_com_snapshot_vazio(
    sessao_sqlite,
):
    """A recusa nao pode depender so da trigger disparar: se a versao ja
    liberada nunca teve nenhuma atribuicao e a chamada tambem manda uma lista
    vazia, os deletes afetam 0 linhas e nenhum insert acontece — a trigger
    nao tem nada para vetar e o commit passaria em silencio se o adapter nao
    checasse liberada_em antes."""
    _semear_repo(sessao_sqlite)
    estado = Estado(sessao=sessao_sqlite)
    estado.registrar_versao("webapp", _info("13.34.0"))
    estado.marcar_liberadas("webapp", {"13.34.0": datetime.datetime(2026, 8, 1)})

    with pytest.raises(MotorError, match="imutavel"):
        estado.substituir_atribuicoes("webapp", "13.34.0", [])


def test_exclusoes(sessao_sqlite):
    """Primeira execucao real do corpo de `exclusoes()`: ate aqui nada semeava
    linha em `exclusao`, entao o adapter construia um `Exclusion` na forma nova
    sem nunca ter rodado uma vez.

    Duas linhas de proposito: `versao_numero` null (vale para todo o repo, ex.:
    commit revertido) e preenchida (vale so para aquela versao). E a distincao
    em que `filtrar_excluidos` se apoia — uma traducao que perdesse o null
    passaria num teste de uma linha so.
    """
    _semear_repo(sessao_sqlite)
    repo_id = sessao_sqlite.execute(
        text("select id from repo where nome = 'webapp'")
    ).scalar_one()
    sessao_sqlite.execute(
        text(
            "insert into exclusao (repo_id, hash_origem, versao_numero, motivo) "
            "values (:repo_id, 'aaa111', null, 'revertido em master'), "
            "       (:repo_id, 'bbb222', '13.34.0', 'nao se aplica a esta versao')"
        ),
        {"repo_id": repo_id},
    )
    sessao_sqlite.commit()

    estado = Estado(sessao=sessao_sqlite)

    assert estado.exclusoes("webapp") == [
        Exclusion(
            hash_origem="aaa111", versao_numero=None, motivo="revertido em master"
        ),
        Exclusion(
            hash_origem="bbb222",
            versao_numero="13.34.0",
            motivo="nao se aplica a esta versao",
        ),
    ]


def test_sem_entrega(sessao_sqlite):
    _semear_repo(sessao_sqlite)
    repo_id = sessao_sqlite.execute(
        text("select id from repo where nome = 'webapp'")
    ).scalar_one()
    sessao_sqlite.execute(
        text(
            "insert into sem_entrega (repo_id, chamado, motivo) "
            "values (:repo_id, '555444', 'chamado administrativo, sem commit')"
        ),
        {"repo_id": repo_id},
    )
    sessao_sqlite.commit()

    estado = Estado(sessao=sessao_sqlite)
    assert estado.sem_entrega("webapp") == {
        "555444": "chamado administrativo, sem commit"
    }


def test_migracao_de_nomes_neutros_preserva_as_linhas(sessao_sqlite):
    from alembic import command

    from motor.migracoes import config_alembic

    _semear_repo(sessao_sqlite)
    sessao_sqlite.execute(
        text(
            "insert into pr_mergeada (repo_id, pr_id, titulo, branch, updated_on) "
            "select id, 7, 't', 'b', CURRENT_TIMESTAMP from repo"
        )
    )
    sessao_sqlite.execute(
        text(
            "insert into varredura_pr (repo_id, ate) select id, CURRENT_TIMESTAMP from repo"
        )
    )
    sessao_sqlite.commit()
    # Fecha a transacao aberta: a migracao espera o lock dela.
    sessao_sqlite.close()
    cfg = config_alembic(str(sessao_sqlite.get_bind().url))

    command.downgrade(cfg, "d4e7a9b2c1f0")
    try:
        antigos = [
            sessao_sqlite.execute(text(f"select count(*) from {t}")).scalar()
            for t in ("bitbucket_pr", "bitbucket_varredura")
        ]
        sessao_sqlite.rollback()
    finally:
        command.upgrade(cfg, "head")

    assert antigos == [1, 1]
    novos = [
        sessao_sqlite.execute(text(f"select count(*) from {t}")).scalar()
        for t in ("pr_mergeada", "varredura_pr")
    ]
    assert novos == [1, 1]
