from alembic import context
from sqlalchemy import create_engine, pool

from motor.adapters.estado.models import Base
from motor.config import database_url

config = context.config

target_metadata = Base.metadata

# Nunca via config.set_main_option: configparser interpola "%", e um caminho
# com "%" quebraria com ValueError. A url vai direto para o engine.
#
# `attributes["url"]` vem de quem chama por codigo (primeiro uso, testes e
# `make migracao`); sem ele, a URL sai da config, que recusa backend antigo.
url = config.attributes.get("url") or database_url()


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=url.startswith("sqlite"),
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        # batch: o SQLite nao tem ALTER para constraint; a revisao recria a
        # tabela. FKs ficam desligadas aqui (padrao do SQLite) pelo mesmo motivo.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
