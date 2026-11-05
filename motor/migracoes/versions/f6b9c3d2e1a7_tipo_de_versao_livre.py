"""tipo de versão livre

O tipo passa a ser o rótulo que o esquema de versão dá (ou nenhum): sai o check
com os três tipos de um esquema só e a coluna aceita null. Linhas existentes não
mudam.

Revision ID: f6b9c3d2e1a7
Revises: f6b9c2d3e4a5

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6b9c3d2e1a7"
down_revision: str | Sequence[str] | None = "f6b9c2d3e4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK_ANTIGO = "tipo in ('fechada', 'ajustada', 'cliente')"

_TABELAS = ("atribuicao", "atribuicao_commit")
_EVENTOS = ("insert", "update", "delete")


def _liberada(coluna: str) -> str:
    return (
        f"exists (select 1 from versao where id = {coluna} and liberada_em is not null)"
    )


def _remover_triggers_sqlite() -> None:
    # O batch recria `versao` (drop + rename) e o SQLite recusa o rename com
    # trigger apontando para a tabela: sai antes, volta depois. Mesma definição
    # de c31ffb4de7a1 (copiada: migration não importa de outra).
    for tabela in _TABELAS:
        for evento in _EVENTOS:
            op.execute(f"drop trigger if exists {tabela}_congelada_{evento}")


def _recriar_triggers_sqlite() -> None:
    condicoes = {
        "insert": _liberada("new.versao_id"),
        "update": f"{_liberada('old.versao_id')} or {_liberada('new.versao_id')}",
        "delete": _liberada("old.versao_id"),
    }
    for tabela in _TABELAS:
        for evento, condicao in condicoes.items():
            op.execute(
                f"create trigger {tabela}_congelada_{evento} "
                f"before {evento} on {tabela} for each row when {condicao} "
                f"begin select raise(abort, 'MV001: versao liberada e imutavel'); end"
            )


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _remover_triggers_sqlite()
        with op.batch_alter_table("versao") as lote:
            lote.drop_constraint("ck_versao_tipo", type_="check")
            lote.alter_column("tipo", existing_type=sa.String(), nullable=True)
        _recriar_triggers_sqlite()
        return
    op.execute("alter table versao drop constraint ck_versao_tipo")
    op.execute("alter table versao alter column tipo drop not null")


def downgrade() -> None:
    # Versão sem tipo ou com rótulo fora do trio não cabe no schema antigo: o
    # downgrade falha nela em vez de inventar um tipo.
    if op.get_bind().dialect.name == "sqlite":
        _remover_triggers_sqlite()
        with op.batch_alter_table("versao") as lote:
            lote.alter_column("tipo", existing_type=sa.String(), nullable=False)
            lote.create_check_constraint("ck_versao_tipo", _CHECK_ANTIGO)
        _recriar_triggers_sqlite()
        return
    op.execute("alter table versao alter column tipo set not null")
    op.execute(
        f"alter table versao add constraint ck_versao_tipo check ({_CHECK_ANTIGO})"
    )
