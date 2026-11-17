"""atualizada_em na versao

Quando a versao foi atualizada pela ultima vez; null ate a primeira atualizacao.

Revision ID: 3c8e1f7a92d4
Revises: a95857a66f91
Create Date: 2026-11-17 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c8e1f7a92d4"
down_revision: str | Sequence[str] | None = "a95857a66f91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ALTER direto, sem batch: recriar `versao` quebra as triggers que a citam.
    op.add_column(
        "versao", sa.Column("atualizada_em", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("versao", "atualizada_em")
