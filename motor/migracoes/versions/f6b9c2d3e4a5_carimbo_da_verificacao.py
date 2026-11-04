"""carimbo da verificação

Guarda, por versão, o resultado do último `verificar` com o tip e a impressão
que o tornam reaproveitável. Cache: o downgrade o descarta.

Revision ID: f6b9c2d3e4a5
Revises: e5a8b1c2d3f4

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6b9c2d3e4a5"
down_revision: str | Sequence[str] | None = "e5a8b1c2d3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verificacao",
        sa.Column("versao_id", sa.Integer(), nullable=False),
        sa.Column("tip", sa.String(), nullable=False),
        sa.Column("impressao", sa.String(), nullable=False),
        sa.Column("verificado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["versao_id"],
            ["versao.id"],
            name=op.f("fk_verificacao_versao_id_versao"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("versao_id", name=op.f("pk_verificacao")),
    )


def downgrade() -> None:
    op.drop_table("verificacao")
