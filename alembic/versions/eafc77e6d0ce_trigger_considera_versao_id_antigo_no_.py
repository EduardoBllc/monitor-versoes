"""trigger considera versao_id antigo no update e liberada_em passa a timestamptz

Revision ID: eafc77e6d0ce
Revises: bae96c9be3c9
Create Date: 2026-08-18 16:22:29.823192

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eafc77e6d0ce'
down_revision: Union[str, Sequence[str], None] = 'bae96c9be3c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # A versao anterior so olhava new.versao_id: um UPDATE que move uma
    # atribuicao PARA FORA de uma versao liberada (new = versao aberta,
    # old = versao liberada) passava o guard e esvaziava silenciosamente
    # o snapshot congelado. Agora checa old e new.
    op.execute("""
        create or replace function trava_versao_liberada() returns trigger as $$
        begin
          if tg_op != 'INSERT' and exists (
            select 1 from versao where id = old.versao_id and liberada_em is not null
          ) then
            raise exception 'versao liberada e imutavel (versao_id=%)', old.versao_id;
          end if;
          if tg_op != 'DELETE' and exists (
            select 1 from versao where id = new.versao_id and liberada_em is not null
          ) then
            raise exception 'versao liberada e imutavel (versao_id=%)', new.versao_id;
          end if;
          if tg_op = 'DELETE' then return old; else return new; end if;
        end $$ language plpgsql;
    """)
    # liberada_em vem da data do commit da tag, que carrega fuso: coluna
    # naive descartava o offset silenciosamente.
    op.alter_column("versao", "liberada_em", type_=sa.DateTime(timezone=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("versao", "liberada_em", type_=sa.DateTime(timezone=False))
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
