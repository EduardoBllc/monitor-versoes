"""Catálogo de campos da config central e leitura dela para edição pela UI."""

from __future__ import annotations

import contextlib
import hashlib
import os
import stat
import tempfile
import tomllib
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

import tomlkit
from tomlkit.exceptions import TOMLKitError

from motor import plugins
from motor.config import (
    ARQUIVO_SQLITE,
    CHAVE_CAMINHO,
    SECAO_REPOS,
    TABELA_AMBIENTE,
    WORKTREES_MANTIDAS_PADRAO,
    Chave,
    Tabela,
    VarAmbiente,
    ambiente_central,
    ambiente_do_documento,
    aplicar_ambiente_central,
    caminho_config_global,
    config_global_do_documento,
    config_repo_do_documento,
    diretorio_dados,
    validar_nome_repo,
)
from motor.errors import ErroDeEntrada, RecusaDeInvariante
from motor.montagem import (
    ATRIBUICAO_PADRAO,
    ESQUEMA_PADRAO,
    GRUPO_ATRIBUICOES,
    GRUPO_ESQUEMAS,
    GRUPO_PRS,
    GRUPO_SUGESTAO,
    GRUPO_TAREFAS,
    resolver_versionamento,
)
from motor.services.versionamento import (
    BRANCH_VERSAO_PADRAO,
    PRINCIPAL_PADRAO,
    TAG_PADRAO,
)

ORIGEM_MOTOR = "motor"


class GrupoPlugin(StrEnum):
    TAREFAS = GRUPO_TAREFAS
    PRS = GRUPO_PRS
    ESQUEMAS = GRUPO_ESQUEMAS
    ATRIBUICOES = GRUPO_ATRIBUICOES
    SUGESTAO = GRUPO_SUGESTAO


_GRUPOS = tuple(GrupoPlugin)


class Escopo(StrEnum):
    GERAL = "geral"
    REPO = "repo"
    AMBIENTE = "ambiente"


class TipoCampo(StrEnum):
    TEXTO = "texto"
    INTEIRO = "inteiro"
    ESCOLHA = "escolha"


@dataclass(frozen=True)
class Campo:
    escopo: Escopo
    tabela: str | None
    chave: str
    tipo: TipoCampo
    rotulo: str
    segredo: bool = False
    opcoes: tuple[str, ...] = ()
    origem: str = ORIGEM_MOTOR
    descricao: str = ""
    padrao: str | None = None
    exemplo: str = ""
    grupo: GrupoPlugin | None = None


@dataclass(frozen=True)
class ValorLido:
    repo: str | None
    tabela: str | None
    chave: str
    valor: str | int | bool | None
    definido: bool
    editavel: bool


@dataclass(frozen=True)
class ConfigEditavel:
    campos: list[Campo]
    valores: list[ValorLido]
    repos: list[str]
    versao: str


_G, _R, _A = Escopo.GERAL, Escopo.REPO, Escopo.AMBIENTE
_TX, _IN, _ES = TipoCampo.TEXTO, TipoCampo.INTEIRO, TipoCampo.ESCOLHA

#: Campo -> grupo cujos entry points e valores `modulo:Classe` em uso são as opções.
_GRUPO_DO_CAMPO: dict[tuple[str, str], GrupoPlugin] = {
    (Tabela.VERSAO, Chave.ESQUEMA): GrupoPlugin.ESQUEMAS,
    (Tabela.VERSAO, Chave.ATRIBUICAO): GrupoPlugin.ATRIBUICOES,
    (Tabela.TAREFAS, Chave.FONTE): GrupoPlugin.TAREFAS,
    (Tabela.PRS, Chave.FONTE): GrupoPlugin.PRS,
    (Tabela.SUGESTAO, Chave.PROVEDOR): GrupoPlugin.SUGESTAO,
}

_V = VarAmbiente
_AMB = TABELA_AMBIENTE

