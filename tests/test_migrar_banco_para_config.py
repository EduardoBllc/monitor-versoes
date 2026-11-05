"""Script que leva `sistema` e `piso` do banco antigo para a config.

O script nomeia as colunas que sairam: este arquivo e uma das excecoes
listadas no teste de nucleo neutro (tests/test_nucleo_neutro.py).
"""

from __future__ import annotations

import ast
import importlib.util
import os
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from motor.migracoes import config_alembic

_ARQUIVO = Path(__file__).parent.parent / "scripts" / "migrar_banco_para_config.py"
_COM_PISO = "f6b9c3d2e1a7"
_SEM_PISO = "b1f2c3d4e5a6"


def _carregar() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migrar_banco_para_config", _ARQUIVO)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    # dataclass resolve as anotacoes pelo modulo registrado em sys.modules.
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


script = _carregar()


def _semear(url: str, revisao: str = _COM_PISO) -> None:
    """Dois repos no esquema antigo: `webapp` (alias `web`) e `api`."""
    command.upgrade(config_alembic(url), revisao)
    engine = create_engine(url)
    com_piso = revisao == _COM_PISO
    with engine.begin() as con:
        for repo_id, nome, sistema, piso in (
            (1, "webapp", 7, "14.0.0"),
            (2, "api", 3, "13.5.0"),
        ):
            if com_piso:
                con.execute(
                    text(
                        "insert into repo (id, nome, tickio_sistema_id, piso_versao) "
                        "values (:i, :n, :s, :p)"
                    ),
                    {"i": repo_id, "n": nome, "s": sistema, "p": piso},
                )
            else:
                con.execute(
                    text(
                        "insert into repo (id, nome, tickio_sistema_id) "
                        "values (:i, :n, :s)"
                    ),
                    {"i": repo_id, "n": nome, "s": sistema},
                )
        con.execute(text("insert into repo_alias (nome, repo_id) values ('web', 1)"))
    engine.dispose()


@pytest.fixture
def banco(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'antigo.db'}"
    _semear(url)
    return url


@pytest.fixture
def projetos(tmp_path: Path) -> Path:
    raiz = tmp_path / "projetos"
    for nome in ("webapp", "api"):
        (raiz / nome).mkdir(parents=True)
    return raiz


def _config(repo: Path) -> dict[str, object]:
    with open(repo / ".monitor-versoes.toml", "rb") as f:
        return tomllib.load(f)


def _rodar(banco: str, *repos: Path | str, aplicar: bool = True) -> int:
    argv = ["--banco", banco]
    for repo in repos:
        argv += ["--repo", str(repo)]
    if aplicar:
        argv.append("--aplicar")
    codigo: int = script.main(argv)
    return codigo


@pytest.mark.parametrize(
    ("revisao", "piso"), [(_COM_PISO, "14.0.0"), (_SEM_PISO, "13.0.0")]
)
def test_escreve_sistema_e_piso_por_repo(tmp_path, projetos, revisao, piso):
    url = f"sqlite:///{tmp_path / 'antigo.db'}"
    _semear(url, revisao)

    assert _rodar(url, projetos / "webapp", projetos / "api") == 0

    assert _config(projetos / "webapp") == {
        "tarefas": {"sistema": 7},
        "versao": {"piso": piso},
    }
    assert _config(projetos / "api")["tarefas"] == {"sistema": 3}


def test_casa_pelo_alias(banco, tmp_path):
    web = tmp_path / "outro" / "web"
    api = tmp_path / "outro" / "api"
    web.mkdir(parents=True)
    api.mkdir()

    assert _rodar(banco, web, api) == 0

    assert _config(web)["tarefas"] == {"sistema": 7}


def test_sem_aplicar_nao_escreve(banco, projetos, capsys):
    assert _rodar(banco, projetos / "webapp", projetos / "api", aplicar=False) == 0

    assert not (projetos / "webapp" / ".monitor-versoes.toml").exists()
    saida = capsys.readouterr().out
    assert '[tarefas] sistema = 7, [versao] piso = "14.0.0"' in saida
    assert "nada foi escrito" in saida


