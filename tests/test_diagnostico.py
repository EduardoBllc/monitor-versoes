"""Diagnóstico da instalação, sem banco real nem rede."""

from __future__ import annotations

import contextlib
import os

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
ENV_OK: dict[str, str] = {}

#: As cinco variáveis do Postgres removido, que juntas são configuração antiga.
CINCO_POSTGRES = {
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


def _sem_fonte() -> ConfigProjeto:
    return ConfigProjeto()


CONFIG_EM = "/xdg/monitor-versoes/config.toml"


def _rodar(
    env=None,
    *,
    abrir=None,
    ambiente="production",
    config_central=_sem_fonte,
    repos=dict,
    erro_ambiente=None,
):
    resultados = diagnosticar(
        ENV_OK if env is None else env,
        abrir_sessao=abrir or _sessao_com(HEAD),
        head=HEAD,
        ambiente=ambiente,
        config_central=config_central,
        repos=repos,
        config_em=CONFIG_EM,
        erro_ambiente=erro_ambiente,
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
        Peca.SQLITE,
        Peca.MIGRACAO,
        Peca.REPOS,
        Peca.TAREFAS,
        Peca.PRS,
    ]
    assert por_peca[Peca.TAREFAS].estado is Estado.NAO_CONFIGURADO
    assert por_peca[Peca.PRS].estado is Estado.NAO_CONFIGURADO


def test_erro_no_ambiente_central_vira_linha_propria_e_o_resto_segue():
    por_peca, resultados = _rodar(
        erro_ambiente=ErroDeEntrada(f"{CONFIG_EM}: TOML inválido")
    )

    assert falhou(resultados)
    assert resultados[0].peca is Peca.AMBIENTE
    assert resultados[0].estado is Estado.FALHA
    assert CONFIG_EM in resultados[0].detalhe
    assert resultados[0].correcao == f"corrigir {CONFIG_EM}"
    assert {Peca.VARIAVEIS, Peca.SQLITE, Peca.TAREFAS, Peca.PRS} <= set(por_peca)


@pytest.mark.parametrize(
    ("ambiente", "arquivo"),
    [("production", ".env"), ("development", ".env.development")],
)
def test_variaveis_ausentes_apontam_o_ambiente_central(ambiente, arquivo):
    por_peca, _ = _rodar(
        {"DATABASE_BACKEND": "postgres"}, abrir=_abrir_proibido, ambiente=ambiente
    )

    assert por_peca[Peca.VARIAVEIS].correcao == (
        f"corrigir em [ambiente] de {CONFIG_EM} (ou no {arquivo})"
    )


def test_migracao_vazia_aponta_o_primeiro_uso():
    por_peca, _ = _rodar(abrir=_sessao_com(None))

    assert por_peca[Peca.MIGRACAO].estado is Estado.FALHA
    assert "primeiro uso" in por_peca[Peca.MIGRACAO].correcao


@pytest.mark.parametrize(
    ("ambiente", "correcao"),
    [
        ("production", "monitor-versoes migrar"),
        ("development", "monitor-versoes --env development migrar"),
    ],
)
def test_migracao_antiga_aponta_o_migrar(ambiente, correcao):
    por_peca, _ = _rodar(abrir=_sessao_com("antiga"), ambiente=ambiente)

    assert por_peca[Peca.MIGRACAO].estado is Estado.FALHA
    assert por_peca[Peca.MIGRACAO].correcao == correcao


@pytest.mark.parametrize(
    "env",
    [{"DATABASE_BACKEND": "postgres"}, CINCO_POSTGRES],
    ids=["backend-postgres", "cinco-partes"],
)
def test_config_antiga_do_postgres_falha_sem_abrir_sessao(env):
    por_peca, resultados = _rodar(env, abrir=_abrir_proibido)

    assert falhou(resultados)
    assert por_peca[Peca.VARIAVEIS].estado is Estado.FALHA
    assert "migrar-estado" in por_peca[Peca.VARIAVEIS].detalhe
    assert por_peca[Peca.SQLITE].estado is Estado.NAO_VERIFICADA
    assert por_peca[Peca.MIGRACAO].estado is Estado.NAO_VERIFICADA


def test_so_algumas_partes_do_postgres_sao_ignoradas():
    por_peca, resultados = _rodar({"DATABASE_HOST": "h"})

    assert not falhou(resultados)
    assert por_peca[Peca.SQLITE].estado is Estado.OK


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


def test_falhas_independentes_no_mesmo_relatorio(tmp_path):
    por_peca, resultados = _rodar(
        abrir=_banco_fora, repos=lambda: {"x": str(tmp_path / "nao")}
    )

    assert Estado.FALHA in [r.estado for r in _repos_de(resultados)]
    assert por_peca[Peca.SQLITE].estado is Estado.FALHA


def test_credenciais_nunca_aparecem():
    _, resultados = _rodar(CINCO_POSTGRES)
    texto = " ".join(f"{r.detalhe} {r.correcao}" for r in resultados)

    for segredo in ("senha-secreta",):
        assert segredo not in texto


def test_nao_verificada_e_nao_configurado_nao_falham():
    assert not falhou(
        [
            Resultado(Peca.VARIAVEIS, Estado.NAO_VERIFICADA),
            Resultado(Peca.TAREFAS, Estado.NAO_CONFIGURADO),
        ]
    )


def test_sqlite_nao_exige_partes_do_banco_e_rotula_o_backend():
    por_peca, resultados = _rodar(ENV_OK)

    assert not falhou(resultados)
    assert por_peca[Peca.SQLITE].estado is Estado.OK
    assert por_peca[Peca.MIGRACAO].estado is Estado.OK


def test_sqlite_sem_migracao_nao_sugere_docker_nem_make():
    por_peca, _ = _rodar(ENV_OK, abrir=_sessao_com(None))

    assert por_peca[Peca.MIGRACAO].estado is Estado.FALHA
    assert "docker" not in por_peca[Peca.MIGRACAO].correcao


def test_sqlite_fora_nao_sugere_docker():
    por_peca, _ = _rodar(ENV_OK, abrir=_banco_fora)

    assert por_peca[Peca.SQLITE].estado is Estado.FALHA
    assert "docker" not in por_peca[Peca.SQLITE].correcao
    assert por_peca[Peca.MIGRACAO].estado is Estado.NAO_VERIFICADA


def test_backend_desconhecido_e_variavel_invalida():
    por_peca, _ = _rodar({**ENV_OK, "DATABASE_BACKEND": "mysql"}, abrir=_abrir_proibido)

    assert por_peca[Peca.VARIAVEIS].estado is Estado.FALHA
    assert "aceito: sqlite" in por_peca[Peca.VARIAVEIS].detalhe


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
            f"conferir as credenciais da fonte em [ambiente] de {CONFIG_EM} "
            "(ou no .env)",
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


# -- linha Fonte de PR -----------------------------------------------------------

_PLUGINS_PR = "conferir [prs] fonte e os plugins instalados"


@pytest.mark.parametrize(
    ("fonte", "token", "estado", "correcao"),
    [
        (
            None,
            "",
            Estado.NAO_CONFIGURADO,
            "definir [prs] fonte no config.toml central",
        ),
        ("inexistente", "", Estado.FALHA, _PLUGINS_PR),
        ("tests.fontes_falsas:HostConstrutorComBug", "", Estado.FALHA, _PLUGINS_PR),
        ("tests.fontes_falsas:HostSemVerificacao", "", Estado.NAO_VERIFICADA, ""),
        ("tests.fontes_falsas:HostFalso", "certo", Estado.OK, ""),
        (
            "tests.fontes_falsas:HostFalso",
            "errado",
            Estado.FALHA,
            f"conferir as credenciais da fonte em [ambiente] de {CONFIG_EM} "
            "(ou no .env)",
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
def test_linha_fonte_de_pr_por_estado(
    tmp_path, monkeypatch, fonte, token, estado, correcao
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("HOST_FALSO_TOKEN", token)
    central = tmp_path / "monitor-versoes" / "config.toml"
    central.parent.mkdir()
    central.write_text("" if fonte is None else f'[prs]\nfonte = "{fonte}"\n')

    por_peca, resultados = _rodar(config_central=carregar_config_global)

    linha = por_peca[Peca.PRS]
    assert linha.estado is estado
    assert linha.correcao == correcao
    assert falhou(resultados) is (estado is Estado.FALHA)


def test_bitbucket_sem_credencial_falha_sem_rede(tmp_path, monkeypatch):
    """O plugin embutido: sem `BITBUCKET_EMAIL`, a falha sai antes de qualquer
    requisição (sem `httpx.Client` injetado, uma requisição sairia para a rede)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("BITBUCKET_TOKEN", "tok")
    monkeypatch.delenv("BITBUCKET_EMAIL", raising=False)
    central = tmp_path / "monitor-versoes" / "config.toml"
    central.parent.mkdir()
    central.write_text('[prs]\nfonte = "bitbucket"\n')

    por_peca, _ = _rodar(config_central=carregar_config_global)

    assert por_peca[Peca.PRS].estado is Estado.FALHA
    assert "BITBUCKET_EMAIL" in por_peca[Peca.PRS].detalhe


def test_config_central_invalida_falha_so_nas_linhas_de_plugin():
    def invalida() -> ConfigProjeto:
        raise ErroDeEntrada("config.toml: TOML invalido")

    por_peca, resultados = _rodar(config_central=invalida)

    for peca in (Peca.TAREFAS, Peca.PRS):
        assert por_peca[peca].estado is Estado.FALHA
        assert "TOML invalido" in por_peca[peca].detalhe
    assert [r.peca for r in resultados] == [
        Peca.VARIAVEIS,
        Peca.SQLITE,
        Peca.MIGRACAO,
        Peca.REPOS,
        Peca.TAREFAS,
        Peca.PRS,
    ]
    outras = [r for r in resultados if r.peca not in (Peca.TAREFAS, Peca.PRS)]
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
        ENV_OK,
        abrir=_sessao_com_repos("orfao"),
        repos=lambda: {"a": str(tmp_path)},
    )

    (linha,) = _repos_de(resultados)
    assert linha.estado is Estado.AVISO
    assert "'orfao'" in linha.detalhe
