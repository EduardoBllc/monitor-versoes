"""errcode na trigger, checks de dominio e nome da constraint de versao

Tres divida registradas na §15 do desenho, todas do mesmo tipo: invariante que
existia so em comentario ou so em texto.

Revision ID: c31ffb4de7a1
Revises: eafc77e6d0ce
Create Date: 2026-08-19

"""
from typing import Sequence, Union

from alembic import op

revision: str = "c31ffb4de7a1"
down_revision: Union[str, Sequence[str], None] = "eafc77e6d0ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Igual a ERRCODE_VERSAO_CONGELADA em motor/adapters/estado/postgres.py.
# Classe MV: nao colide com nenhuma classe do padrao (Appendix A do Postgres).
ERRCODE = "MV001"


def upgrade() -> None:
    # 1. A trigger passa a levantar com errcode proprio. Antes o adapter
    # identificava o congelamento por `"imutavel" in str(e.orig)`, entao
    # reescrever esta mensagem quebrava a traducao em silencio, em outro arquivo.
    op.execute(f"""
        create or replace function trava_versao_liberada() returns trigger as $$
        begin
          if tg_op != 'INSERT' and exists (
            select 1 from versao where id = old.versao_id and liberada_em is not null
          ) then
            raise exception 'versao liberada e imutavel (versao_id=%)', old.versao_id
              using errcode = '{ERRCODE}';
          end if;
          if tg_op != 'DELETE' and exists (
            select 1 from versao where id = new.versao_id and liberada_em is not null
          ) then
            raise exception 'versao liberada e imutavel (versao_id=%)', new.versao_id
              using errcode = '{ERRCODE}';
          end if;
          if tg_op = 'DELETE' then return old; else return new; end if;
        end $$ language plpgsql;
    """)

    # 2. `uq_versao_repo_id` vinha da convencao de nomes, que so ve column_0 —
    # nome que le como se repo_id sozinho fosse unico, quando a constraint e
    # (repo_id, numero). Um repo tem muitas versoes; o nome dizia o contrario.
    op.execute(
        "alter table versao rename constraint uq_versao_repo_id "
        "to uq_versao_repo_id_numero"
    )

    # 3. `tipo` e `estado` eram texto livre com os valores legais so em
    # comentario do model, num schema cuja razao de existir e ser consultado e
    # corrigido via psql. Valor digitado errado passava no insert e so estourava
    # na LEITURA, como KeyError longe da causa.
    op.execute(
        "alter table versao add constraint ck_versao_tipo "
        "check (tipo in ('fechada', 'ajustada', 'cliente'))"
    )
    op.execute(
        "alter table atribuicao add constraint ck_atribuicao_estado "
        "check (estado in ('pendente', 'aplicado'))"
    )


def downgrade() -> None:
    op.execute("alter table atribuicao drop constraint ck_atribuicao_estado")
    op.execute("alter table versao drop constraint ck_versao_tipo")
    op.execute(
        "alter table versao rename constraint uq_versao_repo_id_numero "
        "to uq_versao_repo_id"
    )
    # trigger volta ao corpo de eafc77e6d0ce, sem errcode
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
