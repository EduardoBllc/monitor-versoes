"""piso de versao por repo

O piso de `fontes_de_alvo` era a constante 13.0.0 para todo repo. Repo com
branch legada sem tag acima dela (13.1.0 do vb2web) fazia o verificar pedir ao
Tickio uma versao que ele nao conhece, e o 404 derrubava o run inteiro.

Default 13.0.0: repo ja cadastrado mantem o comportamento de antes.

Revision ID: d4e7a9b2c1f0
Revises: b1f2c3d4e5a6
Create Date: 2026-10-08

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e7a9b2c1f0"
down_revision: str | Sequence[str] | None = "b1f2c3d4e5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "repo",
        sa.Column("piso_versao", sa.String(), nullable=False, server_default="13.0.0"),
    )
    if op.get_bind().dialect.name == "sqlite":
        # Sem regex no SQLite: tres grupos numericos separados por ponto, via glob.
        with op.batch_alter_table("repo") as lote:
            lote.create_check_constraint(
                "ck_repo_piso_versao",
                "piso_versao glob '[0-9]*.[0-9]*.[0-9]*' "
                "and piso_versao not glob '*[^0-9.]*' "
                "and piso_versao not glob '*..*' "
                "and piso_versao not glob '*.*.*.*' "
                "and piso_versao not glob '*.'",
            )
        return
    # Mesmo motivo de ck_versao_tipo: o schema e corrigido via psql, e um piso
    # digitado errado so estouraria no proximo verificar, longe da causa.
    op.execute(
        "alter table repo add constraint ck_repo_piso_versao "
        r"check (piso_versao ~ '^\d+\.\d+\.\d+$')"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("repo") as lote:
            lote.drop_constraint("ck_repo_piso_versao", type_="check")
            lote.drop_column("piso_versao")
        return
    op.drop_constraint("ck_repo_piso_versao", "repo")
    op.drop_column("repo", "piso_versao")
