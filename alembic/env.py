from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import create_engine, pool

from alembic import context
from motor.adapters.estado.models import Base
from motor.config import database_url

load_dotenv()

config = context.config

# Chamado por codigo (`attributes["url"]`), o logging e do chamador: fileConfig
# desligaria os loggers ja configurados do motor.
if config.config_file_name is not None and "url" not in config.attributes:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Nunca via config.set_main_option: configparser interpola "%" e uma senha
# como "se%40nha%25x" (ja com quote() aplicado) quebra com ValueError antes
# de qualquer tentativa de conexao. A url vai direto para o engine.
#
# `attributes["url"]` vem de quem chama por codigo (primeiro uso e
# `migrar-estado`); sem ele, a URL sai da config, sem o aviso de backend padrao.
url = config.attributes.get("url") or database_url(avisar=False)


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
