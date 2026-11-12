from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest

_CAMPOS_POSTGRES = (
    "DATABASE_HOST",
    "DATABASE_PORT",
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
)


@pytest.fixture(autouse=True)
def _sem_dotenv_dentro_do_main(monkeypatch):
    """Guarda estrutural do "sem rede": desliga o load_dotenv() do main().

    Sem ela, `main()` repovoa o ambiente a cada invocacao e toda variavel que um
    teste apagou com `monkeypatch.delenv` volta do `.env` de produção — foi assim
    que um teste de credencial ausente saiu para o host real do rastreador na Task
    12. A disciplina de autor (usar `setenv("")` em vez de `delenv`) nao e
    guarda: ela vale ate o proximo teste escrito sem lembrar dela.

    A suíte também não carrega o `.env.development`: o ambiente de cada teste é
    o que `_estado_isolado` fixa, mais o que o próprio teste definir.
    """
    import motor.__main__ as cli

    monkeypatch.setattr(cli, "load_dotenv", None)


@pytest.fixture(autouse=True)
def _estado_isolado(monkeypatch, tmp_path):
    """Nenhum teste lê ou grava estado fora de `tmp_path`.

    A suíte não depende do `.env.development` nem do shell de quem a roda: o
    SQLite é o mesmo arquivo da `sessao_sqlite`; as variáveis de backend antigas
    ficam vazias (um `.env.development` com Postgres não muda resultado nenhum),
    e as credenciais também, para nenhum teste sair para a rede por acaso.
    """
    monkeypatch.setenv("DATABASE_SQLITE_PATH", str(tmp_path / "estado.db"))
    for nome in ("DATABASE_BACKEND", *_CAMPOS_POSTGRES, "WORKTREES_MANTIDAS"):
        monkeypatch.setenv(nome, "")
    monkeypatch.setenv("BITBUCKET_TOKEN", "")
    monkeypatch.setenv("BITBUCKET_EMAIL", "")


@pytest.fixture(autouse=True)
def _config_central_isolado(monkeypatch, tmp_path):
    """Nenhum teste lê o `config.toml` real de quem roda a suíte.

    O `main()` aplica o `[ambiente]` do central: sem isolar, o banco e as
    credenciais da máquina entrariam no teste. Quem precisa de um central
    próprio sobrescreve o `XDG_CONFIG_HOME`.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-isolado"))


@pytest.fixture(autouse=True)
def _ambiente_central_reiniciado():
    """Cada teste começa sem base nem chaves aplicadas do `[ambiente]`."""
    from motor.config import _reiniciar_ambiente_base

    _reiniciar_ambiente_base()
    yield
    _reiniciar_ambiente_base()


@pytest.fixture(autouse=True)
def _os_environ_restaurado():
    """`gravar` aplica o `[ambiente]` em `os.environ`; nada vaza entre testes."""
    antes = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(antes)


@pytest.fixture(autouse=True)
def _travas_isoladas(monkeypatch, tmp_path):
    """Os locks de repo da suíte ficam no `tmp_path`, não em `~/.local/share`.

    Sem isso, um teste que trava um clone gravaria no diretório de dados de
    quem roda, e uma operação real dessa máquina recusaria o teste (ou o
    contrário).
    """
    import motor.trava

    monkeypatch.setattr(motor.trava, "diretorio_travas", lambda: tmp_path / "travas")


@pytest.fixture
def sessao_sqlite(tmp_path: Any) -> Iterator[Any]:
    """Sessao contra um SQLite novo em `tmp_path`, migrado como no primeiro uso.

    O arquivo é o mesmo que `_estado_isolado` aponta em `DATABASE_SQLITE_PATH`.
    """
    from sqlalchemy.orm import Session

    from motor.adapters.estado.engine import criar_engine, garantir_esquema

    url = f"sqlite:///{tmp_path / 'estado.db'}"
    garantir_esquema(url)
    engine = criar_engine(url)
    try:
        with Session(engine) as sessao:
            yield sessao
    finally:
        engine.dispose()
