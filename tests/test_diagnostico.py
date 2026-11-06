"""Diagnóstico da instalação, sem banco real nem rede."""

from __future__ import annotations

import contextlib
import os

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from motor.config import (
    SECAO_REPOS,
    ConfigProjeto,
    carregar_config_global,
    repos_configurados,
)
from motor.diagnostico import (
    Estado,
    Peca,
    Resultado,
    diagnosticar,
    falhou,
)
from motor.errors import ErroDeEntrada
from motor.migracoes import head
from tests.config_repos import secao_repo

HEAD = "rev2"
ENV_OK = {
    "DATABASE_BACKEND": "postgres",
    "DATABASE_HOST": "h",
    "DATABASE_PORT": "5433",
    "DATABASE_NAME": "n",
    "DATABASE_USER": "u",
    "DATABASE_PASSWORD": "senha-secreta",
}

CAMINHO_INEXISTENTE = "/nao/existe"
TABELA_REPO = "CREATE TABLE repo (id INTEGER PRIMARY KEY, nome TEXT)"


def _sessao_com(revisao: str | None):
    @contextlib.contextmanager
    def abrir(garantir=True):
        with Session(create_engine("sqlite://")) as sessao:
            if revisao is not None:
                sessao.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
                sessao.execute(
                    text("INSERT INTO alembic_version VALUES (:r)"), {"r": revisao}
                )
            sessao.execute(text(TABELA_REPO))
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
    repos=dict,
):
    resultados = diagnosticar(
        ENV_OK if env is None else env,
        abrir_sessao=abrir or _sessao_com(HEAD),
        head=HEAD,
        ambiente=ambiente,
        config_central=config_central,
        repos=repos,
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
        Peca.VARIAVEIS,
        Peca.POSTGRES,
        Peca.MIGRACAO,
        Peca.REPOS,
        Peca.TAREFAS,
        Peca.BITBUCKET,
    ]
    assert por_peca[Peca.TAREFAS].estado is Estado.NAO_CONFIGURADO
    assert por_peca[Peca.BITBUCKET].estado is Estado.NAO_CONFIGURADO


def test_postgres_fora():
    por_peca, resultados = _rodar(abrir=_banco_fora)

    assert falhou(resultados)
    assert por_peca[Peca.POSTGRES].estado is Estado.FALHA
    assert "docker compose up -d" in por_peca[Peca.POSTGRES].correcao
    assert por_peca[Peca.MIGRACAO].estado is Estado.NAO_VERIFICADA
    assert por_peca[Peca.TAREFAS].estado is Estado.NAO_CONFIGURADO


@pytest.mark.parametrize("revisao", [None, "antiga"])
def test_migracao_pendente(revisao):
    por_peca, _ = _rodar(abrir=_sessao_com(revisao))

    assert por_peca[Peca.MIGRACAO].estado is Estado.FALHA
    assert por_peca[Peca.MIGRACAO].correcao == "make migrate"


def test_migracao_em_desenvolvimento_usa_migrate_dev():
    por_peca, _ = _rodar(abrir=_sessao_com(None), ambiente="development")

    assert por_peca[Peca.MIGRACAO].correcao == "make migrate-dev"


@pytest.mark.parametrize("porta", ["", "abc"])
def test_variaveis_do_banco_invalidas_nao_abrem_sessao(porta):
    env = {**ENV_OK, "DATABASE_PORT": porta}

    por_peca, _ = _rodar(env, abrir=_abrir_proibido)

    assert por_peca[Peca.VARIAVEIS].estado is Estado.FALHA
    assert "DATABASE_PORT" in por_peca[Peca.VARIAVEIS].detalhe
    assert por_peca[Peca.POSTGRES].estado is Estado.NAO_VERIFICADA
    assert por_peca[Peca.MIGRACAO].estado is Estado.NAO_VERIFICADA


def _sessao_com_repos(*nomes: str):
    @contextlib.contextmanager
    def abrir(garantir=True):
        with Session(create_engine("sqlite://")) as sessao:
            sessao.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
            sessao.execute(text("INSERT INTO alembic_version VALUES (:r)"), {"r": HEAD})
            sessao.execute(text(TABELA_REPO))
            for nome in nomes:
                sessao.execute(text("INSERT INTO repo (nome) VALUES (:n)"), {"n": nome})
            yield sessao

    return abrir


