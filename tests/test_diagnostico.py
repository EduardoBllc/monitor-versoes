"""Diagnóstico da instalação, sem banco real nem rede."""

from __future__ import annotations

import contextlib
import os

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from motor.diagnostico import (
    Estado,
    Resultado,
    diagnosticar,
    falhou,
)
from motor.migracoes import head

HEAD = "rev2"
ENV_OK = {
    "DATABASE_HOST": "h",
    "DATABASE_PORT": "5433",
    "DATABASE_NAME": "n",
    "DATABASE_USER": "u",
    "DATABASE_PASSWORD": "senha-secreta",
    "TICKIO_BASE_URL": "http://tickio",
    "TICKIO_USER": "u",
    "TICKIO_PASSWORD": "tickio-secreto",
}


def _sessao_com(revisao: str | None):
    @contextlib.contextmanager
    def abrir():
        with Session(create_engine("sqlite://")) as sessao:
            if revisao is not None:
                sessao.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
                sessao.execute(
                    text("INSERT INTO alembic_version VALUES (:r)"), {"r": revisao}
                )
            yield sessao

    return abrir


@contextlib.contextmanager
def _banco_fora():
    class _Quebra(Session):
        def execute(self, *a, **k):
            raise OperationalError("select 1", None, Exception("connection refused"))

    with _Quebra(create_engine("sqlite://")) as sessao:
        yield sessao


def _abrir_proibido():
    raise AssertionError("não devia abrir sessão")


def _tickio_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"access": "tok"})


def _cliente(handler=_tickio_ok) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _rodar(env=None, *, abrir=None, ambiente="production", handler=_tickio_ok):
    resultados = diagnosticar(
        ENV_OK if env is None else env,
        abrir_sessao=abrir or _sessao_com(HEAD),
        head=HEAD,
        ambiente=ambiente,
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
        "Tickio",
        "Bitbucket",
    ]
    assert por_peca["Tickio"].estado is Estado.OK
    assert por_peca["PROJECTS_DIR"].estado is Estado.NAO_CONFIGURADO
    assert por_peca["Bitbucket"].estado is Estado.NAO_CONFIGURADO


def test_postgres_fora():
    por_peca, resultados = _rodar(abrir=_banco_fora)

    assert falhou(resultados)
    assert por_peca["Postgres"].estado is Estado.FALHA
    assert "docker compose up -d" in por_peca["Postgres"].correcao
    assert por_peca["Migração"].estado is Estado.NAO_VERIFICADA
    assert por_peca["Tickio"].estado is Estado.OK


@pytest.mark.parametrize("revisao", [None, "antiga"])
def test_migracao_pendente(revisao):
    por_peca, _ = _rodar(abrir=_sessao_com(revisao))

    assert por_peca["Migração"].estado is Estado.FALHA
    assert por_peca["Migração"].correcao == "make migrate"


def test_migracao_em_desenvolvimento_usa_migrate_dev():
    por_peca, _ = _rodar(abrir=_sessao_com(None), ambiente="development")

    assert por_peca["Migração"].correcao == "make migrate-dev"


def test_variaveis_do_tickio_faltando_nao_chama_http():
    env = {k: v for k, v in ENV_OK.items() if not k.startswith("TICKIO_")}

    def handler(request):
        raise AssertionError("sem chamada HTTP")

    por_peca, resultados = _rodar(env, handler=handler)

    assert por_peca["Variáveis"].estado is Estado.FALHA
    for nome in ("TICKIO_BASE_URL", "TICKIO_USER", "TICKIO_PASSWORD"):
        assert nome in por_peca["Variáveis"].detalhe
    assert por_peca["Tickio"].estado is Estado.NAO_VERIFICADA
    assert por_peca["Postgres"].estado is Estado.OK
    assert falhou(resultados)


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


def test_tickio_recusa():
    por_peca, resultados = _rodar(handler=lambda r: httpx.Response(401))

    assert por_peca["Tickio"].estado is Estado.FALHA
    assert por_peca["Tickio"].correcao == "conferir TICKIO_*"
    assert falhou(resultados)


def test_bitbucket_sem_token_nao_faz_rede():
    def handler(request):
        if "bitbucket" in str(request.url):
            raise AssertionError("sem rede")
        return _tickio_ok(request)

    por_peca, _ = _rodar(handler=handler)

    assert por_peca["Bitbucket"].estado is Estado.NAO_CONFIGURADO


def test_bitbucket_token_recusado_e_aceito():
    def recusa(request):
        if "bitbucket" in str(request.url):
            return httpx.Response(401)
        return _tickio_ok(request)

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

    por_peca, _ = _rodar(env, handler=lambda r: httpx.Response(500))

    assert por_peca["PROJECTS_DIR"].estado is Estado.FALHA
    assert por_peca["Tickio"].estado is Estado.FALHA


def test_credenciais_nunca_aparecem():
    env = {**ENV_OK, "BITBUCKET_TOKEN": "bb-secreto", "BITBUCKET_EMAIL": "a@b.c"}

    _, resultados = _rodar(env, handler=lambda r: httpx.Response(401))
    texto = " ".join(f"{r.detalhe} {r.correcao}" for r in resultados)

    for segredo in ("senha-secreta", "tickio-secreto", "bb-secreto"):
        assert segredo not in texto


def test_nao_verificada_e_nao_configurado_nao_falham():
    assert not falhou(
        [
            Resultado("a", Estado.NAO_VERIFICADA),
            Resultado("b", Estado.NAO_CONFIGURADO),
        ]
    )
