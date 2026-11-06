"""repo_alias sai do estado

Repos passam a ser seções da config central (issue #143); o alias deixa de
existir e o repo nasce no primeiro uso (`garantir_repo`).

O downgrade recria a tabela vazia: os aliases não voltam.

Revision ID: b8d4f0a2c3e5
Revises: a7c3e9d1f2b4

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d4f0a2c3e5"
down_revision: str | Sequence[str] | None = "a7c3e9d1f2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("repo_alias")


def downgrade() -> None:
    op.create_table(
        "repo_alias",
        sa.Column("nome", sa.String(), nullable=False),
        sa.Column("repo_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["repo_id"], ["repo.id"], name=op.f("fk_repo_alias_repo_id_repo")
        ),
        sa.PrimaryKeyConstraint("nome", name=op.f("pk_repo_alias")),
    )
