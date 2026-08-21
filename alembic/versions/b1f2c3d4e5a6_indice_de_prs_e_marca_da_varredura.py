"""indice de PRs e marca da varredura

Substitui as N buscas por chamado na API do Bitbucket (uma por chamado, a cada
`verificar`) por uma varredura incremental: `bitbucket_pr` guarda o indice das
PRs mergeadas e `bitbucket_varredura` guarda ate quando esse indice esta
completo.

Cache reconstruivel: o downgrade dropa as duas e a proxima execucao refaz o
backfill a partir da API.

Revision ID: b1f2c3d4e5a6
Revises: ada75384c2bb

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1f2c3d4e5a6"
down_revision: Union[str, Sequence[str], None] = "ada75384c2bb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bitbucket_pr",
        sa.Column("repo_id", sa.Integer(), nullable=False),
        # BigInteger: o pr_id vem do Bitbucket, nao e nosso para caber em int4.
        sa.Column("pr_id", sa.BigInteger(), nullable=False),
        sa.Column("titulo", sa.String(), nullable=False),
        sa.Column("branch", sa.String(), nullable=False),
        sa.Column("updated_on", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["repo_id"], ["repo.id"], name=op.f("fk_bitbucket_pr_repo_id_repo")
        ),
        sa.PrimaryKeyConstraint("repo_id", "pr_id", name=op.f("pk_bitbucket_pr")),
    )
    op.create_table(
        "bitbucket_varredura",
        sa.Column("repo_id", sa.Integer(), nullable=False),
        sa.Column("ate", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["repo_id"], ["repo.id"], name=op.f("fk_bitbucket_varredura_repo_id_repo")
        ),
        sa.PrimaryKeyConstraint("repo_id", name=op.f("pk_bitbucket_varredura")),
    )


def downgrade() -> None:
    op.drop_table("bitbucket_varredura")
    op.drop_table("bitbucket_pr")