def _repos_de(resultados):
    return [r for r in resultados if r.peca is Peca.REPOS]


def test_sem_projects_dir():
    _, resultados = _rodar({**ENV_OK, "PROJECTS_DIR": "/x"})

    assert "PROJECTS_DIR" not in [r.peca for r in resultados]


def test_bitbucket_sem_token_nao_faz_rede():
    def handler(request):
        if "bitbucket" in str(request.url):
            raise AssertionError("sem rede")
        return _bitbucket_ok(request)

    por_peca, _ = _rodar(handler=handler)

    assert por_peca[Peca.BITBUCKET].estado is Estado.NAO_CONFIGURADO


def test_bitbucket_token_recusado_e_aceito():
    def recusa(request):
        if "bitbucket" in str(request.url):
            return httpx.Response(401)
        return _bitbucket_ok(request)

    env = {**ENV_OK, "BITBUCKET_TOKEN": "tok", "BITBUCKET_EMAIL": "a@b.c"}

    recusado, resultados = _rodar(env, handler=recusa)
    aceito, _ = _rodar(env, handler=lambda r: httpx.Response(200, json={"access": "t"}))
    sem_email, _ = _rodar({**ENV_OK, "BITBUCKET_TOKEN": "tok"})

    assert recusado[Peca.BITBUCKET].estado is Estado.FALHA
    assert falhou(resultados)
    assert aceito[Peca.BITBUCKET].estado is Estado.OK
    assert sem_email[Peca.BITBUCKET].estado is Estado.FALHA


def test_falhas_independentes_no_mesmo_relatorio(tmp_path):
    por_peca, resultados = _rodar(
        abrir=_banco_fora, repos=lambda: {"x": str(tmp_path / "nao")}
    )

    assert Estado.FALHA in [r.estado for r in _repos_de(resultados)]
    assert por_peca[Peca.POSTGRES].estado is Estado.FALHA


def test_credenciais_nunca_aparecem():
    env = {**ENV_OK, "BITBUCKET_TOKEN": "bb-secreto", "BITBUCKET_EMAIL": "a@b.c"}

    _, resultados = _rodar(env, handler=lambda r: httpx.Response(401))
    texto = " ".join(f"{r.detalhe} {r.correcao}" for r in resultados)

    for segredo in ("senha-secreta", "bb-secreto"):
        assert segredo not in texto


def test_nao_verificada_e_nao_configurado_nao_falham():
    assert not falhou(
        [
            Resultado(Peca.VARIAVEIS, Estado.NAO_VERIFICADA),
            Resultado(Peca.TAREFAS, Estado.NAO_CONFIGURADO),
        ]
    )


ENV_SQLITE = {k: v for k, v in ENV_OK.items() if not k.startswith("DATABASE_")}


def test_sqlite_nao_exige_partes_do_banco_e_rotula_o_backend():
    por_peca, resultados = _rodar(ENV_SQLITE)

    assert not falhou(resultados)
    assert Peca.POSTGRES not in por_peca
    assert por_peca[Peca.SQLITE].estado is Estado.OK
    assert por_peca[Peca.MIGRACAO].estado is Estado.OK


def test_sqlite_sem_migracao_nao_sugere_docker_nem_make():
    por_peca, _ = _rodar(ENV_SQLITE, abrir=_sessao_com(None))

    assert por_peca[Peca.MIGRACAO].estado is Estado.FALHA
    assert "docker" not in por_peca[Peca.MIGRACAO].correcao


def test_sqlite_fora_nao_sugere_docker():
    por_peca, _ = _rodar(ENV_SQLITE, abrir=_banco_fora)

    assert por_peca[Peca.SQLITE].estado is Estado.FALHA
    assert "docker" not in por_peca[Peca.SQLITE].correcao
    assert por_peca[Peca.MIGRACAO].estado is Estado.NAO_VERIFICADA


