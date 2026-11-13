"""host na varredura de PR

A marca, o indice e o cache de PR passam a valer so para o host que os gravou
(`[prs] fonte`); trocar de host zera os tres. As linhas ja gravadas ficam com
`bitbucket`, o unico host que existiu antes desta revisao.

Revision ID: a95857a66f91
Revises: e50b3d6e40a1
Create Date: 2026-11-13 03:03:20.788475

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a95857a66f91"
down_revision: str | Sequence[str] | None = "e50b3d6e40a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # O default so preenche as linhas antigas: Bitbucket era o unico host.
    with op.batch_alter_table("varredura_pr") as lote:
        lote.add_column(
            sa.Column("host", sa.String(), nullable=False, server_default="bitbucket")
        )
    with op.batch_alter_table("varredura_pr") as lote:
        lote.alter_column("host", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("varredura_pr") as lote:
        lote.drop_column("host")
