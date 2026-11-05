"""Diagnóstico da instalação, sem banco real nem rede."""

from __future__ import annotations

import contextlib
import os

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from motor.config import ConfigProjeto, carregar_config
from motor.diagnostico import (
    Estado,
    Resultado,
    diagnosticar,
    falhou,
)
from motor.errors import ErroDeEntrada
from motor.migracoes import head

HEAD = "rev2"
ENV_OK = {
    "DATABASE_BACKEND": "postgres",
    "DATABASE_HOST": "h",
    "DATABASE_PORT": "5433",
    "DATABASE_NAME": "n",
    "DATABASE_USER": "u",
    "DATABASE_PASSWORD": "senha-secreta",
}


def _sessao_com(revisao: str | None):
    @contextlib.contextmanager
    def abrir(garantir=True):
        with Session(create_engine("sqlite://")) as sessao:
            if revisao is not None:
                sessao.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
                sessao.execute(
                    text("INSERT INTO alembic_version VALUES (:r)"), {"r": revisao}
                )
            yield sessao

    return abrir


@contextlib.contextmanager
def _banco_fora(garantir=True):
    class _Quebra(Session):
        def execute(self, *a, **k):
            raise OperationalError("select 1", None, Exception("connection refused"))

    with _Quebra(create_engine("sqlite://")) as sessao:
        yield sessao


def _abrir_proibido(garantir=True):
    raise AssertionError("não devia abrir sessão")


def _bitbucket_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"access": "tok"})


def _cliente(handler=_bitbucket_ok) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _sem_fonte() -> ConfigProjeto:
    return ConfigProjeto()


def _rodar(
    env=None,
    *,
    abrir=None,
    ambiente="production",
    handler=_bitbucket_ok,
    config_central=_sem_fonte,
):
    resultados = diagnosticar(
        ENV_OK if env is None else env,
        abrir_sessao=abrir or _sessao_com(HEAD),
        head=HEAD,
        ambiente=ambiente,
        config_central=config_central,
        cliente=_cliente(handler),
    )
    return {r.peca: r for r in resultados}, resultados


def test_head_e_uma_das_revisoes_dos_scripts():
    versoes = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "motor", "migracoes", "versions"
    )
    revisoes = {f.split("_", 1)[0] for f in os.listdir(versoes) if f.endswith(".py")}

    assert head() in revisoes


def test_instalacao_integra():
    por_peca, resultados = _rodar()

    assert not falhou(resultados)
    assert [r.peca for r in resultados] == [
        "Variáveis",
        "Postgres",
        "Migração",
        "PROJECTS_DIR",
        "Tarefas",
        "Bitbucket",
    ]
    assert por_peca["Tarefas"].estado is Estado.NAO_CONFIGURADO
    assert por_peca["PROJECTS_DIR"].estado is Estado.NAO_CONFIGURADO
    assert por_peca["Bitbucket"].estado is Estado.NAO_CONFIGURADO


def test_postgres_fora():
    por_peca, resultados = _rodar(abrir=_banco_fora)

    assert falhou(resultados)
    assert por_peca["Postgres"].estado is Estado.FALHA
    assert "docker compose up -d" in por_peca["Postgres"].correcao
    assert por_peca["Migração"].estado is Estado.NAO_VERIFICADA
    assert por_peca["Tarefas"].estado is Estado.NAO_CONFIGURADO


@pytest.mark.parametrize("revisao", [None, "antiga"])
def test_migracao_pendente(revisao):
    por_peca, _ = _rodar(abrir=_sessao_com(revisao))

    assert por_peca["Migração"].estado is Estado.FALHA
    assert por_peca["Migração"].correcao == "make migrate"


def test_migracao_em_desenvolvimento_usa_migrate_dev():
    por_peca, _ = _rodar(abrir=_sessao_com(None), ambiente="development")

    assert por_peca["Migração"].correcao == "make migrate-dev"


