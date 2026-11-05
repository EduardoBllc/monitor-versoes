# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sqlalchemy>=2.0",
#     "psycopg[binary]>=3.2",
#     "tomlkit>=0.13",
#     "python-dotenv",
# ]
# ///
"""Leva `sistema` e `piso` do banco antigo para o `.monitor-versoes.toml`.

Roda uma vez, numa máquina que ainda guarda `repo.tickio_sistema_id` e
`repo.piso_versao` no banco de estado, antes do `motor migrar` que derruba as
colunas. Autocontido de propósito: não importa `motor`, então roda pela URL raw
sem tocar no checkout antigo:

    uv run --script <url raw deste arquivo> --env <checkout>/.env \\
        --repo <caminho> [--repo <caminho> ...] [--aplicar]

Só lê o banco. Sem `--aplicar`, mostra o que escreveria. Qualquer problema
aborta sem escrever nada, com todos os problemas listados de uma vez.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import tomlkit
from dotenv import dotenv_values
from sqlalchemy import Engine, create_engine, inspect, make_url, text
from sqlalchemy.exc import SQLAlchemyError
from tomlkit.exceptions import TOMLKitError

ARQUIVO_CONFIG = ".monitor-versoes.toml"
#: O piso fixo de antes da coluna `piso_versao` existir (2026-10-08).
PISO_SEM_COLUNA = "13.0.0"
#: O mesmo padrão do motor (copiado: o script não importa `motor`).
SQLITE_PADRAO = os.path.join("~", ".local", "share", "monitor-versoes", "estado.db")
_PARTES_POSTGRES = ("HOST", "PORT", "NAME", "USER", "PASSWORD")

_ORDEM = """\
ordem na máquina que ainda tem as colunas no banco:
  1. rodar este script pela URL, com o checkout antigo intacto;
  2. commitar os .monitor-versoes.toml em cada repo;
  3. no config.toml central, escrever esquema = "vendabem" e
     atribuicao = "composta" em [versao], e fonte = "tickio" em [tarefas];
  4. se o banco é Postgres, definir DATABASE_BACKEND=postgres no .env;
  5. fazer git pull e instalar com o pacote monitor-versoes-vendabem;
  6. conferir com motor diagnostico que ele aponta para o banco certo;
  7. rodar motor migrar, sem nenhum outro comando entre o git pull e ele.
