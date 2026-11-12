"""Carregamento do ambiente: config central, `.env` e shell."""

from __future__ import annotations

import os

import dotenv
import pytest

import motor.__main__ as cli

_CHAVES = ("BITBUCKET_EMAIL", "WORKTREES_MANTIDAS")


@pytest.mark.parametrize(
    ("argv", "arquivo"),
    [([], ".env"), (["--env", "development"], ".env.development")],
)
def test_carrega_env_do_diretorio_atual(tmp_path, monkeypatch, argv, arquivo):
    for chave in _CHAVES:
        monkeypatch.setenv(chave, "antes")
    (tmp_path / arquivo).write_text(
        "".join(f"{c}=do_{c.lower()}\n" for c in _CHAVES), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_dotenv", dotenv.load_dotenv)

    cli._carregar_ambiente(argv)

    assert os.environ["BITBUCKET_EMAIL"] == "do_bitbucket_email"
    assert os.environ["WORKTREES_MANTIDAS"] == "do_worktrees_mantidas"


# --- [ambiente] do config central ---

CHAVE = "CHAVE_DE_PRECEDENCIA"


def _limpar_no_fim(monkeypatch, *chaves):
    """Registra a limpeza do que o `_carregar_ambiente` vai exportar."""
    for chave in chaves:
        monkeypatch.setenv(chave, "")
        monkeypatch.delenv(chave)


def _central(tmp_path, monkeypatch, texto, nome="xdg"):
    xdg = tmp_path / nome
    (xdg / "monitor-versoes").mkdir(parents=True)
    (xdg / "monitor-versoes" / "config.toml").write_text(texto, encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    return xdg


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    """Diretório atual em tmp_path, com o `load_dotenv` de verdade."""
    pasta = tmp_path / "cwd"
    pasta.mkdir()
    monkeypatch.chdir(pasta)
    monkeypatch.setattr(cli, "load_dotenv", dotenv.load_dotenv)
    return pasta


@pytest.mark.parametrize(
    ("no_central", "no_env", "esperado"),
    [(True, True, "central"), (False, True, "env"), (False, False, "shell")],
    ids=["central-vence", "env-vence-shell", "so-shell"],
)
def test_precedencia_central_env_shell(
    tmp_path, monkeypatch, cwd, no_central, no_env, esperado
):
    monkeypatch.setenv(CHAVE, "shell")
    _central(tmp_path, monkeypatch, f'[ambiente]\n{CHAVE} = "central"\n' * no_central)
    if no_env:
        (cwd / ".env").write_text(f"{CHAVE}=env\n")

    cli._carregar_ambiente([])

    assert os.environ[CHAVE] == esperado


def test_ambiente_central_vence_o_env_development(tmp_path, monkeypatch, cwd):
    monkeypatch.setenv("WORKTREES_MANTIDAS", "")
    _central(tmp_path, monkeypatch, '[ambiente]\nWORKTREES_MANTIDAS = "5"\n')
    (cwd / ".env.development").write_text("WORKTREES_MANTIDAS=4\n")

    cli._carregar_ambiente(["--env", "development"])

    assert os.environ["WORKTREES_MANTIDAS"] == "5"


def test_xdg_do_env_nao_muda_o_central_lido(tmp_path, monkeypatch, cwd):
    _limpar_no_fim(monkeypatch, CHAVE)
    herdado = _central(tmp_path, monkeypatch, f'[ambiente]\n{CHAVE} = "herdado"\n')
    outro = _central(tmp_path, monkeypatch, f'[ambiente]\n{CHAVE} = "outro"\n', "o")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(herdado))
    (cwd / ".env").write_text(f"XDG_CONFIG_HOME={outro}\n")

    cli._carregar_ambiente([])

    assert os.environ[CHAVE] == "herdado"
    assert os.environ["XDG_CONFIG_HOME"] == str(herdado)


@pytest.mark.parametrize(
    ("flag", "esperado"), [([], "do-central"), (["--bitbucket-token", "flag"], "flag")]
)
def test_bitbucket_token_do_central_e_default_da_flag(
    tmp_path, monkeypatch, cwd, flag, esperado
):
    monkeypatch.setenv("BITBUCKET_TOKEN", "")
    _central(tmp_path, monkeypatch, '[ambiente]\nBITBUCKET_TOKEN = "do-central"\n')

    cli._carregar_ambiente([])
    args = cli._build_parser().parse_args(["verificar", "1.0.0", "--repo", "r", *flag])

    assert args.bitbucket_token == esperado


def test_inscricao_executar_ignora_o_env_do_diretorio(tmp_path, monkeypatch, cwd):
    _limpar_no_fim(monkeypatch, CHAVE)
    monkeypatch.setenv("WORKTREES_MANTIDAS", "")
    _central(tmp_path, monkeypatch, f'[ambiente]\n{CHAVE} = "central"\n')
    (cwd / ".env").write_text("WORKTREES_MANTIDAS=5\n")

    cli._carregar_ambiente(["inscricao", "executar", "1.0.0", "--repo", "r"])

    assert os.environ["WORKTREES_MANTIDAS"] == ""
    assert os.environ[CHAVE] == "central"
