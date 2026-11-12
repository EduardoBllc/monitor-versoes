"""Migrações do banco, empacotadas junto do motor.

Sem `alembic.ini`: a única opção necessária (`script_location`) é montada aqui.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import OperationalError

from motor.errors import BackendIndisponivel


def config_alembic(url: str | None = None) -> Config:
    """Config do Alembic; `url` tem precedência sobre a do ambiente."""
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent))
    if url is not None:
        config.attributes["url"] = url
    return config


def head() -> str:
    """Revisão `head` dos scripts de migração."""
    revisao = ScriptDirectory.from_config(config_alembic()).get_current_head()
    assert revisao is not None  # o pacote sempre tem ao menos uma migração
    return revisao


def migrar() -> None:
    """Aplica as migrações pendentes (`upgrade head`)."""
    try:
        command.upgrade(config_alembic(), "head")
    except OperationalError as erro:
        raise BackendIndisponivel(
            f"não foi possível abrir o estado para migrar: {erro.orig}; "
            "confira DATABASE_SQLITE_PATH e as permissões do arquivo"
        ) from erro


def criar_revisao(mensagem: str) -> None:
    """Gera uma revisão por autogenerate, sem exigir banco nenhum.

    Compara os modelos com um SQLite temporário levado ao `head`, que é
    descartado no fim.
    """
    with tempfile.TemporaryDirectory() as pasta:
        url = f"sqlite:///{Path(pasta) / 'estado.db'}"
        command.upgrade(config_alembic(url), "head")
        command.revision(config_alembic(url), message=mensagem, autogenerate=True)
