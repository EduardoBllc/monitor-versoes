"""julgamento de órfão

Guarda, por versão, o julgamento humano de cada commit órfão (sem referência
de tarefa): o chamado a que ele pertence, ou nenhum, e o motivo.

Revision ID: c9d2e4f6a8b0
Revises: b8d4f0a2c3e5

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d2e4f6a8b0"
down_revision: str | Sequence[str] | None = "b8d4f0a2c3e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "julgamento_orfao",
        sa.Column("versao_id", sa.Integer(), nullable=False),
        sa.Column("hash_origem", sa.String(), nullable=False),
        sa.Column("chamado", sa.String(), nullable=True),
        sa.Column("motivo", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["versao_id"],
            ["versao.id"],
            name=op.f("fk_julgamento_orfao_versao_id_versao"),
        ),
        sa.PrimaryKeyConstraint(
            "versao_id", "hash_origem", name=op.f("pk_julgamento_orfao")
        ),
    )


def downgrade() -> None:
    op.drop_table("julgamento_orfao")
