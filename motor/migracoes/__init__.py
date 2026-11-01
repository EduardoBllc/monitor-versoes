"""Migrações do banco, empacotadas junto do motor.

Sem `alembic.ini`: a única opção necessária (`script_location`) é montada aqui.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import OperationalError

from alembic import command
from motor.errors import BackendIndisponivel


def config_alembic() -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent))
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
            "não foi possível conectar ao Postgres para migrar; "
            "suba o banco com `docker compose up -d`"
        ) from erro


def criar_revisao(mensagem: str) -> None:
    """Gera uma revisão por autogenerate; exige o banco já migrado."""
    command.revision(config_alembic(), message=mensagem, autogenerate=True)
