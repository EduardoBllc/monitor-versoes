"""Configuracao lida do ambiente selecionado pelo CLI."""

from __future__ import annotations

import os
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import quote

from motor.domain.version import validar_versao
from motor.errors import ErroDeEntrada

_CAMPOS_BANCO = ("HOST", "PORT", "NAME", "USER", "PASSWORD")

#: Worktrees de versao que ficam em disco depois de cada operacao.
_WORKTREES_MANTIDAS_PADRAO = 3


_BACKENDS = ("sqlite", "postgres")

#: O aviso de backend padrao sai uma vez por execucao.
_avisos_emitidos: set[str] = set()


def _caminho_sqlite() -> str:
    """Arquivo do SQLite: `DATABASE_SQLITE_PATH` ou o padrao do usuario."""
    configurado = os.environ.get("DATABASE_SQLITE_PATH", "").strip()
    if configurado:
        return os.path.expanduser(configurado)
    return os.path.join(
        os.path.expanduser("~"), ".local", "share", "monitor-versoes", "estado.db"
    )


def _url_sqlite() -> str:
    caminho = _caminho_sqlite()
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    return f"sqlite:///{caminho}"


def _partes_postgres() -> dict[str, str]:
    return {c: os.environ.get(f"DATABASE_{c}", "") for c in _CAMPOS_BANCO}


def _url_postgres() -> str:
    """Monta a URL do Postgres a partir das partes.

    As partes existem separadas porque o compose.yml (modelo) le as mesmas variaveis do
    mesmo .env — uma fonte so para aplicacao e container.
    """
    v = _partes_postgres()
    if faltando := [f"DATABASE_{c}" for c, valor in v.items() if not valor]:
        raise ErroDeEntrada(f"faltando no .env: {', '.join(faltando)}")
    # create_engine converte a porta na hora: um typo aqui viraria ValueError,
    # que o __main__ trata como bug (traceback) em vez de erro do operador.
    if not v["PORT"].isdigit():
        raise ErroDeEntrada(f"DATABASE_PORT invalido: {v['PORT']!r} (esperado numero)")

    # quote em usuario e senha: um '@' na senha monta uma URL sintaticamente
    # valida apontando para outro host, e o erro que aparece e "conexao
    # recusada", nao "senha invalida".
    return (
        f"postgresql+psycopg://{quote(v['USER'], safe='')}:"
        f"{quote(v['PASSWORD'], safe='')}@{v['HOST']}:{v['PORT']}/{v['NAME']}"
    )


def backend() -> str:
    """`sqlite` (padrao) ou `postgres`, conforme `DATABASE_BACKEND`."""
    valor = os.environ.get("DATABASE_BACKEND", "").strip().lower()
    if not valor:
        return "sqlite"
    if valor not in _BACKENDS:
        raise ErroDeEntrada(
            f"DATABASE_BACKEND invalido: {valor!r} (aceitos: {', '.join(_BACKENDS)})"
        )
    return valor


def database_url(avisar: bool = True) -> str:
    """URL do banco de estado, escolhida por `DATABASE_BACKEND`.

    Sem a variavel, o padrao e SQLite. Se as cinco partes `DATABASE_*` estao
    completas mesmo assim (quem usava Postgres antes da variavel existir), o
    SQLite vale e `avisar` escreve uma linha em stderr, uma vez por execucao.
    """
    escolhido = backend()
    if escolhido == "postgres":
        return _url_postgres()
    if (
        avisar
        and "backend_padrao" not in _avisos_emitidos
        and not os.environ.get("DATABASE_BACKEND", "").strip()
        and all(_partes_postgres().values())
    ):
        _avisos_emitidos.add("backend_padrao")
        print(
            "aviso: DATABASE_BACKEND nao definido; usando SQLite. Para usar o "
            "Postgres configurado em DATABASE_*, defina DATABASE_BACKEND=postgres.",
            file=sys.stderr,
        )
    return _url_sqlite()


