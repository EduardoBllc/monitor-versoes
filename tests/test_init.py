"""`motor init` e o carregamento do `.env` do diretório atual."""

from __future__ import annotations

from pathlib import Path

import dotenv
import pytest

import motor.__main__ as cli
from motor.init import iniciar

MODELOS = Path(cli.__file__).parent / "modelos"
COMPOSE = (MODELOS / "compose.yml").read_text(encoding="utf-8")
ENV = (MODELOS / "env.example").read_text(encoding="utf-8")


def test_diretorio_vazio_cria_os_dois(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    cli.main(["init"])

    assert (tmp_path / "compose.yml").read_text(encoding="utf-8") == COMPOSE
    assert (tmp_path / ".env").read_text(encoding="utf-8") == ENV


@pytest.mark.parametrize("existente", ["compose.yml", ".env"])
def test_arquivo_existente_fica_intacto(tmp_path, existente):
    (tmp_path / existente).write_text("meu", encoding="utf-8")

    mensagens = iniciar(tmp_path)

    assert (tmp_path / existente).read_text(encoding="utf-8") == "meu"
    assert f"{existente} já existe; mantido" in mensagens
    outro, conteudo = (
        (".env", ENV) if existente == "compose.yml" else ("compose.yml", COMPOSE)
    )
    assert (tmp_path / outro).read_text(encoding="utf-8") == conteudo


_CHAVES = ("HOST", "PORT", "NAME", "USER", "PASSWORD")


@pytest.mark.parametrize(
    ("argv", "arquivo"),
    [([], ".env"), (["--env", "development"], ".env.development")],
)
def test_carrega_env_do_diretorio_atual(tmp_path, monkeypatch, argv, arquivo):
    for chave in _CHAVES:
        monkeypatch.setenv(f"DATABASE_{chave}", "antes")
    (tmp_path / arquivo).write_text(
        "".join(f"DATABASE_{c}=do_{c.lower()}\n" for c in _CHAVES), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_dotenv", dotenv.load_dotenv)

    cli._carregar_ambiente(argv)

    import os

    assert os.environ["DATABASE_HOST"] == "do_host"
    assert os.environ["DATABASE_PASSWORD"] == "do_password"
