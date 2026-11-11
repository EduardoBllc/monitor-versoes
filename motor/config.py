"""Configuracao lida do ambiente selecionado pelo CLI."""

from __future__ import annotations

import os
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import quote

from motor.domain.referencia import validar_padrao
from motor.errors import ErroDeEntrada

_CAMPOS_BANCO = ("HOST", "PORT", "NAME", "USER", "PASSWORD")

#: Worktrees de versao que ficam em disco depois de cada operacao.
WORKTREES_MANTIDAS_PADRAO = 3
ARQUIVO_SQLITE = "estado.db"


class Backend(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


#: Variável que localiza a config central; nunca vem do `[ambiente]`.
VAR_XDG_CONFIG_HOME = "XDG_CONFIG_HOME"


class Tabela(StrEnum):
    """Tabelas do TOML com chaves que o motor conhece."""

    VERSAO = "versao"
    LIBERACAO = "liberacao"
    BRANCHES = "branches"
    REFERENCIA = "referencia"
    TAREFAS = "tarefas"


class Chave(StrEnum):
    ESQUEMA = "esquema"
    ATRIBUICAO = "atribuicao"
    TAG = "tag"
    VERSAO = "versao"
    PRINCIPAL = "principal"
    PADRAO = "padrao"
    FONTE = "fonte"
    PISO = "piso"


class VarAmbiente(StrEnum):
    """Chaves do `[ambiente]`: os nomes das variáveis que o motor lê."""

    DATABASE_BACKEND = "DATABASE_BACKEND"
    DATABASE_HOST = "DATABASE_HOST"
    DATABASE_PORT = "DATABASE_PORT"
    DATABASE_NAME = "DATABASE_NAME"
    DATABASE_USER = "DATABASE_USER"
    DATABASE_PASSWORD = "DATABASE_PASSWORD"
    DATABASE_SQLITE_PATH = "DATABASE_SQLITE_PATH"
    WORKTREES_MANTIDAS = "WORKTREES_MANTIDAS"
    BITBUCKET_EMAIL = "BITBUCKET_EMAIL"
    BITBUCKET_TOKEN = "BITBUCKET_TOKEN"


#: O aviso de backend padrao sai uma vez por execucao.
_avisos_emitidos: set[str] = set()


def diretorio_dados() -> str:
    """Diretorio de dados do usuario (estado.db, inscricoes.json)."""
    return os.path.join(os.path.expanduser("~"), ".local", "share", "monitor-versoes")


def _caminho_sqlite() -> str:
    """Arquivo do SQLite: `DATABASE_SQLITE_PATH` ou o padrao do usuario."""
    configurado = os.environ.get(VarAmbiente.DATABASE_SQLITE_PATH, "").strip()
    if configurado:
        return os.path.expanduser(configurado)
    return os.path.join(diretorio_dados(), ARQUIVO_SQLITE)


def _url_sqlite() -> str:
    caminho = _caminho_sqlite()
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    return f"sqlite:///{caminho}"


def _partes_postgres() -> dict[str, str]:
    return {c: os.environ.get(f"DATABASE_{c}", "") for c in _CAMPOS_BANCO}


def _url_postgres() -> str:
    """Monta a URL do Postgres a partir das partes.

    As partes existem separadas porque o compose.yml (modelo) le as mesmas variaveis,
    com os mesmos nomes — quem preferir um .env ao lado serve aplicacao e container.
    """
    v = _partes_postgres()
    if faltando := [f"DATABASE_{c}" for c, valor in v.items() if not valor]:
        raise ErroDeEntrada(
            f"faltando em [{TABELA_AMBIENTE}] de {caminho_config_global()} "
            f"(ou no .env): {', '.join(faltando)}"
        )
    # create_engine converte a porta na hora: um typo aqui viraria ValueError,
    # que o __main__ trata como bug (traceback) em vez de erro do operador.
    if not v["PORT"].isdigit():
        raise ErroDeEntrada(f"DATABASE_PORT inválido: {v['PORT']!r} (esperado número)")

    # quote em usuario e senha: um '@' na senha monta uma URL sintaticamente
    # valida apontando para outro host, e o erro que aparece e "conexao
    # recusada", nao "senha invalida".
    return (
        f"postgresql+psycopg://{quote(v['USER'], safe='')}:"
        f"{quote(v['PASSWORD'], safe='')}@{v['HOST']}:{v['PORT']}/{v['NAME']}"
    )


def backend() -> Backend:
    """`sqlite` (padrao) ou `postgres`, conforme `DATABASE_BACKEND`."""
    valor = os.environ.get(VarAmbiente.DATABASE_BACKEND, "").strip().lower()
    if not valor:
        return Backend.SQLITE
    if valor not in Backend:
        raise ErroDeEntrada(
            f"DATABASE_BACKEND inválido: {valor!r} (aceitos: {', '.join(Backend)})"
        )
    return Backend(valor)


def database_url(avisar: bool = True) -> str:
    """URL do banco de estado, escolhida por `DATABASE_BACKEND`.

    Sem a variavel, o padrao e SQLite. Se as cinco partes `DATABASE_*` estao
    completas mesmo assim (quem usava Postgres antes da variavel existir), o
    SQLite vale e `avisar` escreve uma linha em stderr, uma vez por execucao.
    """
    escolhido = backend()
    if escolhido is Backend.POSTGRES:
        return _url_postgres()
    if (
        avisar
        and "backend_padrao" not in _avisos_emitidos
        and not os.environ.get(VarAmbiente.DATABASE_BACKEND, "").strip()
        and all(_partes_postgres().values())
    ):
        _avisos_emitidos.add("backend_padrao")
        print(
            "aviso: DATABASE_BACKEND não definido; usando SQLite. Para usar o "
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
    valor = os.environ.get(VarAmbiente.WORKTREES_MANTIDAS, "").strip()
    if not valor:
        return WORKTREES_MANTIDAS_PADRAO
    # isdigit recusa "-1", "1.5" e "3 worktrees" de uma vez; int() sozinho
    # aceitaria negativo, que nao tem significado aqui.
    if not valor.isdigit():
        raise ErroDeEntrada(
            f"WORKTREES_MANTIDAS inválido: {valor!r} (esperado inteiro >= 0)"
        )
    return int(valor)


AMBIENTE_PADRAO = "production"

SECAO_REPOS = "repos"
TABELA_AMBIENTE = "ambiente"
CHAVE_CAMINHO = "caminho"


@dataclass(frozen=True)
class Escolhido:
    """Valor de uma chave com o arquivo que o deu, para o erro citá-lo."""

    valor: str
    arquivo: str


@dataclass(frozen=True)
class ConfigProjeto:
    """Config por projeto, mesclada do topo e da seção do repo (a seção vence).

    `tarefas` e opaco ao nucleo, salvo `fonte`: quem le as outras chaves e o
    plugin da fonte de tarefas, que recebe a tabela inteira (`fonte` inclusa).
    `fonte_tarefas` e o `[tarefas] fonte` com o arquivo que o deu.
    `padrao_referencia` e o `[referencia] padrao` mesclado; `None` quando nenhuma
    camada o define (vale o proposto pelo adapter).

    `piso` chega cru: quem o valida e o esquema de versao em uso, quando e
    resolvido (motor.montagem.resolver_versionamento), nao a leitura — senao um
    piso que o esquema nao reconhece derrubaria `atualizar --abort`.
    """

    piso: str | None = None
    arquivo_piso: str | None = None
    padrao_referencia: str | None = None
    tarefas: Mapping[str, object] = field(default_factory=dict)
    arquivos: tuple[str, ...] = ()
    esquema: Escolhido | None = None
    atribuicao: Escolhido | None = None
    tag_liberacao: Escolhido | None = None
    branch_versao: Escolhido | None = None
    branch_principal: Escolhido | None = None
    fonte_tarefas: Escolhido | None = None
    caminho: str | None = None


def validar_nome_repo(valor: str) -> str:
    """Nome canonico do repo: basename puro, sem caminho e sem espaco em volta.

    O nome e a chave do estado — aceitar 'pasta/backend' fragmentaria o repo em
    duas linhas paralelas sem erro nenhum aparecer.
    """
    if not valor.strip() or valor != valor.strip() or os.path.basename(valor) != valor:
        raise ErroDeEntrada("use um nome simples, sem caminho")
    return valor


def caminho_config_global() -> str:
    """`$XDG_CONFIG_HOME/monitor-versoes/config.toml`, ou `~/.config/...`."""
    base = os.environ.get(VAR_XDG_CONFIG_HOME, "").strip()
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
        raise ErroDeEntrada(f"{caminho}: TOML inválido ({e})") from e
    except OSError as e:
        raise ErroDeEntrada(f"{caminho}: não foi possível ler ({e})") from e


def _tabela(
    dados: Mapping[str, object], nome: str, caminho: str
) -> Mapping[str, object]:
    valor = dados.get(nome, {})
    if not isinstance(valor, dict):
        raise ErroDeEntrada(f"{caminho}: [{nome}] deve ser uma tabela, veio {valor!r}")
    return valor


def _texto(
    dados: Mapping[str, object], tabela: str, chave: str, caminho: str
) -> str | None:
    """`[tabela] chave` como texto não vazio; `None` se ausente."""
    bruto = _tabela(dados, tabela, caminho).get(chave)
    if bruto is None:
        return None
    if not isinstance(bruto, str) or not bruto.strip():
        raise ErroDeEntrada(
            f"{caminho}: [{tabela}] {chave} deve ser texto não vazio, veio {bruto!r}"
        )
    return bruto


def _template(
    dados: Mapping[str, object], tabela: str, chave: str, caminho: str
) -> str | None:
    """Texto com exatamente um `{versao}`; o resto e literal."""
    valor = _texto(dados, tabela, chave, caminho)
    if valor is not None and valor.count("{versao}") != 1:
        raise ErroDeEntrada(
            f"{caminho}: [{tabela}] {chave} deve ter exatamente um {{versao}}, "
            f"veio {valor!r}"
        )
    return valor


#: (atributo do ConfigProjeto, tabela, chave, e se e template com `{versao}`)
_ESCOLHAS = (
    ("esquema", Tabela.VERSAO, Chave.ESQUEMA, False),
    ("atribuicao", Tabela.VERSAO, Chave.ATRIBUICAO, False),
    ("tag_liberacao", Tabela.LIBERACAO, Chave.TAG, True),
    ("branch_versao", Tabela.BRANCHES, Chave.VERSAO, True),
    ("branch_principal", Tabela.BRANCHES, Chave.PRINCIPAL, False),
    ("fonte_tarefas", Tabela.TAREFAS, Chave.FONTE, False),
)


def _padrao_referencia(dados: Mapping[str, object], caminho: str) -> str | None:
    bruto = _tabela(dados, Tabela.REFERENCIA, caminho).get(Chave.PADRAO)
    return None if bruto is None else validar_padrao(bruto, caminho)


Camada = tuple[Mapping[str, object], str]


def _mesclar(camadas: list[Camada], caminho: str | None = None) -> ConfigProjeto:
    """Mescla chave a chave, a última camada vencendo."""
    piso: Escolhido | None = None
    padrao: str | None = None
    tarefas: dict[str, object] = {}
    escolhas: dict[str, Escolhido] = {}
    for dados, arquivo in camadas:
        if (p := _texto(dados, Tabela.VERSAO, Chave.PISO, arquivo)) is not None:
            piso = Escolhido(p, arquivo)
        if (r := _padrao_referencia(dados, arquivo)) is not None:
            padrao = r
        tarefas.update(_tabela(dados, Tabela.TAREFAS, arquivo))
        for atributo, tabela, chave, template in _ESCOLHAS:
            ler = _template if template else _texto
            if (valor := ler(dados, tabela, chave, arquivo)) is not None:
                escolhas[atributo] = Escolhido(valor, arquivo)
    return ConfigProjeto(
        piso=None if piso is None else piso.valor,
        arquivo_piso=None if piso is None else piso.arquivo,
        padrao_referencia=padrao,
        tarefas=tarefas,
        arquivos=tuple(c for _, c in camadas),
        esquema=escolhas.get("esquema"),
        atribuicao=escolhas.get("atribuicao"),
        tag_liberacao=escolhas.get("tag_liberacao"),
        branch_versao=escolhas.get("branch_versao"),
        branch_principal=escolhas.get("branch_principal"),
        fonte_tarefas=escolhas.get("fonte_tarefas"),
        caminho=caminho,
    )


def _topo(dados: Mapping[str, object], caminho: str) -> dict[str, object]:
    """O topo da config central, sem `[repos]`; `piso` aqui e erro."""
    if _texto(dados, Tabela.VERSAO, Chave.PISO, caminho) is not None:
        raise ErroDeEntrada(f"{caminho}: piso só vale em [{SECAO_REPOS}.<nome>.versao]")
    return {k: v for k, v in dados.items() if k != SECAO_REPOS}


def _secoes(
    dados: Mapping[str, object], caminho: str
) -> dict[str, Mapping[str, object]]:
    brutas = _tabela(dados, SECAO_REPOS, caminho)
    secoes: dict[str, Mapping[str, object]] = {}
    for nome in brutas:
        try:
            validar_nome_repo(nome)
        except ErroDeEntrada as e:
            raise ErroDeEntrada(f"{caminho}: [{SECAO_REPOS}.{nome!r}] {e}") from e
        secoes[nome] = _tabela(brutas, nome, caminho)
        if TABELA_AMBIENTE in secoes[nome]:
            # Banco e credenciais sao da instalacao: um [ambiente] por repo
            # sugeriria que cada repo pode ter o seu, e nao pode.
            raise ErroDeEntrada(
                f"{caminho}: [{SECAO_REPOS}.{nome}.{TABELA_AMBIENTE}] não vale; "
                f"[{TABELA_AMBIENTE}] só no topo"
            )
    return secoes


def _caminho_da_secao(
    secao: Mapping[str, object], nome: str, arquivo: str
) -> str | None:
    bruto = secao.get(CHAVE_CAMINHO)
    if bruto is None:
        return None
    if not isinstance(bruto, str) or not bruto.strip():
        raise ErroDeEntrada(
            f"{arquivo}: [{SECAO_REPOS}.{nome}] {CHAVE_CAMINHO} deve ser texto "
            f"não vazio, veio {bruto!r}"
        )
    return os.path.abspath(os.path.expanduser(bruto))


def repos_configurados() -> dict[str, str | None]:
    """Nome -> caminho expandido (`None` sem `caminho`), por nome; não checa o disco."""
    arquivo = caminho_config_global()
    secoes = _secoes(_ler_toml(arquivo), arquivo)
    return {
        nome: _caminho_da_secao(secoes[nome], nome, arquivo) for nome in sorted(secoes)
    }


#: `base` é o ambiente antes do primeiro `[ambiente]`; `aplicadas`, o que ele pôs.
_estado_ambiente: dict[str, dict[str, str]] = {}
_chaves_aplicadas: set[str] = set()
_BASE = "base"


def _reiniciar_ambiente_base() -> None:
    _estado_ambiente.clear()
    _chaves_aplicadas.clear()


def aplicar_ambiente_central(central: Mapping[str, str]) -> None:
    """Aplica o `[ambiente]` sobre a base (shell + .env), desfazendo o que saiu.

    `XDG_CONFIG_HOME` nunca vem do `[ambiente]`: o caminho do central não pode
    mudar sob quem o acabou de ler.
    """
    base = _estado_ambiente.setdefault(_BASE, dict(os.environ))
    novo = {k: v for k, v in central.items() if k != VAR_XDG_CONFIG_HOME}
    for chave in _chaves_aplicadas - novo.keys():
        if chave in base:
            os.environ[chave] = base[chave]
        else:
            os.environ.pop(chave, None)
    os.environ.update(novo)
    _chaves_aplicadas.clear()
    _chaves_aplicadas.update(novo)


def ambiente_central() -> dict[str, str]:
    """`[ambiente]` do topo da config central, como variaveis de ambiente."""
    arquivo = caminho_config_global()
    return ambiente_do_documento(_ler_toml(arquivo), arquivo)


def ambiente_do_documento(dados: Mapping[str, object], arquivo: str) -> dict[str, str]:
    """`[ambiente]` de um documento já lido, como variaveis de ambiente.

    Os nomes sao os das variaveis (os mesmos do .env), para que adapters e
    plugins leiam do ambiente sem saber de onde veio. Inteiro vira texto porque
    `DATABASE_PORT = 5433` e o natural em TOML; booleano, data e lista nao tem
    uma forma textual unica, e adivinhar uma seria configurar outra coisa.
    """
    bruto = _tabela(dados, TABELA_AMBIENTE, arquivo)
    _secoes(dados, arquivo)
    ambiente: dict[str, str] = {}
    for chave, valor in bruto.items():
        if isinstance(valor, str):
            ambiente[chave] = valor
        elif isinstance(valor, int) and not isinstance(valor, bool):
            ambiente[chave] = str(valor)
        else:
            raise ErroDeEntrada(
                f"{arquivo}: [{TABELA_AMBIENTE}] {chave} deve ser texto ou inteiro, "
                f"veio {valor!r}"
            )
    return ambiente


def carregar_config_global() -> ConfigProjeto:
    """So o topo da config central."""
    arquivo = caminho_config_global()
    return config_global_do_documento(_ler_toml(arquivo), arquivo)


def config_global_do_documento(
    dados: Mapping[str, object], arquivo: str
) -> ConfigProjeto:
    return _mesclar([(_topo(dados, arquivo), arquivo)])


def carregar_config_repo(nome: str) -> ConfigProjeto:
    """Topo mesclado com `[repos.<nome>]`, a seção vencendo; valida o `caminho`."""
    arquivo = caminho_config_global()
    return config_repo_do_documento(_ler_toml(arquivo), arquivo, nome)


def config_repo_do_documento(
    dados: Mapping[str, object], arquivo: str, nome: str
) -> ConfigProjeto:
    secoes = _secoes(dados, arquivo)
    if nome not in secoes:
        existentes = ", ".join(sorted(secoes)) or "(nenhuma)"
        raise ErroDeEntrada(
            f"{arquivo}: repo {nome!r} sem seção [{SECAO_REPOS}.{nome}] "
            f"(existentes: {existentes})"
        )
    secao = secoes[nome]
    rotulo = f"{arquivo} [{SECAO_REPOS}.{nome}]"
    caminho = _caminho_da_secao(secao, nome, arquivo)
    if caminho is None:
        raise ErroDeEntrada(
            f"{arquivo}: [{SECAO_REPOS}.{nome}] {CHAVE_CAMINHO} é obrigatório"
        )
    if not os.path.isdir(caminho):
        raise ErroDeEntrada(
            f"{arquivo}: [{SECAO_REPOS}.{nome}] {CHAVE_CAMINHO} {caminho!r} "
            "não é um diretório"
        )
    sem_caminho = {k: v for k, v in secao.items() if k != CHAVE_CAMINHO}
    return _mesclar(
        [
            (_topo(dados, arquivo), arquivo),
            (sem_caminho, rotulo),
        ],
        caminho=caminho,
    )