def worktrees_mantidas() -> int:
    """Quantas worktrees de versao sobrevivem a cada operacao.

    Levantar uma worktree e um checkout inteiro — depois do fetch, a espera mais
    longa do motor. Mantendo as ultimas em disco, o run seguinte na mesma versao
    so reusa o diretorio que ja esta la.

    `0` e valor valido, e significa o comportamento historico (descarta no fim
    de cada run) — por isso o default nao pode sair de um `or`. Valor nao
    numerico e erro do operador, nao default calado: `WORKTREES_MANTIDAS=tres`
    cairia em 3 e a pessoa nunca saberia que nao configurou nada.
    """
    valor = os.environ.get("WORKTREES_MANTIDAS", "").strip()
    if not valor:
        return _WORKTREES_MANTIDAS_PADRAO
    # isdigit recusa "-1", "1.5" e "3 worktrees" de uma vez; int() sozinho
    # aceitaria negativo, que nao tem significado aqui.
    if not valor.isdigit():
        raise ErroDeEntrada(
            f"WORKTREES_MANTIDAS invalido: {valor!r} (esperado inteiro >= 0)"
        )
    return int(valor)


#: Nome do arquivo de config na raiz do repo-alvo.
ARQUIVO_CONFIG_REPO = ".monitor-versoes.toml"


@dataclass(frozen=True)
class ConfigProjeto:
    """Config por projeto, mesclada das duas camadas (repo vence o global).

    `tarefas` e opaco ao nucleo: quem le as chaves e o adapter do tracker.
    """

    piso: str | None = None
    tarefas: Mapping[str, object] = field(default_factory=dict)
    arquivos: tuple[str, ...] = ()


def caminho_config_global() -> str:
    """`$XDG_CONFIG_HOME/monitor-versoes/config.toml`, ou `~/.config/...`."""
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "monitor-versoes", "config.toml")


def _ler_toml(caminho: str) -> dict[str, object]:
    try:
        with open(caminho, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        raise ErroDeEntrada(f"{caminho}: TOML invalido ({e})") from e
    except OSError as e:
        raise ErroDeEntrada(f"{caminho}: nao foi possivel ler ({e})") from e


def _tabela(
    dados: Mapping[str, object], nome: str, caminho: str
) -> Mapping[str, object]:
    valor = dados.get(nome, {})
    if not isinstance(valor, dict):
        raise ErroDeEntrada(f"{caminho}: [{nome}] deve ser uma tabela")
    return valor


def _piso(dados: Mapping[str, object], caminho: str) -> str | None:
    bruto = _tabela(dados, "versao", caminho).get("piso")
    if bruto is None:
        return None
    if not isinstance(bruto, str):
        raise ErroDeEntrada(f"{caminho}: [versao] piso deve ser texto X.Y.Z")
    try:
        return validar_versao(bruto)
    except ErroDeEntrada as e:
        raise ErroDeEntrada(f"{caminho}: [versao] piso invalido ({e})") from e


def carregar_config(raiz_repo: str | None) -> ConfigProjeto:
    """Le o global e, havendo `raiz_repo`, o `.monitor-versoes.toml` dela.

    Mescla chave a chave, o repo vencendo. Arquivo ausente vale vazio. So `piso`
    e `[tarefas]` sao lidos; o resto e ignorado.
    """
    caminhos = [caminho_config_global()]
    if raiz_repo is not None:
        caminhos.append(os.path.join(raiz_repo, ARQUIVO_CONFIG_REPO))
    piso: str | None = None
    tarefas: dict[str, object] = {}
    for caminho in caminhos:
        dados = _ler_toml(caminho)
        if (p := _piso(dados, caminho)) is not None:
            piso = p
        tarefas.update(_tabela(dados, "tarefas", caminho))
    return ConfigProjeto(piso=piso, tarefas=tarefas, arquivos=tuple(caminhos))
