"""As migrations do Alembic rodam no SQLite, sem Docker."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from motor.adapters.estado.models import Base
from motor.migracoes import config_alembic


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
    command.upgrade(config_alembic(url), "e5a8b1c2d3f4")
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
    command.upgrade(config_alembic(url), "f6b9c3d2e1a7")
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

    command.upgrade(config_alembic(url), "head")

    with engine.connect() as con:
        colunas = {c["name"] for c in inspect(con).get_columns("repo")}
        linhas = [
            con.execute(text("select nome from repo")).scalar_one(),
            con.execute(text("select nome from repo_alias")).scalar_one(),
            con.execute(text("select numero from versao")).scalar_one(),
        ]
    assert colunas == {"id", "nome"}
    assert linhas == ["webapp", "web", "14.1.0"]

    command.downgrade(config_alembic(url), "f6b9c3d2e1a7")

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
