"""errcode na trigger, checks de dominio e nome da constraint de versao

Tres dividas, todas do mesmo tipo: invariante que existia so em comentario ou
so em texto.

Revision ID: c31ffb4de7a1
Revises: eafc77e6d0ce
Create Date: 2026-08-19

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c31ffb4de7a1"
down_revision: str | Sequence[str] | None = "eafc77e6d0ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Igual a ERRCODE_VERSAO_CONGELADA em motor/adapters/estado/postgres.py.
# Classe MV: nao colide com nenhuma classe do padrao (Appendix A do Postgres).
ERRCODE = "MV001"

_TABELAS = ("atribuicao", "atribuicao_commit")
_EVENTOS = ("insert", "update", "delete")


def _liberada(coluna: str) -> str:
    return (
        f"exists (select 1 from versao where id = {coluna} and liberada_em is not null)"
    )


def _remover_triggers_sqlite() -> None:
    # O batch recria `versao` (drop + rename) e o SQLite recusa o rename com
    # trigger apontando para a tabela: sai antes, volta depois. Mesma definicao
    # de bae96c9be3c9 (copiada: migration nao importa de outra).
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
                f"begin select raise(abort, '{ERRCODE}: versao liberada e imutavel'); end"
            )


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        # Sem errcode nem rename constraint: o marcador MV001 ja esta na
        # mensagem das triggers; o resto e recriacao em lote.
        _remover_triggers_sqlite()
        with op.batch_alter_table("versao") as lote:
            lote.drop_constraint("uq_versao_repo_id", type_="unique")
            lote.create_unique_constraint(
                "uq_versao_repo_id_numero", ["repo_id", "numero"]
            )
            lote.create_check_constraint(
                "ck_versao_tipo", "tipo in ('fechada', 'ajustada', 'cliente')"
            )
        with op.batch_alter_table("atribuicao") as lote:
            lote.create_check_constraint(
                "ck_atribuicao_estado", "estado in ('pendente', 'aplicado')"
            )
        _recriar_triggers_sqlite()
        return

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
    if op.get_bind().dialect.name == "sqlite":
        _remover_triggers_sqlite()
        with op.batch_alter_table("atribuicao") as lote:
            lote.drop_constraint("ck_atribuicao_estado", type_="check")
        with op.batch_alter_table("versao") as lote:
            lote.drop_constraint("ck_versao_tipo", type_="check")
            lote.drop_constraint("uq_versao_repo_id_numero", type_="unique")
            lote.create_unique_constraint("uq_versao_repo_id", ["repo_id", "numero"])
        _recriar_triggers_sqlite()
        return
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
