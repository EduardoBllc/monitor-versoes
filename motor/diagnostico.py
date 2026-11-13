"""Diagnóstico da instalação: checa cada peça e diz qual falhou e como corrigir.

Tudo chega por parâmetro (ambiente, abertura de sessão, `head` do
alembic, config central), para ser testável sem banco real nem rede. Não tem efeito colateral:
não escreve no banco, não roda git, não exige repo cadastrado.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Collection, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from motor.adapters.estado import sqlite as estado_sqlite
from motor.config import SECAO_REPOS, Chave, ConfigProjeto, Tabela, checar_backend
from motor.errors import ErroDeEntrada, MotorError, formatar_com_notas
from motor.montagem import (
    instanciar_fonte_tarefas,
    instanciar_host_pr,
    instanciar_provedor_sugestao,
)


class Peca(enum.StrEnum):
    AMBIENTE = "Ambiente"
    VARIAVEIS = "Variáveis"
    SQLITE = "SQLite"
    MIGRACAO = "Migração"
    REPOS = "Repos"
    TAREFAS = "Tarefas"
    PRS = "Fonte de PR"
    SUGESTAO = "Sugestão"


class Estado(enum.Enum):
    OK = "OK"
    FALHA = "FALHA"
    NAO_VERIFICADA = "não verificada"
    NAO_CONFIGURADO = "não configurado"
    AVISO = "aviso"


@dataclass(frozen=True)
class Resultado:
    peca: Peca
    estado: Estado
    detalhe: str = ""
    correcao: str = ""


def falhou(resultados: list[Resultado]) -> bool:
    """Só `FALHA` conta; `aviso`, `não verificada` e `não configurado` não."""
    return any(r.estado is Estado.FALHA for r in resultados)


def _falha(peca: Peca, erro: MotorError, correcao: str) -> Resultado:
    return Resultado(peca, Estado.FALHA, formatar_com_notas(erro), correcao)


def _problemas_do_banco(env: Mapping[str, str]) -> list[str]:
    """A config de backend recusada, como o motor a recusaria; sem conectar."""
    try:
        checar_backend(env)
    except ErroDeEntrada as e:
        return [str(e)]
    return []


def onde_das_credenciais(config_em: str, ambiente: str) -> str:
    """Onde a correção manda pôr credencial: o `[ambiente]` do central ou o `.env`."""
    arquivo = ".env.development" if ambiente == "development" else ".env"
    return f"[ambiente] de {config_em} (ou no {arquivo})"


# Oito parâmetros, sete nomeados: cada um é uma peça injetada para o teste
# rodar sem banco, rede nem arquivo de config reais.
def diagnosticar(  # noqa: PLR0913
    env: Mapping[str, str],
    *,
    abrir_sessao: Callable[..., AbstractContextManager[Session]],
    head: str,
    ambiente: str,
    config_central: Callable[[], ConfigProjeto],
    repos: Callable[[], Mapping[str, str | None]],
    config_em: str,
    erro_ambiente: MotorError | None = None,
) -> list[Resultado]:
    """`config_em` é o caminho do config central; `erro_ambiente`, o erro ao ler
    o `[ambiente]` dele — o diagnóstico mostra e segue sem o central."""
    migrar = (
        "monitor-versoes --env development migrar"
        if ambiente == "development"
        else "monitor-versoes migrar"
    )
    onde = onde_das_credenciais(config_em, ambiente)

    problemas = _problemas_do_banco(env)

    resultados = []
    if erro_ambiente is not None:
        resultados.append(_falha(Peca.AMBIENTE, erro_ambiente, f"corrigir {config_em}"))
    resultados.append(
        Resultado(
            Peca.VARIAVEIS,
            Estado.FALHA,
            "; ".join(problemas),
            f"corrigir em {onde}",
        )
        if problemas
        else Resultado(Peca.VARIAVEIS, Estado.OK, "configuração do estado aceita")
    )
    resultados += _banco(abrir_sessao, problemas, head, migrar)
    banco_ok = [
        r.estado for r in resultados if r.peca in (Peca.SQLITE, Peca.MIGRACAO)
    ] == [
        Estado.OK,
        Estado.OK,
    ]
    resultados += _repos(abrir_sessao, repos, banco_ok)
    resultados.append(_tarefas(config_central, onde))
    resultados.append(_prs(config_central, onde))
    resultados += _sugestao(config_central, onde)
    return resultados


def _banco_fora(peca: Peca, erro: MotorError, dica: str) -> list[Resultado]:
    """Banco fora implica Migração não verificada."""
    return [
        _falha(peca, erro, dica),
        Resultado(Peca.MIGRACAO, Estado.NAO_VERIFICADA, f"{peca} indisponível"),
    ]


def _banco(
    abrir_sessao: Callable[..., AbstractContextManager[Session]],
    problemas_banco: list[str],
    head: str,
    migrar: str,
) -> list[Resultado]:
    peca = Peca.SQLITE
    if problemas_banco:
        motivo = "variáveis do banco inválidas"
        return [
            Resultado(peca, Estado.NAO_VERIFICADA, motivo),
            Resultado(Peca.MIGRACAO, Estado.NAO_VERIFICADA, motivo),
        ]
    dica_banco = "conferir DATABASE_SQLITE_PATH e as permissões do arquivo"
    # Banco vazio: o primeiro uso migra. Banco já migrado numa revisão antiga: o
    # garantir_esquema não o toca, só o `migrar` leva ao head.
    primeiro_uso = (
        "rodar qualquer comando do motor (aplica as migrations no primeiro uso)"
    )
    try:
        # garantir=False: o diagnóstico só olha, não cria arquivo nem esquema.
        with abrir_sessao(garantir=False) as sessao:
            estado = estado_sqlite.Estado(sessao=sessao)
            try:
                estado.verificar_conexao()
            except MotorError as e:
                return _banco_fora(peca, e, dica_banco)
            conexao = Resultado(peca, Estado.OK, "conexão funciona")
            try:
                revisao = estado.revisao_migracao()
            except MotorError as e:
                return [conexao, _falha(Peca.MIGRACAO, e, dica_banco)]
    except MotorError as e:
        return _banco_fora(peca, e, dica_banco)
    if revisao is None:
        migracao = Resultado(
            Peca.MIGRACAO, Estado.FALHA, "banco sem migração aplicada", primeiro_uso
        )
    elif revisao != head:
        migracao = Resultado(
            Peca.MIGRACAO,
            Estado.FALHA,
            f"banco na revisão {revisao}, esperado {head}",
            migrar,
        )
    else:
        migracao = Resultado(Peca.MIGRACAO, Estado.OK, f"revisão {head}")
    return [conexao, migracao]


def _estado_sem_secao(
    abrir_sessao: Callable[..., AbstractContextManager[Session]], nomes: set[str]
) -> list[Resultado]:
    try:
        with abrir_sessao(garantir=False) as sessao:
            no_banco = [
                r.nome for r in estado_sqlite.Estado(sessao=sessao).listar_repos()
            ]
    except MotorError as e:
        return [Resultado(Peca.REPOS, Estado.NAO_VERIFICADA, formatar_com_notas(e))]
    return [
        Resultado(
            Peca.REPOS,
            Estado.AVISO,
            f"estado de {nome!r} no banco sem seção [{SECAO_REPOS}.{nome}] "
            "no config.toml",
            "remover o estado do banco ou criar a seção",
        )
        for nome in no_banco
        if nome not in nomes
    ]


_CORRECAO_REPOS = f"conferir [{SECAO_REPOS}.<nome>] no config.toml central"


def _caminho_do_repo(nome: str, caminho: str | None) -> Resultado:
    if caminho is None:
        detalhe = f"[{SECAO_REPOS}.{nome}] sem caminho"
    elif not Path(caminho).is_dir():
        detalhe = f"[{SECAO_REPOS}.{nome}] caminho não é diretório: {caminho}"
    else:
        return Resultado(Peca.REPOS, Estado.OK, "caminho encontrado")
    return Resultado(Peca.REPOS, Estado.FALHA, detalhe, _CORRECAO_REPOS)


def _repos(
    abrir_sessao: Callable[..., AbstractContextManager[Session]],
    repos: Callable[[], Mapping[str, str | None]],
    banco_ok: bool,
) -> list[Resultado]:
    """Seções `[repos.<nome>]` do config.toml central contra disco e banco."""
    try:
        configurados = repos()
    except MotorError as e:
        return [_falha(Peca.REPOS, e, _CORRECAO_REPOS)]
    linhas = [
        r
        for nome, caminho in configurados.items()
        if (r := _caminho_do_repo(nome, caminho)).estado is Estado.FALHA
    ]
    if banco_ok:
        linhas += _estado_sem_secao(abrir_sessao, set(configurados))
    else:
        linhas.append(
            Resultado(
                Peca.REPOS,
                Estado.NAO_VERIFICADA,
                "banco indisponível: estado não conferido",
            )
        )
    if not linhas:
        return [
            Resultado(
                Peca.REPOS, Estado.OK, f"{len(configurados)} repo(s) configurado(s)"
            )
        ]
    return linhas


# Seis parâmetros: cada um é uma peça da linha (peça, config, tabela, chave...).
def _plugin_da_config(  # noqa: PLR0913
    peca: Peca,
    config_central: Callable[[], ConfigProjeto],
    onde: str,
    tabela: Tabela,
    instanciar: Callable[[ConfigProjeto], object | None],
    chave: str = Chave.FONTE,
) -> Resultado:
    """O plugin de `[tabela] fonte` do `config.toml` central: o diagnóstico não
    tem repo. `instanciar` devolve `None` quando a `fonte` não está definida.

    Credencial só é conferida se o plugin oferece `verificar_credenciais`.
    """
    plugins = f"conferir [{tabela}] {chave} e os plugins instalados"
    try:
        plugin = instanciar(config_central())
    except MotorError as e:
        return _falha(peca, e, plugins)
    if plugin is None:
        return Resultado(
            peca,
            Estado.NAO_CONFIGURADO,
            f"sem [{tabela}] {chave} no config.toml central",
            f"definir [{tabela}] {chave} no config.toml central",
        )
    verificar = getattr(plugin, "verificar_credenciais", None)
    if not callable(verificar):
        return Resultado(
            peca, Estado.NAO_VERIFICADA, "o plugin não oferece verificação"
        )
    try:
        verificar()
    except MotorError as e:
        return _falha(peca, e, f"conferir as credenciais do plugin em {onde}")
    return Resultado(peca, Estado.OK, "credenciais aceitas")


def _tarefas(config_central: Callable[[], ConfigProjeto], onde: str) -> Resultado:
    def instanciar(config: ConfigProjeto) -> object | None:
        if config.fonte_tarefas is None:
            return None
        return instanciar_fonte_tarefas(config)

    return _plugin_da_config(
        Peca.TAREFAS, config_central, onde, Tabela.TAREFAS, instanciar
    )


def _sem_repo() -> str:
    raise ErroDeEntrada("o diagnóstico não tem repo")


def _prs(config_central: Callable[[], ConfigProjeto], onde: str) -> Resultado:
    """`verificar_credenciais` do host não precisa de repo: a URL do `origin`
    que o host pedir falha com erro de entrada."""

    def instanciar(config: ConfigProjeto) -> object | None:
        if config.fonte_prs is None:
            return None
        return instanciar_host_pr(config, _sem_repo)

    return _plugin_da_config(Peca.PRS, config_central, onde, Tabela.PRS, instanciar)


def _sugestao(
    config_central: Callable[[], ConfigProjeto], onde: str
) -> list[Resultado]:
    """Só existe linha com `[sugestao] provedor`; sem ele, nada a dizer."""
    resultado = _plugin_da_config(
        Peca.SUGESTAO,
        config_central,
        onde,
        Tabela.SUGESTAO,
        instanciar_provedor_sugestao,
        Chave.PROVEDOR,
    )
    return [] if resultado.estado is Estado.NAO_CONFIGURADO else [resultado]


class PecaTestavel(enum.StrEnum):
    """As peças que a web testa uma a uma, sobre o rascunho da config."""

    PRS = "prs"
    TAREFAS = "tarefas"
    REPO = "repo"


PECA_DO_DIAGNOSTICO = {
    PecaTestavel.PRS: Peca.PRS,
    PecaTestavel.TAREFAS: Peca.TAREFAS,
    PecaTestavel.REPO: Peca.REPOS,
}


def diagnosticar_peca(
    peca: PecaTestavel,
    *,
    config_central: Callable[[], ConfigProjeto],
    repos: Callable[[], Mapping[str, str | None]],
    onde: str,
    repo: str | None = None,
) -> Resultado:
    """A linha do diagnóstico de uma peça só; `onde` é o que a correção cita."""
    match peca:
        case PecaTestavel.PRS:
            return _prs(config_central, onde)
        case PecaTestavel.TAREFAS:
            return _tarefas(config_central, onde)
        case PecaTestavel.REPO:
            configurados = repos()
            nome = repo_existente(repo, configurados)
            return _caminho_do_repo(nome, configurados[nome])


def repo_existente(repo: str | None, nomes: Collection[str]) -> str:
    """O repo a testar, que precisa estar entre os `nomes` da config."""
    if repo is None or repo not in nomes:
        raise ErroDeEntrada(f"repo {repo!r} não existe")
    return repo


def formatar(resultado: Resultado) -> str:
    linha = f"{resultado.estado.value}  {resultado.peca}"
    if resultado.detalhe:
        linha += f": {resultado.detalhe}"
    if resultado.correcao:
        linha += f" -> {resultado.correcao}"
    return linha


__all__ = [
    "Estado",
    "Peca",
    "PecaTestavel",
    "Resultado",
    "diagnosticar",
    "diagnosticar_peca",
    "falhou",
    "formatar",
    "onde_das_credenciais",
    "repo_existente",
]