def _sem_caminho(p: Path) -> list[Path | str]:
    return [p / "webapp"]


def _nao_casa(p: Path) -> list[Path | str]:
    (p / "desconhecido").mkdir()
    return [p / "webapp", p / "api", p / "desconhecido"]


def _dois_para_o_mesmo(p: Path) -> list[Path | str]:
    return [p / "webapp", p / "api", f"{p / 'webapp'}/../webapp/"]


def _nao_e_diretorio(p: Path) -> list[Path | str]:
    (p / "api").rmdir()
    (p / "api").write_text("arquivo")
    return [p / "webapp", p / "api"]


def _toml_invalido(p: Path) -> list[Path | str]:
    (p / "api" / ".monitor-versoes.toml").write_text("[tarefas\n")
    return [p / "webapp", p / "api"]


def _outro_valor(p: Path) -> list[Path | str]:
    (p / "api" / ".monitor-versoes.toml").write_text("[tarefas]\nsistema = 99\n")
    return [p / "webapp", p / "api"]


def _arquivos(p: Path) -> dict[str, bytes | None]:
    estado: dict[str, bytes | None] = {}
    for nome in ("webapp", "api"):
        arquivo = p / nome / ".monitor-versoes.toml"
        estado[nome] = arquivo.read_bytes() if arquivo.is_file() else None
    return estado


@pytest.mark.parametrize(
    "preparar",
    [
        _sem_caminho,
        _nao_casa,
        _dois_para_o_mesmo,
        _nao_e_diretorio,
        _toml_invalido,
        _outro_valor,
    ],
)
def test_aborta_sem_escrever(banco, projetos, preparar, capsys):
    repos = preparar(projetos)
    antes = _arquivos(projetos)

    assert _rodar(banco, *repos) == 1

    assert _arquivos(projetos) == antes
    assert "nada foi escrito" in capsys.readouterr().err


def test_lista_todos_os_problemas_de_uma_vez(banco, projetos, capsys):
    (projetos / "api" / ".monitor-versoes.toml").write_text("[tarefas\n")
    (projetos / "desconhecido").mkdir()

    codigo = _rodar(
        banco, projetos / "webapp", projetos / "api", projetos / "desconhecido"
    )

    erro = capsys.readouterr().err
    assert codigo == 1
    assert "TOML inválido" in erro
    assert "não casa com nenhum repo" in erro


def test_preserva_o_conteudo_existente(banco, projetos):
    existente = '# config do repo\n[referencia]\npadrao = "ch{id}"  # proposta\n'
    arquivo = projetos / "webapp" / ".monitor-versoes.toml"
    arquivo.write_text(existente)

    assert _rodar(banco, projetos / "webapp", projetos / "api") == 0

    assert arquivo.read_text().startswith(existente)
    assert _config(projetos / "webapp")["versao"] == {"piso": "14.0.0"}


def test_mesmo_valor_ja_presente_fica_como_esta(banco, projetos, capsys):
    arquivo = projetos / "webapp" / ".monitor-versoes.toml"
    arquivo.write_text('[tarefas]\nsistema = 7\n\n[versao]\npiso = "14.0.0"\n')

    assert _rodar(banco, projetos / "webapp", projetos / "api") == 0

    assert "(sem mudança)" in capsys.readouterr().out


def test_rodar_de_novo_nao_muda_nada(banco, projetos):
    assert _rodar(banco, projetos / "webapp", projetos / "api") == 0
    arquivo = projetos / "webapp" / ".monitor-versoes.toml"
    antes = (arquivo.read_bytes(), os.stat(arquivo).st_mtime_ns)

    assert _rodar(banco, projetos / "webapp", projetos / "api") == 0

    assert (arquivo.read_bytes(), os.stat(arquivo).st_mtime_ns) == antes


def test_nao_importa_motor():
    arvore = ast.parse(_ARQUIVO.read_text(encoding="utf-8"))
    modulos = [
        alias.name
        for no in ast.walk(arvore)
        if isinstance(no, ast.Import)
        for alias in no.names
    ] + [no.module or "" for no in ast.walk(arvore) if isinstance(no, ast.ImportFrom)]

    assert modulos
    assert not [m for m in modulos if m == "motor" or m.startswith("motor.")]


