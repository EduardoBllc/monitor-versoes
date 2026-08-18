"""trigger de congelamento de versao liberada

Revision ID: bae96c9be3c9
Revises: a2c11a78f505
Create Date: 2026-08-18 16:07:55.951711

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bae96c9be3c9'
down_revision: Union[str, Sequence[str], None] = 'a2c11a78f505'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
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
    op.execute("drop trigger if exists atribuicao_commit_congelada on atribuicao_commit")
    op.execute("drop trigger if exists atribuicao_congelada on atribuicao")
    op.execute("drop function if exists trava_versao_liberada()")