def test_backend_desconhecido_e_variavel_invalida():
    por_peca, _ = _rodar(
        {**ENV_SQLITE, "DATABASE_BACKEND": "mysql"}, abrir=_abrir_proibido
    )

    assert por_peca[Peca.VARIAVEIS].estado is Estado.FALHA
    assert "DATABASE_BACKEND" in por_peca[Peca.VARIAVEIS].detalhe


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

    por_peca, resultados = _rodar(config_central=carregar_config_global)

    linha = por_peca[Peca.TAREFAS]
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

    por_peca, _ = _rodar(config_central=carregar_config_global)

    assert "construtor quebrou" in por_peca[Peca.TAREFAS].detalhe


def test_config_central_invalida_falha_so_na_linha_tarefas():
    def invalida() -> ConfigProjeto:
        raise ErroDeEntrada("config.toml: TOML invalido")

    por_peca, resultados = _rodar(config_central=invalida)

    assert por_peca[Peca.TAREFAS].estado is Estado.FALHA
    assert "TOML invalido" in por_peca[Peca.TAREFAS].detalhe
    assert [r.peca for r in resultados] == [
        Peca.VARIAVEIS,
        Peca.POSTGRES,
        Peca.MIGRACAO,
        Peca.REPOS,
        Peca.TAREFAS,
        Peca.BITBUCKET,
    ]
    outras = [r for r in resultados if r.peca is not Peca.TAREFAS]
    assert all(r.estado is not Estado.FALHA for r in outras)


def test_estado_sem_secao_avisa(tmp_path):
    _, resultados = _rodar(
        abrir=_sessao_com_repos("vb2web"), repos=lambda: {"vb2": str(tmp_path)}
    )

    assert _repos_de(resultados) == [
        Resultado(
            Peca.REPOS,
            Estado.AVISO,
            f"estado de 'vb2web' no banco sem seção [{SECAO_REPOS}.vb2web] "
            "no config.toml",
            "remover o estado do banco ou criar a seção",
        )
    ]
    assert not falhou(resultados)


def test_caminho_inexistente_falha():
    _, resultados = _rodar(repos=lambda: {"x": CAMINHO_INEXISTENTE})

    (linha,) = _repos_de(resultados)
    assert linha.estado is Estado.FALHA
    assert f"[{SECAO_REPOS}.x]" in linha.detalhe
    assert CAMINHO_INEXISTENTE in linha.detalhe
    assert falhou(resultados)


def test_secao_sem_caminho_falha():
    _, resultados = _rodar(repos=lambda: {"x": None})

    (linha,) = _repos_de(resultados)
    assert linha.estado is Estado.FALHA
    assert f"[{SECAO_REPOS}.x]" in linha.detalhe


def test_repos_ok(tmp_path):
    _, resultados = _rodar(
        abrir=_sessao_com_repos("a"),
        repos=lambda: {"a": str(tmp_path), "b": str(tmp_path)},
    )

    assert _repos_de(resultados) == [
        Resultado(Peca.REPOS, Estado.OK, "2 repo(s) configurado(s)")
    ]


def test_banco_fora_nao_verifica_repos():
    _, resultados = _rodar(abrir=_banco_fora, repos=lambda: {"x": CAMINHO_INEXISTENTE})

    estados = [r.estado for r in _repos_de(resultados)]
    assert Estado.NAO_VERIFICADA in estados
    assert Estado.FALHA in estados


def test_config_invalida_falha_repos():
    def invalida():
        raise ErroDeEntrada("config.toml: TOML invalido")

    _, resultados = _rodar(repos=invalida)

    (linha,) = _repos_de(resultados)
    assert linha.estado is Estado.FALHA
    assert "TOML invalido" in linha.detalhe


def test_repos_le_o_config_toml_real(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    central = tmp_path / "monitor-versoes" / "config.toml"
    central.parent.mkdir()
    central.write_text(secao_repo("a", tmp_path))

    _, resultados = _rodar(repos=repos_configurados)

    assert _repos_de(resultados)[0].estado is Estado.OK


def test_estado_sem_secao_avisa_no_sqlite(tmp_path):
    _, resultados = _rodar(
        ENV_SQLITE,
        abrir=_sessao_com_repos("orfao"),
        repos=lambda: {"a": str(tmp_path)},
    )

    (linha,) = _repos_de(resultados)
    assert linha.estado is Estado.AVISO
    assert "'orfao'" in linha.detalhe
