"""estado de PR neutro de host

Renomeia `bitbucket_pr` para `pr_mergeada` e `bitbucket_varredura` para
`varredura_pr`, com PK e FK, para que adapters de outros hosts reaproveitem o
indice e a marca sem herdar um nome que mente. Rename puro: as linhas ja
gravadas continuam validas.

Revision ID: e5a8b1c2d3f4
Revises: d4e7a9b2c1f0

"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5a8b1c2d3f4"
down_revision: str | Sequence[str] | None = "d4e7a9b2c1f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RENOMEIA = (("bitbucket_pr", "pr_mergeada"), ("bitbucket_varredura", "varredura_pr"))


def _renomear(origem: str, destino: str) -> None:
    op.rename_table(origem, destino)
    op.execute(f"ALTER TABLE {destino} RENAME CONSTRAINT pk_{origem} TO pk_{destino}")
    op.execute(
        f"ALTER TABLE {destino} RENAME CONSTRAINT "
        f"fk_{origem}_repo_id_repo TO fk_{destino}_repo_id_repo"
    )


def upgrade() -> None:
    for antigo, novo in _RENOMEIA:
        _renomear(antigo, novo)


def downgrade() -> None:
    for antigo, novo in _RENOMEIA:
        _renomear(novo, antigo)
