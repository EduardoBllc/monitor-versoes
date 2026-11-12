"""As migrations do Alembic rodam no SQLite."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from motor.adapters.estado.models import Base
from motor.migracoes import config_alembic

REV_TIPO_LIVRE_ANTERIOR = "e5a8b1c2d3f4"
REV_COM_TRACKER = "f6b9c3d2e1a7"
REV_SEM_TRACKER = "a7c3e9d1f2b4"
REV_CHECK_COM_NOME_DUPLICADO = "c9d2e4f6a8b0"


@pytest.fixture
def url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'estado.db'}"


def test_upgrade_cria_todas_as_tabelas_e_o_indice_unico(url: str) -> None:
    command.upgrade(config_alembic(url), "head")

    engine = create_engine(url)
    insp = inspect(engine)
    assert set(Base.metadata.tables) <= set(insp.get_table_names())
    with engine.connect() as con:
        # a reflexao do SQLAlchemy ignora indice de expressao: le o DDL cru.
        indice = con.execute(
            text(
                "select sql from sqlite_master where name = 'uq_exclusao_repo_hash_versao'"
            )
        ).scalar_one()
        triggers = {
            r[0]
            for r in con.execute(
                text("select name from sqlite_master where type='trigger'")
            )
        }
        checks = (
            con.execute(
                text("select sql from sqlite_master where name in ('versao', 'repo')")
            )
            .scalars()
            .all()
        )
    assert indice.lower().startswith("create unique index")
    assert len(triggers) == 6
    assert not any("ck_versao_tipo" in c for c in checks)
    assert not any("ck_repo_piso_versao" in c for c in checks)


def test_tipo_gravado_antes_do_tipo_livre_sobrevive_ao_upgrade(url: str) -> None:
    command.upgrade(config_alembic(url), REV_TIPO_LIVRE_ANTERIOR)
    engine = create_engine(url)
    with engine.begin() as con:
        con.execute(
            text(
                "insert into repo (id, nome, tickio_sistema_id) values (1, 'webapp', 1)"
            )
        )
        con.execute(
            text(
                "insert into versao (repo_id, numero, tipo, base_ref, base_commit) "
                "values (1, '13.34.0', 'ajustada', '13.33.0', 'aaa111')"
            )
        )

    command.upgrade(config_alembic(url), "head")

    with engine.connect() as con:
        tipo = con.execute(text("select tipo from versao")).scalar_one()
    assert tipo == "ajustada"


def test_colunas_do_tracker_saem_e_o_downgrade_as_recria(url: str) -> None:
    command.upgrade(config_alembic(url), REV_COM_TRACKER)
    engine = create_engine(url)
    with engine.begin() as con:
        con.execute(
            text(
                "insert into repo (id, nome, tickio_sistema_id, piso_versao) "
                "values (1, 'webapp', 7, '14.0.0')"
            )
        )
        con.execute(text("insert into repo_alias (nome, repo_id) values ('web', 1)"))
        con.execute(
            text(
                "insert into versao (repo_id, numero, tipo, base_ref, base_commit) "
                "values (1, '14.1.0', null, '14.0.0', 'aaa111')"
            )
        )

    command.upgrade(config_alembic(url), REV_SEM_TRACKER)

    with engine.connect() as con:
        colunas = {c["name"] for c in inspect(con).get_columns("repo")}
        linhas = [
            con.execute(text("select nome from repo")).scalar_one(),
            con.execute(text("select nome from repo_alias")).scalar_one(),
            con.execute(text("select numero from versao")).scalar_one(),
        ]
    assert colunas == {"id", "nome"}
    assert linhas == ["webapp", "web", "14.1.0"]

    command.downgrade(config_alembic(url), REV_COM_TRACKER)

    with engine.connect() as con:
        recriadas = con.execute(
            text("select tickio_sistema_id, piso_versao from repo")
        ).one()
        alias = con.execute(text("select nome from repo_alias")).scalar_one()
    assert tuple(recriadas) == (0, "13.0.0")
    assert alias == "web"
    with pytest.raises(IntegrityError), engine.begin() as con:
        con.execute(text("update repo set piso_versao = 'x'"))
    engine.dispose()


def test_repo_alias_sai_e_o_repo_fica(url: str) -> None:
    command.upgrade(config_alembic(url), REV_SEM_TRACKER)
    engine = create_engine(url)
    with engine.begin() as con:
        con.execute(text("insert into repo (id, nome) values (1, 'webapp')"))
        con.execute(
            text(
                "insert into versao (repo_id, numero, tipo, base_ref, base_commit) "
                "values (1, '14.1.0', null, '14.0.0', 'aaa111')"
            )
        )

    command.upgrade(config_alembic(url), "head")

    with engine.connect() as con:
        assert "repo_alias" not in inspect(con).get_table_names()
        assert con.execute(text("select nome from repo")).scalar_one() == "webapp"
        assert con.execute(text("select numero from versao")).scalar_one() == "14.1.0"
    engine.dispose()


def test_downgrade_base_funciona(url: str) -> None:
    command.upgrade(config_alembic(url), "head")
    command.downgrade(config_alembic(url), "base")

    with create_engine(url).connect() as con:
        restantes = inspect(con).get_table_names()
        triggers = con.execute(
            text("select name from sqlite_master where type='trigger'")
        ).all()
    assert restantes == ["alembic_version"]
    assert triggers == []


def _ddl(con: Connection, nome: str) -> str:
    sql: str = con.execute(
        text("select sql from sqlite_master where name = :nome"), {"nome": nome}
    ).scalar_one()
    return sql


def _triggers(con: Connection) -> list[tuple[str, str]]:
    return sorted(
        (nome, sql)
        for nome, sql in con.execute(
            text("select name, sql from sqlite_master where type = 'trigger'")
        )
    )


def test_check_de_atribuicao_ganha_o_nome_da_convencao(url: str) -> None:
    command.upgrade(config_alembic(url), REV_CHECK_COM_NOME_DUPLICADO)
    engine = create_engine(url)
    with engine.connect() as con:
        triggers_antes = _triggers(con)
        commit_antes = _ddl(con, "atribuicao_commit")

    command.upgrade(config_alembic(url), "head")

    with engine.connect() as con:
        ddl = _ddl(con, "atribuicao")
        assert "CONSTRAINT ck_atribuicao_estado CHECK" in ddl
        assert "ck_atribuicao_ck_" not in ddl
        assert len(triggers_antes) == 6
        assert _triggers(con) == triggers_antes
        assert _ddl(con, "atribuicao_commit") == commit_antes
    with pytest.raises(IntegrityError), engine.begin() as con:
        con.execute(text("insert into repo (id, nome) values (1, 'webapp')"))
        con.execute(
            text(
                "insert into versao (id, repo_id, numero, base_ref, base_commit) "
                "values (1, 1, '14.1.0', '14.0.0', 'aaa111')"
            )
        )
        con.execute(
            text(
                "insert into atribuicao (versao_id, chamado, marcada, estado) "
                "values (1, 'T-1', '14.1.0', 'x')"
            )
        )
    engine.dispose()


def test_downgrade_volta_o_nome_antigo_do_check(url: str) -> None:
    command.upgrade(config_alembic(url), REV_CHECK_COM_NOME_DUPLICADO)
    engine = create_engine(url)
    with engine.connect() as con:
        triggers_antes = _triggers(con)

    command.upgrade(config_alembic(url), "head")
    command.downgrade(config_alembic(url), REV_CHECK_COM_NOME_DUPLICADO)

    with engine.connect() as con:
        ddl = _ddl(con, "atribuicao")
        assert "CONSTRAINT ck_atribuicao_ck_atribuicao_estado CHECK" in ddl
        assert _triggers(con) == triggers_antes
    engine.dispose()


def test_dados_sobrevivem_a_troca_do_nome_do_check(url: str) -> None:
    command.upgrade(config_alembic(url), REV_CHECK_COM_NOME_DUPLICADO)
    engine = create_engine(url)
    consultas = {
        "repo": "select * from repo",
        "versao": "select * from versao",
        "atribuicao": "select * from atribuicao",
        "atribuicao_commit": "select * from atribuicao_commit",
        "exclusao": "select * from exclusao",
        "sem_entrega": "select * from sem_entrega",
    }
    with engine.begin() as con:
        con.execute(text("insert into repo (id, nome) values (1, 'webapp')"))
        con.execute(
            text(
                "insert into versao (id, repo_id, numero, base_ref, base_commit) "
                "values (1, 1, '14.1.0', '14.0.0', 'aaa111')"
            )
        )
        con.execute(
            text(
                "insert into atribuicao (versao_id, chamado, marcada, estado) "
                "values (1, 'T-1', '14.1.0', 'aplicado')"
            )
        )
        con.execute(
            text(
                "insert into atribuicao_commit (versao_id, chamado, hash_origem) "
                "values (1, 'T-1', 'bbb222')"
            )
        )
        con.execute(
            text(
                "insert into exclusao (repo_id, hash_origem, versao_numero, motivo) "
                "values (1, 'ccc333', '14.1.0', 'revertido')"
            )
        )
        con.execute(
            text(
                "insert into sem_entrega (repo_id, chamado, motivo) "
                "values (1, 'T-2', 'só configuração')"
            )
        )
    with engine.connect() as con:
        antes = {t: con.execute(text(q)).all() for t, q in consultas.items()}

    command.upgrade(config_alembic(url), "head")

    with engine.connect() as con:
        depois = {t: con.execute(text(q)).all() for t, q in consultas.items()}
    assert all(antes.values())
    assert depois == antes
    engine.dispose()


# O SQLite não reflete índice de expressão: o autogenerate pula o
# uq_exclusao_repo_hash_versao, que se escreve à mão.
@pytest.mark.filterwarnings("ignore:.*expression-based index")
def test_modelos_e_migracoes_nao_divergem(url: str) -> None:
    command.upgrade(config_alembic(url), "head")
    engine = create_engine(url)
    with engine.connect() as con:
        diferencas = compare_metadata(MigrationContext.configure(con), Base.metadata)
    engine.dispose()
    assert diferencas == []