@pytest.mark.parametrize("porta", ["", "abc"])
def test_variaveis_do_banco_invalidas_nao_abrem_sessao(porta):
    env = {**ENV_OK, "DATABASE_PORT": porta}

    por_peca, _ = _rodar(env, abrir=_abrir_proibido)

    assert por_peca["Variáveis"].estado is Estado.FALHA
    assert "DATABASE_PORT" in por_peca["Variáveis"].detalhe
    assert por_peca["Postgres"].estado is Estado.NAO_VERIFICADA
    assert por_peca["Migração"].estado is Estado.NAO_VERIFICADA


def test_projects_dir(tmp_path):
    existente, _ = _rodar({**ENV_OK, "PROJECTS_DIR": str(tmp_path)})
    inexistente, _ = _rodar({**ENV_OK, "PROJECTS_DIR": str(tmp_path / "nao")})

    assert existente["PROJECTS_DIR"].estado is Estado.OK
    assert inexistente["PROJECTS_DIR"].estado is Estado.FALHA
    assert inexistente["PROJECTS_DIR"].correcao


def test_bitbucket_sem_token_nao_faz_rede():
    def handler(request):
        if "bitbucket" in str(request.url):
            raise AssertionError("sem rede")
        return _bitbucket_ok(request)

    por_peca, _ = _rodar(handler=handler)

    assert por_peca["Bitbucket"].estado is Estado.NAO_CONFIGURADO


def test_bitbucket_token_recusado_e_aceito():
    def recusa(request):
        if "bitbucket" in str(request.url):
            return httpx.Response(401)
        return _bitbucket_ok(request)

    env = {**ENV_OK, "BITBUCKET_TOKEN": "tok", "BITBUCKET_EMAIL": "a@b.c"}

    recusado, resultados = _rodar(env, handler=recusa)
    aceito, _ = _rodar(env, handler=lambda r: httpx.Response(200, json={"access": "t"}))
    sem_email, _ = _rodar({**ENV_OK, "BITBUCKET_TOKEN": "tok"})

    assert recusado["Bitbucket"].estado is Estado.FALHA
    assert falhou(resultados)
    assert aceito["Bitbucket"].estado is Estado.OK
    assert sem_email["Bitbucket"].estado is Estado.FALHA


def test_falhas_independentes_no_mesmo_relatorio(tmp_path):
    env = {**ENV_OK, "PROJECTS_DIR": str(tmp_path / "nao")}

    por_peca, _ = _rodar(env, abrir=_banco_fora)

    assert por_peca["PROJECTS_DIR"].estado is Estado.FALHA
    assert por_peca["Postgres"].estado is Estado.FALHA


def test_credenciais_nunca_aparecem():
    env = {**ENV_OK, "BITBUCKET_TOKEN": "bb-secreto", "BITBUCKET_EMAIL": "a@b.c"}

    _, resultados = _rodar(env, handler=lambda r: httpx.Response(401))
    texto = " ".join(f"{r.detalhe} {r.correcao}" for r in resultados)

    for segredo in ("senha-secreta", "bb-secreto"):
        assert segredo not in texto


def test_nao_verificada_e_nao_configurado_nao_falham():
    assert not falhou(
        [
            Resultado("a", Estado.NAO_VERIFICADA),
            Resultado("b", Estado.NAO_CONFIGURADO),
        ]
    )


ENV_SQLITE = {k: v for k, v in ENV_OK.items() if not k.startswith("DATABASE_")}


def test_sqlite_nao_exige_partes_do_banco_e_rotula_o_backend():
    por_peca, resultados = _rodar(ENV_SQLITE)

    assert not falhou(resultados)
    assert "Postgres" not in por_peca
    assert por_peca["SQLite"].estado is Estado.OK
    assert por_peca["Migração"].estado is Estado.OK


