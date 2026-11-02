"""trigger de congelamento de versao liberada

Revision ID: bae96c9be3c9
Revises: a2c11a78f505
Create Date: 2026-08-18 16:07:55.951711

"""

from collections.abc import Sequence

from alembic import op

# Marcador estavel que o adapter procura na mensagem do SQLite (sem errcode).
MARCADOR = "MV001"

_EVENTOS_SQLITE = {
    "insert": "new.versao_id",
    "update": "old.versao_id",
    "delete": "old.versao_id",
}
_TABELAS = ("atribuicao", "atribuicao_commit")


def _liberada(coluna: str) -> str:
    return (
        f"exists (select 1 from versao where id = {coluna} and liberada_em is not null)"
    )


def _triggers_sqlite() -> None:
    # SQLite nao tem trigger multi-evento nem errcode: uma por evento, e a
    # recusa carrega o marcador na mensagem. UPDATE olha old e new (mover linha
    # PARA FORA de versao liberada tambem e recusado).
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
                f"begin select raise(abort, '{MARCADOR}: versao liberada e imutavel'); end"
            )


# revision identifiers, used by Alembic.
revision: str = "bae96c9be3c9"
down_revision: str | Sequence[str] | None = "a2c11a78f505"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    if op.get_bind().dialect.name == "sqlite":
        _triggers_sqlite()
        return
    op.execute("""
        create or replace function trava_versao_liberada() returns trigger as $$
        declare vid int;
        begin
          if tg_op = 'DELETE' then vid := old.versao_id; else vid := new.versao_id; end if;
          if exists (select 1 from versao where id = vid and liberada_em is not null) then
            raise exception 'versao liberada e imutavel (versao_id=%)', vid;
          end if;
          if tg_op = 'DELETE' then return old; else return new; end if;
        end $$ language plpgsql;
    """)
    op.execute("""
        create trigger atribuicao_congelada
          before insert or update or delete on atribuicao
          for each row execute function trava_versao_liberada();
    """)
    op.execute("""
        create trigger atribuicao_commit_congelada
          before insert or update or delete on atribuicao_commit
          for each row execute function trava_versao_liberada();
    """)


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name == "sqlite":
        for tabela in _TABELAS:
            for evento in _EVENTOS_SQLITE:
                op.execute(f"drop trigger if exists {tabela}_congelada_{evento}")
        return
    op.execute(
        "drop trigger if exists atribuicao_commit_congelada on atribuicao_commit"
    )
    op.execute("drop trigger if exists atribuicao_congelada on atribuicao")
    op.execute("drop function if exists trava_versao_liberada()")