def test_cabecalho_pep723_declara_as_dependencias():
    texto = _ARQUIVO.read_text(encoding="utf-8")
    inicio = texto.index("# /// script\n")
    bloco = texto[inicio : texto.index("# ///\n", inicio + 1)]
    toml = "\n".join(
        linha.removeprefix("# ").removeprefix("#") for linha in bloco.splitlines()[1:]
    )

    deps = tomllib.loads(toml)["dependencies"]

    nomes = {d.split(">")[0].split("[")[0] for d in deps}
    assert nomes == {"sqlalchemy", "psycopg", "tomlkit", "python-dotenv"}


_PARTES = {
    "DATABASE_HOST": "h",
    "DATABASE_PORT": "5433",
    "DATABASE_NAME": "n",
    "DATABASE_USER": "u",
    "DATABASE_PASSWORD": "s@nha",
}


def test_env_sem_backend_com_partes_completas_infere_postgres_e_avisa(
    tmp_path, monkeypatch, capsys
):
    url, inferido = script.url_do_env(_PARTES)

    assert url == "postgresql+psycopg://u:s%40nha@h:5433/n"
    assert inferido is True

    env = tmp_path / ".env"
    env.write_text("".join(f"{k}={v}\n" for k, v in _PARTES.items()))
    lidas: list[str] = []

    def ler_repos(url_lida: str) -> list[object]:
        lidas.append(url_lida)
        return []

    monkeypatch.setattr(script, "ler_repos", ler_repos)

    assert script.main(["--env", str(env), "--repo", str(tmp_path)]) == 1

    assert lidas == [url]
    assert "DATABASE_BACKEND=postgres" in capsys.readouterr().err


def test_env_com_backend_postgres_nao_avisa():
    _, inferido = script.url_do_env({**_PARTES, "DATABASE_BACKEND": "postgres"})

    assert inferido is False


def test_env_sem_backend_e_sem_partes_usa_sqlite_padrao(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    url, inferido = script.url_do_env({"DATABASE_HOST": "h"})

    assert url == f"sqlite:///{tmp_path}/.local/share/monitor-versoes/estado.db"
    assert inferido is False


def test_sqlite_inexistente_nao_e_criado(tmp_path, capsys):
    caminho = tmp_path / "nao.db"

    assert _rodar(f"sqlite:///{caminho}", tmp_path) == 1

    assert not caminho.exists()
    assert "não encontrado" in capsys.readouterr().err


def test_help_traz_a_ordem(capsys):
    with pytest.raises(SystemExit) as saida:
        script.main(["--help"])

    texto = capsys.readouterr().out
    assert saida.value.code == 0
    assert "motor migrar" in texto
    assert "DATABASE_BACKEND=postgres" in texto


def test_banco_e_env_sao_exclusivos(tmp_path):
    with pytest.raises(SystemExit) as saida:
        script.main(["--banco", "x", "--env", "y", "--repo", str(tmp_path)])

    assert saida.value.code == 2


@pytest.mark.integracao
def test_le_postgres_antigo(_postgres_efemero, tmp_path, projetos):
    from sqlalchemy.engine import make_url

    url_base = make_url(_postgres_efemero.get_connection_url())
    admin = create_engine(url_base, isolation_level="AUTOCOMMIT")
    with admin.connect() as con:
        con.execute(text("drop database if exists antigo"))
        con.execute(text("create database antigo"))
    url_antigo = url_base.set(database="antigo").render_as_string(hide_password=False)
    try:
        _semear(url_antigo)

        assert _rodar(url_antigo, projetos / "webapp", projetos / "api") == 0

        assert _config(projetos / "webapp") == {
            "tarefas": {"sistema": 7},
            "versao": {"piso": "14.0.0"},
        }
    finally:
        with admin.connect() as con:
            con.execute(text("drop database if exists antigo with (force)"))
        admin.dispose()
