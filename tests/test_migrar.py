"""`motor migrar`: banco real (integração) e erros sem Docker."""

from __future__ import annotations

import logging
import socket

import dotenv
import pytest

import motor.__main__ as cli
from motor.migracoes import head


def _porta_fechada() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return str(s.getsockname()[1])


def _apontar_para_porta_fechada(monkeypatch) -> None:
    for chave, valor in {
        "HOST": "127.0.0.1",
        "PORT": _porta_fechada(),
        "NAME": "x",
        "USER": "x",
        "PASSWORD": "x",
    }.items():
        monkeypatch.setenv(f"DATABASE_{chave}", valor)


@pytest.mark.integracao
def test_migrar_e_idempotente_e_chega_ao_head(_postgres_efemero, sessao_postgres):
    from motor.adapters.estado.postgres import PostgresEstado

    cli.main(["migrar"])
    cli.main(["migrar"])

    assert PostgresEstado(sessao=sessao_postgres).revisao_migracao() == head()


def test_migrar_com_banco_fora_do_ar_e_erro_do_motor(monkeypatch, caplog):
    _apontar_para_porta_fechada(monkeypatch)

    with pytest.raises(SystemExit) as saida:
        cli.main(["migrar"])

    assert saida.value.code == 1
    assert "Erro interno fatal" not in caplog.text
    assert "docker compose up -d" in caplog.text


def test_migrar_le_env_do_diretorio_atual(tmp_path, monkeypatch, caplog):
    (tmp_path / ".env").write_text(
        f"DATABASE_HOST=127.0.0.1\nDATABASE_PORT={_porta_fechada()}\n"
        "DATABASE_NAME=x\nDATABASE_USER=x\nDATABASE_PASSWORD=x\n",
        encoding="utf-8",
    )
    for chave in ("HOST", "PORT", "NAME", "USER", "PASSWORD"):
        monkeypatch.setenv(f"DATABASE_{chave}", "restaurar")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_dotenv", dotenv.load_dotenv)

    with pytest.raises(SystemExit):
        cli.main(["migrar"])

    assert "Erro interno fatal" not in caplog.text
    assert "docker compose up -d" in caplog.text


def test_migrar_com_env_development(tmp_path, monkeypatch, caplog):
    (tmp_path / ".env.development").write_text(
        f"DATABASE_HOST=127.0.0.1\nDATABASE_PORT={_porta_fechada()}\n"
        "DATABASE_NAME=x\nDATABASE_USER=x\nDATABASE_PASSWORD=x\n",
        encoding="utf-8",
    )
    for chave in ("HOST", "PORT", "NAME", "USER", "PASSWORD"):
        monkeypatch.setenv(f"DATABASE_{chave}", "restaurar")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_dotenv", dotenv.load_dotenv)

    with pytest.raises(SystemExit):
        cli.main(["--env", "development", "migrar"])

    assert "docker compose up -d" in caplog.text
    assert caplog.text.count("ERROR") == 1
    logging.getLogger().handlers.clear()
