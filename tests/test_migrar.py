"""`motor migrar`: banco real (integração) e erros sem Docker."""

from __future__ import annotations

import socket

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
