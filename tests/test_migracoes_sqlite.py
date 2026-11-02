"""As migrations do Alembic rodam no SQLite, sem Docker."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from motor.adapters.estado.models import Base

RAIZ = Path(__file__).resolve().parent.parent


def _config(url: str) -> Config:
    config = Config(str(RAIZ / "alembic.ini"))
    config.set_main_option("script_location", str(RAIZ / "alembic"))
    config.attributes["url"] = url
    return config


@pytest.fixture
def url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'estado.db'}"


def test_upgrade_cria_todas_as_tabelas_e_o_indice_unico(url: str) -> None:
    command.upgrade(_config(url), "head")

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
    assert any("ck_versao_tipo" in c for c in checks)
    assert any("ck_repo_piso_versao" in c for c in checks)


def test_downgrade_base_funciona(url: str) -> None:
    command.upgrade(_config(url), "head")
    command.downgrade(_config(url), "base")

    with create_engine(url).connect() as con:
        restantes = inspect(con).get_table_names()
        triggers = con.execute(
            text("select name from sqlite_master where type='trigger'")
        ).all()
    assert restantes == ["alembic_version"]
    assert triggers == []