"""


class ErroDoScript(Exception):
    """Erro do operador: argumento, `.env` ou banco inválidos."""


@dataclass(frozen=True)
class RepoAntigo:
    nome: str
    aliases: tuple[str, ...]
    sistema: int
    piso: str


@dataclass(frozen=True)
class Escrita:
    caminho: str
    conteudo: str
    mudou: bool
    sistema: int
    piso: str


def url_do_env(env: Mapping[str, str | None]) -> tuple[str, bool]:
    """A URL do banco e se o Postgres foi inferido sem `DATABASE_BACKEND`.

    Sem a variável, partes `DATABASE_*` completas valem Postgres, como nas
    revisões anteriores ao SQLite; sem elas, o SQLite no caminho padrão.
    """
    backend = (env.get("DATABASE_BACKEND") or "").strip().lower()
    partes = {p: (env.get(f"DATABASE_{p}") or "").strip() for p in _PARTES_POSTGRES}
    if backend == "postgres" or (not backend and all(partes.values())):
        faltando = [f"DATABASE_{p}" for p, v in partes.items() if not v]
        if faltando:
            raise ErroDoScript(f"faltando no .env: {', '.join(faltando)}")
        url = (
            f"postgresql+psycopg://{quote(partes['USER'], safe='')}:"
            f"{quote(partes['PASSWORD'], safe='')}@{partes['HOST']}:"
            f"{partes['PORT']}/{partes['NAME']}"
        )
        return url, not backend
    if backend not in {"", "sqlite"}:
        raise ErroDoScript(
            f"DATABASE_BACKEND (aceitos: sqlite, postgres; veio {backend!r})"
        )
    caminho = (env.get("DATABASE_SQLITE_PATH") or "").strip() or SQLITE_PADRAO
    return f"sqlite:///{os.path.expanduser(caminho)}", False


def _engine_so_leitura(url: str) -> Engine:
    """Engine que não escreve nem cria o arquivo do SQLite."""
    if url.startswith("sqlite"):
        caminho = make_url(url).database or ""
        if not os.path.isfile(caminho):
            raise ErroDoScript(f"banco SQLite não encontrado: {caminho}")
        return create_engine(
            "sqlite://",
            creator=lambda: sqlite3.connect(f"file:{caminho}?mode=ro", uri=True),
        )
    return create_engine(
        url, connect_args={"options": "-c default_transaction_read_only=on"}
    )


def ler_repos(url: str) -> list[RepoAntigo]:
    """Nome, aliases, sistema e piso de cada repo, sem alterar o banco."""
    engine = _engine_so_leitura(url)
    try:
        with engine.connect() as con:
            colunas = {c["name"] for c in inspect(con).get_columns("repo")}
            if "tickio_sistema_id" not in colunas:
                raise ErroDoScript(
                    "o banco não tem repo.tickio_sistema_id: já foi migrado?"
                )
            piso = "piso_versao" if "piso_versao" in colunas else f"'{PISO_SEM_COLUNA}'"
            linhas = con.execute(
                text(f"select id, nome, tickio_sistema_id, {piso} from repo")
            ).all()
            aliases: dict[int, list[str]] = {}
            for repo_id, alias in con.execute(
                text("select repo_id, nome from repo_alias order by nome")
            ):
                aliases.setdefault(repo_id, []).append(alias)
            con.rollback()
    except SQLAlchemyError as e:
        raise ErroDoScript(f"não consegui ler o banco: {e}") from e
    finally:
        engine.dispose()
    return [
        RepoAntigo(
            nome=nome,
            aliases=tuple(aliases.get(repo_id, [])),
            sistema=int(sistema),
            piso=str(piso_valor),
        )
        for repo_id, nome, sistema, piso_valor in sorted(linhas, key=lambda r: r[1])
    ]


def _basename(caminho: str) -> str:
    return os.path.basename(os.path.normpath(os.path.abspath(caminho)))


def _casar(
    repos: list[RepoAntigo], caminhos: list[str]
) -> tuple[dict[str, RepoAntigo], list[str]]:
    """Caminho -> repo pelo basename (nome ou alias), e os problemas."""
    por_nome = {n: r for r in repos for n in (r.nome, *r.aliases)}
    casados: dict[str, RepoAntigo] = {}
    donos: dict[str, list[str]] = {}
    problemas: list[str] = []
    for caminho in caminhos:
        repo = por_nome.get(_basename(caminho))
        if repo is None:
            problemas.append(f"{caminho}: não casa com nenhum repo do banco")
            continue
        casados[caminho] = repo
        donos.setdefault(repo.nome, []).append(caminho)
    for nome, lista in donos.items():
        if len(lista) > 1:
            problemas.append(
                f"repo {nome!r}: casa com mais de um --repo ({', '.join(lista)})"
            )
    problemas += [
        f"repo {r.nome!r} do banco ficou sem caminho (passe --repo)"
        for r in repos
        if r.nome not in donos
    ]
    return casados, problemas


def _tabela(doc: tomlkit.TOMLDocument, nome: str) -> MutableMapping[str, Any] | None:
    """A tabela `[nome]`, criada no fim do arquivo se não existe."""
    if nome not in doc:
        doc[nome] = tomlkit.table()
    tabela = doc[nome]
    return tabela if isinstance(tabela, MutableMapping) else None


def _planejar_um(caminho: str, repo: RepoAntigo) -> tuple[Escrita | None, list[str]]:
    if not os.path.isdir(caminho):
        return None, [f"{caminho}: não é diretório"]
    arquivo = os.path.join(caminho, ARQUIVO_CONFIG)
    original = ""
    if os.path.exists(arquivo):
        with open(arquivo, encoding="utf-8") as f:
            original = f.read()
    try:
        doc = tomlkit.parse(original)
    except TOMLKitError as e:
        return None, [f"{arquivo}: TOML inválido ({e})"]
    problemas: list[str] = []
    for tabela, chave, valor in (
        ("tarefas", "sistema", repo.sistema),
        ("versao", "piso", repo.piso),
    ):
        destino = _tabela(doc, tabela)
        if destino is None:
            problemas.append(f"{arquivo}: [{tabela}] não é tabela")
            continue
        if chave not in destino:
            destino[chave] = valor
        elif destino[chave] != valor or isinstance(destino[chave], bool):
            problemas.append(
                f"{arquivo}: [{tabela}] {chave} = {destino[chave]!r}, "
                f"o banco diz {valor!r}"
            )
    if problemas:
        return None, problemas
    conteudo = tomlkit.dumps(doc)
    return Escrita(arquivo, conteudo, conteudo != original, repo.sistema, repo.piso), []


def planejar(
    repos: list[RepoAntigo], caminhos: list[str]
) -> tuple[list[Escrita], list[str]]:
    """O que escrever em cada repo e tudo o que impede escrever."""
    casados, problemas = _casar(repos, caminhos)
    escritas: list[Escrita] = []
    for caminho, repo in casados.items():
        escrita, do_repo = _planejar_um(caminho, repo)
        problemas += do_repo
        if escrita is not None:
            escritas.append(escrita)
    return escritas, problemas


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migrar_banco_para_config.py",
        description=(
            "Escreve [tarefas] sistema e [versao] piso no .monitor-versoes.toml "
            "de cada repo, a partir do banco de estado antigo."
        ),
        epilog=_ORDEM,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    banco = parser.add_mutually_exclusive_group(required=True)
    banco.add_argument("--banco", metavar="URL", help="URL SQLAlchemy do banco")
    banco.add_argument(
        "--env", metavar="ARQUIVO", help=".env do checkout antigo (DATABASE_*)"
    )
    parser.add_argument(
        "--repo",
        action="append",
        required=True,
        metavar="CAMINHO",
        help="checkout de um repo-alvo; repita para cada repo do banco",
    )
    parser.add_argument(
        "--aplicar", action="store_true", help="escreve (sem ele, só mostra)"
    )
    return parser


def _url(args: argparse.Namespace) -> str:
    if args.banco is not None:
        return str(args.banco)
    if not os.path.isfile(args.env):
        raise ErroDoScript(f".env não encontrado: {args.env}")
    url, inferido = url_do_env(dotenv_values(args.env))
    if inferido:
        print(
            "aviso: o .env não define DATABASE_BACKEND e tem as partes do "
            "Postgres. O código novo usa SQLite nesse caso: defina "
            "DATABASE_BACKEND=postgres no .env antes do motor migrar.",
            file=sys.stderr,
        )
    return url


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        repos = ler_repos(_url(args))
    except ErroDoScript as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    escritas, problemas = planejar(repos, args.repo)
    if problemas:
        for problema in problemas:
            print(f"problema: {problema}", file=sys.stderr)
        print("nada foi escrito", file=sys.stderr)
        return 1
    for escrita in escritas:
        linha = (
            f"{escrita.caminho}: [tarefas] sistema = {escrita.sistema}, "
            f'[versao] piso = "{escrita.piso}"'
        )
        print(linha if escrita.mudou else f"{linha} (sem mudança)")
        if args.aplicar and escrita.mudou:
            with open(escrita.caminho, "w", encoding="utf-8") as f:
                f.write(escrita.conteudo)
    if not args.aplicar:
        print("simulação: nada foi escrito (use --aplicar)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
