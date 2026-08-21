"""cache de commits por PR do bitbucket

Cache puro de fato imutavel: PR mergeada nao ganha nem perde commit. Corta o
`GET /pullrequests/{id}/commits`, que roda uma vez por PR a cada `verificar`.

Nao ha nada a preservar aqui — o downgrade dropa a tabela e o proximo run
reconstroi tudo a partir da API.

Revision ID: ada75384c2bb
Revises: c31ffb4de7a1
Create Date: 2026-08-21 10:09:27.501153

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ada75384c2bb"
down_revision: Union[str, Sequence[str], None] = "c31ffb4de7a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pr_commit_cache",
        sa.Column("repo_id", sa.Integer(), nullable=False),
        # BigInteger: o pr_id vem do Bitbucket, nao e nosso para caber em int4.
        sa.Column("pr_id", sa.BigInteger(), nullable=False),
        sa.Column("hash_origem", sa.String(), nullable=False),
        sa.Column("parent", sa.String(), nullable=False),
        sa.Column("commit_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("msg", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["repo_id"], ["repo.id"], name=op.f("fk_pr_commit_cache_repo_id_repo")
        ),
        sa.PrimaryKeyConstraint(
            "repo_id", "pr_id", "hash_origem", name=op.f("pk_pr_commit_cache")
        ),
    )


def downgrade() -> None:
    op.drop_table("pr_commit_cache")
