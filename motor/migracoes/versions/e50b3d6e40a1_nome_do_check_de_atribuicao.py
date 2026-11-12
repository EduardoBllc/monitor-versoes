"""nome do check de atribuicao

O check de `atribuicao.estado` nasceu com o nome já prefixado
(`ck_atribuicao_estado`), e a convenção de nomes do `MetaData` o prefixou de
novo: no banco ele se chama `ck_atribuicao_ck_atribuicao_estado`. Esta revisão
dá a ele o nome que a convenção gera a partir de `name="estado"`, o mesmo do
modelo, para o autogenerate não ver diferença.

Revision ID: e50b3d6e40a1
Revises: c9d2e4f6a8b0

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "e50b3d6e40a1"
down_revision: str | Sequence[str] | None = "c9d2e4f6a8b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "estado in ('pendente', 'aplicado')"


def _trocar_nome_do_check(de: str, para: str) -> None:
    # O batch recria `atribuicao` (cópia, drop, rename), e o drop leva junto as
    # triggers de congelamento. Elas são guardadas antes e recriadas idênticas.
    # As de `atribuicao_commit` também, porque citam `atribuicao` no corpo.
    #
    # Os nomes vão em op.f(...): com o target_metadata do env.py, nome cru
    # recebe a convenção de novo, e o drop procuraria
    # 'ck_atribuicao_ck_atribuicao_ck_atribuicao_estado'.
    conexao = op.get_bind()
    triggers = conexao.execute(
        text("select name, sql from sqlite_master where type = 'trigger'")
    ).all()
    for nome, _ in triggers:
        op.execute(f'drop trigger "{nome}"')
    with op.batch_alter_table("atribuicao") as batch:
        batch.drop_constraint(op.f(de), type_="check")
        batch.create_check_constraint(op.f(para), _CHECK)
    for _, sql in triggers:
        op.execute(sql)


def upgrade() -> None:
    _trocar_nome_do_check("ck_atribuicao_ck_atribuicao_estado", "ck_atribuicao_estado")


def downgrade() -> None:
    _trocar_nome_do_check("ck_atribuicao_estado", "ck_atribuicao_ck_atribuicao_estado")