_CAMPOS_MOTOR = (
    Campo(
        _G,
        Tabela.VERSAO,
        Chave.ESQUEMA,
        _ES,
        "Esquema de versão",
        descricao="Plugin que define o formato da versão e de onde ela sai",
        padrao=ESQUEMA_PADRAO,
    ),
    Campo(
        _G,
        Tabela.VERSAO,
        Chave.ATRIBUICAO,
        _ES,
        "Atribuição",
        descricao="Política que decide quais tarefas são alvo de cada versão",
        padrao=ATRIBUICAO_PADRAO,
    ),
    Campo(
        _G,
        Tabela.LIBERACAO,
        Chave.TAG,
        _TX,
        "Tag de liberação",
        descricao="Tag que libera a versão; exatamente um {versao}. "
        "Sem ela, vale o critério do esquema",
        padrao=TAG_PADRAO,
        exemplo="v{versao}",
    ),
    Campo(
        _G,
        Tabela.BRANCHES,
        Chave.VERSAO,
        _TX,
        "Branch de versão",
        descricao="Branch de cada versão; exatamente um {versao}",
        padrao=BRANCH_VERSAO_PADRAO,
        exemplo="release/{versao}",
    ),
    Campo(
        _G,
        Tabela.BRANCHES,
        Chave.PRINCIPAL,
        _TX,
        "Branch principal",
        descricao="Branch de onde as versões novas saem",
        padrao=PRINCIPAL_PADRAO,
        exemplo="develop",
    ),
    Campo(
        _G,
        Tabela.REFERENCIA,
        Chave.PADRAO,
        _TX,
        "Padrão de referência",
        descricao="Como a tarefa aparece na mensagem do commit; exatamente um {id}. "
        "Sem ele, vale o que a fonte de tarefas propõe",
        exemplo="ch{id}",
    ),
    Campo(
        _G,
        Tabela.TAREFAS,
        Chave.FONTE,
        _ES,
        "Fonte de tarefas",
        descricao="Plugin que lista as tarefas; sem ela, só a lista manual",
    ),
    Campo(
        _G,
        Tabela.PRS,
        Chave.FONTE,
        _ES,
        "Fonte de PR",
        descricao="Plugin do host de PR; sem ela, os commits saem só do grep na principal",
    ),
    Campo(
        _R,
        None,
        CHAVE_CAMINHO,
        _TX,
        "Caminho",
        descricao="Diretório do clone local do repo",
        exemplo="~/projetos/meu-repo",
    ),
    Campo(
        _R,
        Tabela.VERSAO,
        Chave.PISO,
        _TX,
        "Piso de versão",
        descricao="Menor versão cujas tarefas são buscadas; sem ele, nada é cortado",
        exemplo="13.0.0",
    ),
    Campo(
        _A,
        _AMB,
        _V.DATABASE_SQLITE_PATH,
        _TX,
        "Arquivo do SQLite",
        descricao="Arquivo do banco SQLite",
        padrao=os.path.join(diretorio_dados(), ARQUIVO_SQLITE),
        exemplo="~/estado.db",
    ),
    Campo(
        _A,
        _AMB,
        _V.WORKTREES_MANTIDAS,
        _IN,
        "Worktrees mantidas",
        descricao="Worktrees de versão mantidas em disco para o próximo comando "
        "reusar; 0 descarta a cada run",
        padrao=str(WORKTREES_MANTIDAS_PADRAO),
    ),
)


def _mapa(valor: object) -> Mapping[str, object]:
    return valor if isinstance(valor, dict) else {}