def test_sqlite_sem_migracao_nao_sugere_docker_nem_make():
    por_peca, _ = _rodar(ENV_SQLITE, abrir=_sessao_com(None))

    assert por_peca["Migração"].estado is Estado.FALHA
    assert "docker" not in por_peca["Migração"].correcao


def test_sqlite_fora_nao_sugere_docker():
    por_peca, _ = _rodar(ENV_SQLITE, abrir=_banco_fora)

    assert por_peca["SQLite"].estado is Estado.FALHA
    assert "docker" not in por_peca["SQLite"].correcao
    assert por_peca["Migração"].estado is Estado.NAO_VERIFICADA


def test_backend_desconhecido_e_variavel_invalida():
    por_peca, _ = _rodar(
        {**ENV_SQLITE, "DATABASE_BACKEND": "mysql"}, abrir=_abrir_proibido
    )

    assert por_peca["Variáveis"].estado is Estado.FALHA
    assert "DATABASE_BACKEND" in por_peca["Variáveis"].detalhe


# -- linha Tarefas --------------------------------------------------------------

_PLUGINS = "conferir [tarefas] fonte e os plugins instalados"


@pytest.mark.parametrize(
    ("fonte", "token", "estado", "correcao"),
    [
        (
            None,
            "",
            Estado.NAO_CONFIGURADO,
            "definir [tarefas] fonte no config.toml central",
        ),
        ("inexistente", "", Estado.FALHA, _PLUGINS),
        ("tests.fontes_falsas:FonteConstrutorQuebra", "", Estado.FALHA, _PLUGINS),
        ("tests.fontes_falsas:FonteFixa", "", Estado.NAO_VERIFICADA, ""),
        ("tests.fontes_falsas:FonteComCredencial", "certo", Estado.OK, ""),
        (
            "tests.fontes_falsas:FonteComCredencial",
            "errado",
            Estado.FALHA,
            "conferir as credenciais da fonte no .env",
        ),
    ],
    ids=[
        "sem-fonte",
        "plugin-nao-carrega",
        "construtor-levanta",
        "sem-verificacao",
        "credencial-aceita",
        "credencial-recusada",
    ],
)
def test_linha_tarefas_por_estado(
    tmp_path, monkeypatch, fonte, token, estado, correcao
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("FONTE_FALSA_TOKEN", token)
    central = tmp_path / "monitor-versoes" / "config.toml"
    central.parent.mkdir()
    central.write_text("" if fonte is None else f'[tarefas]\nfonte = "{fonte}"\n')

    por_peca, resultados = _rodar(config_central=lambda: carregar_config(None))

    linha = por_peca["Tarefas"]
    assert linha.estado is estado
    assert linha.correcao == correcao
    assert falhou(resultados) is (estado is Estado.FALHA)


def test_linha_tarefas_cita_a_mensagem_da_falha(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    central = tmp_path / "monitor-versoes" / "config.toml"
    central.parent.mkdir()
    central.write_text(
        '[tarefas]\nfonte = "tests.fontes_falsas:FonteConstrutorQuebra"\n'
    )

    por_peca, _ = _rodar(config_central=lambda: carregar_config(None))

    assert "construtor quebrou" in por_peca["Tarefas"].detalhe


def test_config_central_invalida_falha_so_na_linha_tarefas():
    def invalida() -> ConfigProjeto:
        raise ErroDeEntrada("config.toml: TOML invalido")

    por_peca, resultados = _rodar(config_central=invalida)

    assert por_peca["Tarefas"].estado is Estado.FALHA
    assert "TOML invalido" in por_peca["Tarefas"].detalhe
    assert [r.peca for r in resultados] == [
        "Variáveis",
        "Postgres",
        "Migração",
        "PROJECTS_DIR",
        "Tarefas",
        "Bitbucket",
    ]
    outras = [r for r in resultados if r.peca != "Tarefas"]
    assert all(r.estado is not Estado.FALHA for r in outras)
