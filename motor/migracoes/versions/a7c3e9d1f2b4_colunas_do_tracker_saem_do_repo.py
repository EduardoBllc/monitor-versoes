"""colunas do tracker saem do repo

`tickio_sistema_id` e `piso_versao` sao ignoradas desde a config por projeto
(docs/decisoes/024-config-por-projeto.md): `[tarefas] sistema` e `[versao] piso`
vem dos arquivos de config. O script `scripts/migrar_banco_para_config.py` leva
os valores para la antes desta revisao.

O downgrade recria as colunas com os defaults de quando nasceram (`0` e
`13.0.0`) e o check do piso. Os valores originais nao voltam: estao na config.

Revision ID: a7c3e9d1f2b4
Revises: f6b9c3d2e1a7

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e9d1f2b4"
down_revision: str | Sequence[str] | None = "f6b9c3d2e1a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mesma expressao de d4e7a9b2c1f0 (copiada: migration nao importa de outra).
_CHECK_PISO_SQLITE = (
    "piso_versao glob '[0-9]*.[0-9]*.[0-9]*' "
    "and piso_versao not glob '*[^0-9.]*' "
    "and piso_versao not glob '*..*' "
    "and piso_versao not glob '*.*.*.*' "
    "and piso_versao not glob '*.'"
)
_CHECK_PISO_POSTGRES = r"piso_versao ~ '^\d+\.\d+\.\d+$'"


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("repo") as lote:
            lote.drop_constraint("ck_repo_piso_versao", type_="check")
            lote.drop_column("piso_versao")
            lote.drop_column("tickio_sistema_id")
        return
    op.drop_constraint("ck_repo_piso_versao", "repo")
    op.drop_column("repo", "piso_versao")
    op.drop_column("repo", "tickio_sistema_id")


def downgrade() -> None:
    colunas = (
        sa.Column(
            "tickio_sistema_id", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("piso_versao", sa.String(), nullable=False, server_default="13.0.0"),
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("repo") as lote:
            for coluna in colunas:
                lote.add_column(coluna)
            lote.create_check_constraint("ck_repo_piso_versao", _CHECK_PISO_SQLITE)
        return
    for coluna in colunas:
        op.add_column("repo", coluna)
    op.execute(
        f"alter table repo add constraint ck_repo_piso_versao "
        f"check ({_CHECK_PISO_POSTGRES})"
    )