def _secoes(dados: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    return {n: _mapa(s) for n, s in _mapa(dados.get(SECAO_REPOS)).items()}


def _em_uso(dados: Mapping[str, object], tabela: str, chave: str) -> set[str]:
    """Valores `modulo:Classe` da chave, no topo e em cada seção de repo."""
    camadas = [dados, *_secoes(dados).values()]
    valores = {_mapa(c.get(tabela)).get(chave) for c in camadas}
    return {v for v in valores if isinstance(v, str) and plugins.MARCADOR_IMPORT in v}


def _campos_do_plugin(grupo: GrupoPlugin, nome: str) -> tuple[Campo, ...]:
    try:
        declarados = getattr(plugins.carregar_plugin(grupo, nome), "campos_config", ())
    except Exception:  # plugin de terceiro pode quebrar no import de qualquer jeito
        return ()
    if not isinstance(declarados, tuple) or not all(
        isinstance(c, Campo) for c in declarados
    ):
        return ()
    # O `[ambiente]` só tem uma tabela; aceitar outra deixaria o segredo sem máscara.
    return tuple(
        replace(
            c,
            origem=nome,
            grupo=grupo,
            tabela=TABELA_AMBIENTE if c.escopo is Escopo.AMBIENTE else c.tabela,
        )
        for c in declarados
    )


def catalogo_campos(dados: Mapping[str, object]) -> list[Campo]:
    """Campos do motor e os que os plugins instalados ou em uso declaram."""
    instalados = {g: plugins.nomes_instalados(g) for g in _GRUPOS}
    em_uso = {g: _em_uso(dados, *tc) for tc, g in _GRUPO_DO_CAMPO.items()}
    campos: list[Campo] = []
    for base in _CAMPOS_MOTOR:
        grupo = _GRUPO_DO_CAMPO.get((base.tabela or "", base.chave))
        opcoes = tuple(instalados[grupo] + sorted(em_uso[grupo])) if grupo else None
        campos.append(base if opcoes is None else replace(base, opcoes=opcoes))
    vistos = {(c.escopo, c.tabela, c.chave) for c in campos}
    for grupo in _GRUPOS:
        for nome in [*instalados[grupo], *sorted(em_uso[grupo])]:
            for c in _campos_do_plugin(grupo, nome):
                if (c.escopo, c.tabela, c.chave) not in vistos:
                    vistos.add((c.escopo, c.tabela, c.chave))
                    campos.append(c)
    return campos


def _valor(
    repo: str | None,
    tabela: str | None,
    chave: str,
    bruto: object,
    segredos: set[tuple[str | None, str]],
) -> ValorLido:
    if (tabela, chave) in segredos:
        return ValorLido(repo, tabela, chave, None, True, True)
    if isinstance(bruto, str | int):  # bool é int
        return ValorLido(repo, tabela, chave, bruto, True, True)
    return ValorLido(repo, tabela, chave, None, True, False)


def _valores_da_secao(
    repo: str | None, secao: Mapping[str, object], segredos: set[tuple[str | None, str]]
) -> list[ValorLido]:
    lidos: list[ValorLido] = []
    for chave, bruto in secao.items():
        if isinstance(bruto, dict):
            lidos += [_valor(repo, chave, k, v, segredos) for k, v in bruto.items()]
        elif repo is not None:
            lidos.append(_valor(repo, None, chave, bruto, segredos))
    return lidos


def _ler_bytes(arquivo: str) -> bytes:
    try:
        with open(arquivo, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return b""
    except OSError as e:
        raise ErroDeEntrada(f"{arquivo}: não foi possível ler ({e})") from e


def ler_para_edicao() -> ConfigEditavel:
    """Lê a config central com segredos mascarados e o token de versão."""
    arquivo = caminho_config_global()
    bruto = _ler_bytes(arquivo)
    try:
        dados = tomllib.loads(bruto.decode())
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise ErroDeEntrada(f"{arquivo}: TOML inválido ({e})") from e
    campos = catalogo_campos(dados)
    segredos = {(c.tabela, c.chave) for c in campos if c.segredo}
    topo = {k: v for k, v in dados.items() if k != SECAO_REPOS}
    valores = _valores_da_secao(None, topo, segredos)
    secoes = _secoes(dados)
    for nome in sorted(secoes):
        valores += _valores_da_secao(nome, secoes[nome], segredos)
    return ConfigEditavel(
        campos, valores, sorted(secoes), hashlib.sha256(bruto).hexdigest()
    )


class AcaoAlteracao(StrEnum):
    DEFINIR = "definir"
    REMOVER = "remover"
    CRIAR_REPO = "criar_repo"
    REMOVER_REPO = "remover_repo"


@dataclass(frozen=True)
class Alteracao:
    """`repo=None` é o topo; `tabela=None` é chave direta do topo ou da seção."""

    acao: AcaoAlteracao
    repo: str | None = None
    tabela: str | None = None
    chave: str | None = None
    valor: str | int | bool | None = None


MENSAGEM_VERSAO_VELHA = "a config mudou desde que foi aberta; recarregue"
MODO_ARQUIVO_NOVO = 0o600

Documento = MutableMapping[str, Any]


def _editavel(valor: object) -> bool:
    return isinstance(valor, str | int)  # bool é int


def _chave(alteracao: Alteracao) -> str:
    if not alteracao.chave:
        raise ErroDeEntrada(f"{alteracao.acao}: chave não informada")
    return alteracao.chave


def _repos(doc: Documento) -> Documento:
    if SECAO_REPOS not in doc:
        doc[SECAO_REPOS] = tomlkit.table(is_super_table=True)
    repos: Documento = doc[SECAO_REPOS]
    return repos


def _secao(doc: Documento, repo: str | None) -> Documento | None:
    if repo is None:
        return doc
    secao = _mapa(doc.get(SECAO_REPOS)).get(repo)
    return secao if isinstance(secao, MutableMapping) else None


def _definir(doc: Documento, alteracao: Alteracao) -> None:
    chave = _chave(alteracao)
    if alteracao.valor is None:
        raise ErroDeEntrada(f"{chave}: valor não informado")
    alvo = _secao(doc, alteracao.repo)
    if alvo is None:
        raise ErroDeEntrada(f"repo {alteracao.repo!r} não existe")
    if alteracao.tabela is not None:
        if alteracao.tabela not in alvo:
            alvo[alteracao.tabela] = tomlkit.table()
        alvo = alvo[alteracao.tabela]
        if not isinstance(alvo, MutableMapping):
            raise ErroDeEntrada(f"[{alteracao.tabela}] não é uma tabela")
    if chave in alvo and not _editavel(alvo[chave]):
        raise ErroDeEntrada(f"{chave}: valor só de leitura")
    alvo[chave] = alteracao.valor


def _remover(doc: Documento, alteracao: Alteracao) -> None:
    chave = _chave(alteracao)
    secao = _secao(doc, alteracao.repo)
    alvo = secao if alteracao.tabela is None else _mapa(secao).get(alteracao.tabela)
    if not isinstance(alvo, MutableMapping) or chave not in alvo:
        return
    if not _editavel(alvo[chave]):
        raise ErroDeEntrada(f"{chave}: valor só de leitura")
    del alvo[chave]
    if alteracao.tabela is not None and not alvo and secao is not None:
        del secao[alteracao.tabela]


def _aplicar(doc: Documento, alteracao: Alteracao) -> None:
    match alteracao.acao:
        case AcaoAlteracao.DEFINIR:
            _definir(doc, alteracao)
        case AcaoAlteracao.REMOVER:
            _remover(doc, alteracao)
        case AcaoAlteracao.CRIAR_REPO:
            nome = validar_nome_repo(alteracao.repo or "")
            repos = _repos(doc)
            if nome in repos:
                raise ErroDeEntrada(f"repo {nome!r} já existe")
            repos[nome] = tomlkit.table()
        case AcaoAlteracao.REMOVER_REPO:
            if alteracao.repo not in _mapa(doc.get(SECAO_REPOS)):
                raise ErroDeEntrada(f"repo {alteracao.repo!r} não existe")
            del doc[SECAO_REPOS][alteracao.repo]


def _validar_tipo(campo: Campo, valor: object) -> None:
    if campo.tipo is TipoCampo.INTEIRO:
        valido = (isinstance(valor, str) and valor.isascii() and valor.isdigit()) or (
            isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0
        )
    elif campo.tipo is TipoCampo.ESCOLHA and campo.origem == ORIGEM_MOTOR:
        valido = valor in campo.opcoes or (
            isinstance(valor, str) and plugins.MARCADOR_IMPORT in valor
        )
    else:
        return
    if not valido:
        exibido = "" if campo.segredo else f" {valor!r}"
        raise ErroDeEntrada(
            f"[{campo.tabela}] {campo.chave}: valor inválido{exibido} "
            f"(esperado {campo.tipo})"
        )


def _validar(dados: Mapping[str, object], arquivo: str) -> None:
    """As mesmas regras da leitura, mais o tipo de cada campo declarado."""
    ambiente_do_documento(dados, arquivo)
    secoes = _secoes(dados)
    configs = [config_global_do_documento(dados, arquivo)]
    configs += [config_repo_do_documento(dados, arquivo, n) for n in secoes]
    for config in configs:
        resolver_versionamento(config)
        if config.fonte_tarefas is not None:
            plugins.carregar_plugin(GRUPO_TAREFAS, config.fonte_tarefas.valor)
    topo = {k: v for k, v in dados.items() if k != SECAO_REPOS}
    for campo in catalogo_campos(dados):
        for camada in [topo, *secoes.values()]:
            alvo = camada if campo.tabela is None else _mapa(camada.get(campo.tabela))
            if campo.chave in alvo:
                _validar_tipo(campo, alvo[campo.chave])


def _gravar_atomico(arquivo: str, conteudo: bytes) -> None:
    # config.toml symlinkado (dotfiles) continua link
    arquivo = os.path.realpath(arquivo)
    diretorio = os.path.dirname(arquivo)
    try:
        os.makedirs(diretorio, exist_ok=True)
        try:
            modo = stat.S_IMODE(os.stat(arquivo).st_mode)
        except FileNotFoundError:
            modo = MODO_ARQUIVO_NOVO
        fd, temporario = tempfile.mkstemp(dir=diretorio, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                os.fchmod(f.fileno(), modo)
                f.write(conteudo)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporario, arquivo)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporario)
            raise
    except OSError as e:
        raise ErroDeEntrada(f"{arquivo}: não foi possível gravar ({e})") from e


def rascunho(alteracoes: list[Alteracao], versao: str) -> str:
    """Config central com as alterações, validada sem gravar; recusa `versao` velha."""
    arquivo = caminho_config_global()
    bruto = _ler_bytes(arquivo)
    if hashlib.sha256(bruto).hexdigest() != versao:
        raise RecusaDeInvariante(MENSAGEM_VERSAO_VELHA)
    try:
        doc = tomlkit.parse(bruto.decode())
    except (TOMLKitError, UnicodeDecodeError) as e:
        raise ErroDeEntrada(f"{arquivo}: TOML inválido ({e})") from e
    for alteracao in alteracoes:
        _aplicar(doc, alteracao)
    texto = tomlkit.dumps(doc)
    try:
        candidato = tomllib.loads(texto)
    except tomllib.TOMLDecodeError as e:
        raise ErroDeEntrada(f"{arquivo}: alteração gera TOML inválido ({e})") from e
    _validar(candidato, arquivo)
    return texto


def gravar(alteracoes: list[Alteracao], versao: str) -> ConfigEditavel:
    """Aplica, valida e grava a config central; recusa se ela mudou desde `versao`."""
    texto = rascunho(alteracoes, versao)
    _gravar_atomico(caminho_config_global(), texto.encode())
    aplicar_ambiente_central(ambiente_central())
    return ler_para_edicao()
