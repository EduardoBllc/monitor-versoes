"""Cola entre as telas (TUI, web) e o motor: descoberta, runners e validação."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Protocol

from sqlalchemy.orm import Session

from motor.adapters.git.subprocess import new_git_subprocess
from motor.config import carregar_config_repo, repos_configurados
from motor.domain.conflito import PropostaDeBloco
from motor.domain.types import JulgamentoOrfao, VersionStatus
from motor.engine.atualizar import (
    AtualizarResult,
    atualizar,
    atualizar_abort,
    atualizar_continue,
    previa_atualizacao,
)
from motor.engine.conflito import (
    ConflitoAberto,
    ConteudoDoConflito,
    ler_arquivo,
    ler_conflito,
    propor_resolucao,
    reabrir_arquivo,
    resolver_arquivo,
)
from motor.engine.consultar import ChamadoConsultado, consultar
from motor.engine.criar import criar
from motor.engine.deps import Deps
from motor.engine.orfaos import OrfaoDaVersao, julgar_orfao, listar_orfaos
from motor.engine.verificar import verificar
from motor.errors import ErroDeEntrada, MotorError, NaoEncontrado
from motor.montagem import abrir_sessao, montar_deps, resolver_versionamento
from motor.ports import GitRepo
from motor.progresso import Progresso, RelatorProgresso, silencioso
from motor.services.catalogo import Catalogo
from motor.services.versionamento import Versionamento
from motor.trava import Trava, travar


@dataclass(frozen=True)
class RepoOption:
    nome: str
    caminho: str | None
    # Piso da config do projeto (`[versao] piso`); None = nada cortado.
    piso_versao: str | None = None

    @property
    def disponivel(self) -> bool:
        return self.caminho is not None


def travar_repo(repo: RepoOption) -> Trava | None:
    """Lock do clone do repo (decisão 032); `None` quando não há checkout.

    Repo sem checkout não trava: falha como sempre, dentro do runner.
    """
    if repo.caminho is None:
        return None
    return travar(repo.nome, repo.caminho)


@dataclass(frozen=True)
class Resolucao:
    caminho: str
    conteudo: str | None
    versao_disco: str


@dataclass(frozen=True)
class PedidoProposta:
    caminho: str
    versao_disco: str
    ordens: list[int]


@dataclass(frozen=True)
class VersionOption:
    numero: str
    liberada: bool


RepoLoader = Callable[[], list[RepoOption]]
VersionLoader = Callable[[RepoOption], list[VersionOption]]
VerifyRunner = Callable[[RepoOption, str, bool], VersionStatus]
UpdateRunner = Callable[[RepoOption, str], AtualizarResult]
PreviewRunner = Callable[[RepoOption, str], VersionStatus]
AbortRunner = Callable[[RepoOption, str], None]
CriarRunner = Callable[[RepoOption, str], AtualizarResult]
VersionamentoLoader = Callable[[RepoOption], Versionamento]
LerConflitoRunner = Callable[[RepoOption, str], ConflitoAberto]
LerArquivoConflitoRunner = Callable[[RepoOption, str, str], ConteudoDoConflito]
ResolverArquivoRunner = Callable[[RepoOption, str, Resolucao], None]
ReabrirArquivoRunner = Callable[[RepoOption, str, str], None]
ProporRunner = Callable[[RepoOption, str, PedidoProposta], list[PropostaDeBloco]]


class ContinueRunner(Protocol):
    """Como UpdateRunner, mais o `allow_empty` do `atualizar_continue`: e a
    confirmacao do operador de que a resolucao sem alteracao pode entrar como
    commit vazio."""

    def __call__(
        self, repo: RepoOption, versao: str, /, *, allow_empty: bool = False
    ) -> AtualizarResult: ...


ConsultaRunner = Callable[[RepoOption, str], list[ChamadoConsultado]]
OrfaosRunner = Callable[[RepoOption, str], list[OrfaoDaVersao]]
# (repo, versao, hash, chamado ou None para "nenhum", motivo)
JulgarRunner = Callable[[RepoOption, str, str, str | None, str], JulgamentoOrfao]


@dataclass(frozen=True)
class Runners:
    """O que as telas (TUI e daemon web) chamam para falar com o motor. Os
    opcionais ausentes deixam a acao correspondente indisponivel."""

    carregar_repos: RepoLoader
    carregar_versoes: VersionLoader
    executar: VerifyRunner
    atualizar_repo: UpdateRunner | None = None
    continuar_repo: ContinueRunner | None = None
    abortar_repo: AbortRunner | None = None
    consultar_versao: ConsultaRunner | None = None
    criar_repo: CriarRunner | None = None
    previa_atualizacao: PreviewRunner | None = None
    # Sem ele, o versionamento sai da config do repo (`versionamento_do_repo`).
    versionamento_repo: VersionamentoLoader | None = None
    ler_conflito: LerConflitoRunner | None = None
    ler_arquivo_conflito: LerArquivoConflitoRunner | None = None
    resolver_arquivo_conflito: ResolverArquivoRunner | None = None
    reabrir_arquivo_conflito: ReabrirArquivoRunner | None = None
    propor_resolucao: ProporRunner | None = None
    listar_orfaos: OrfaosRunner | None = None
    julgar_orfao: JulgarRunner | None = None


def descobrir_repos(
    repos: Mapping[str, str | None], *, progresso: RelatorProgresso = silencioso
) -> list[RepoOption]:
    opcoes = []
    for indice, (nome, caminho) in enumerate(repos.items(), start=1):
        progresso(Progresso("procurando os checkouts", indice, len(repos)))
        achado = caminho if caminho is not None and os.path.isdir(caminho) else None
        opcoes.append(
            RepoOption(
                nome=nome,
                caminho=achado,
                piso_versao=None if achado is None else _piso_da_config(nome),
            )
        )
    return opcoes


def _piso_da_config(nome: str) -> str | None:
    """Piso da seção do repo; config invalida deixa `None` em vez de derrubar a
    lista (o erro aparece ao operar o repo, pela montagem)."""
    try:
        return resolver_versionamento(carregar_config_repo(nome)).piso
    except ErroDeEntrada:
        return None


def descobrir_versoes(
    git: GitRepo,
    versionamento: Versionamento,
    *,
    progresso: RelatorProgresso = silencioso,
) -> list[VersionOption]:
    progresso(Progresso("buscando refs do origin"))
    git.fetch("origin")
    catalogo = Catalogo(git, versionamento)
    liberadas = catalogo.liberadas()
    return [
        VersionOption(numero, numero in liberadas)
        for numero in reversed(catalogo.existentes())
    ]


def repos_do_ambiente(*, progresso: RelatorProgresso = silencioso) -> list[RepoOption]:
    return descobrir_repos(repos_configurados(), progresso=progresso)


def versionamento_do_repo(repo: RepoOption) -> Versionamento:
    return resolver_versionamento(carregar_config_repo(repo.nome))


def versoes_do_repo(
    repo: RepoOption, *, progresso: RelatorProgresso = silencioso
) -> list[VersionOption]:
    if repo.caminho is None:
        return []
    # Config invalida sobe como a falha de git ao listar versoes: o operador ve
    # o erro ao escolher o repo.
    versionamento = versionamento_do_repo(repo)
    return descobrir_versoes(
        new_git_subprocess(repo.caminho, progresso=progresso),
        versionamento,
        progresso=progresso,
    )


def _deps_do_repo(
    repo: RepoOption, sessao: Session, progresso: RelatorProgresso = silencioso
) -> Deps:
    if repo.caminho is None:
        raise NaoEncontrado("checkout local não encontrado")
    # Sem flags: a fonte de PR e a de tasks sao sempre as da config.
    return montar_deps(repo.nome, sessao, progresso=progresso)


def verificar_repo(
    repo: RepoOption,
    versao: str,
    auditar: bool,
    *,
    progresso: RelatorProgresso = silencioso,
) -> VersionStatus:
    with abrir_sessao() as sessao:
        deps = _deps_do_repo(repo, sessao, progresso)
        return verificar(deps, versao, auditar=auditar)


def atualizar_repo(
    repo: RepoOption, versao: str, *, progresso: RelatorProgresso = silencioso
) -> AtualizarResult:
    with abrir_sessao() as sessao:
        return atualizar(_deps_do_repo(repo, sessao, progresso), versao)


def previa_repo(
    repo: RepoOption, versao: str, *, progresso: RelatorProgresso = silencioso
) -> VersionStatus:
    with abrir_sessao() as sessao:
        return previa_atualizacao(_deps_do_repo(repo, sessao, progresso), versao)


def continuar_repo(
    repo: RepoOption,
    versao: str,
    *,
    allow_empty: bool = False,
    progresso: RelatorProgresso = silencioso,
) -> AtualizarResult:
    with abrir_sessao() as sessao:
        return atualizar_continue(
            _deps_do_repo(repo, sessao, progresso), versao, allow_empty=allow_empty
        )


def abortar_repo(
    repo: RepoOption, versao: str, *, progresso: RelatorProgresso = silencioso
) -> None:
    with abrir_sessao() as sessao:
        atualizar_abort(_deps_do_repo(repo, sessao, progresso), versao)


def ler_conflito_repo(
    repo: RepoOption, versao: str, *, progresso: RelatorProgresso = silencioso
) -> ConflitoAberto:
    with abrir_sessao() as sessao:
        return ler_conflito(_deps_do_repo(repo, sessao, progresso), versao)


def ler_arquivo_conflito_repo(
    repo: RepoOption,
    versao: str,
    caminho: str,
    *,
    progresso: RelatorProgresso = silencioso,
) -> ConteudoDoConflito:
    with abrir_sessao() as sessao:
        return ler_arquivo(_deps_do_repo(repo, sessao, progresso), versao, caminho)


def resolver_arquivo_conflito_repo(
    repo: RepoOption,
    versao: str,
    resolucao: Resolucao,
    *,
    progresso: RelatorProgresso = silencioso,
) -> None:
    with abrir_sessao() as sessao:
        resolver_arquivo(
            _deps_do_repo(repo, sessao, progresso),
            versao,
            resolucao.caminho,
            resolucao.conteudo,
            resolucao.versao_disco,
        )


def reabrir_arquivo_conflito_repo(
    repo: RepoOption,
    versao: str,
    caminho: str,
    *,
    progresso: RelatorProgresso = silencioso,
) -> None:
    with abrir_sessao() as sessao:
        reabrir_arquivo(_deps_do_repo(repo, sessao, progresso), versao, caminho)


def propor_resolucao_repo(
    repo: RepoOption,
    versao: str,
    pedido: PedidoProposta,
    *,
    progresso: RelatorProgresso = silencioso,
) -> list[PropostaDeBloco]:
    with abrir_sessao() as sessao:
        return propor_resolucao(
            _deps_do_repo(repo, sessao, progresso),
            versao,
            pedido.caminho,
            pedido.versao_disco,
            pedido.ordens,
        )


def criar_repo(
    repo: RepoOption, versao: str, *, progresso: RelatorProgresso = silencioso
) -> AtualizarResult:
    with abrir_sessao() as sessao:
        return criar(_deps_do_repo(repo, sessao, progresso), versao)


def consultar_repo(
    repo: RepoOption, versao: str, *, progresso: RelatorProgresso = silencioso
) -> list[ChamadoConsultado]:
    with abrir_sessao() as sessao:
        return consultar(_deps_do_repo(repo, sessao, progresso), versao)


def orfaos_repo(
    repo: RepoOption, versao: str, *, progresso: RelatorProgresso = silencioso
) -> list[OrfaoDaVersao]:
    with abrir_sessao() as sessao:
        return listar_orfaos(_deps_do_repo(repo, sessao, progresso), versao)


# Seis parâmetros: os cinco posicionais são a assinatura do JulgarRunner, que a
# TUI e o daemon chamam, e o sexto é o relator que o `partial` amarra.
def julgar_orfao_repo(  # noqa: PLR0913
    repo: RepoOption,
    versao: str,
    hash_: str,
    chamado: str | None,
    motivo: str,
    *,
    progresso: RelatorProgresso = silencioso,
) -> JulgamentoOrfao:
    with abrir_sessao() as sessao:
        return julgar_orfao(
            _deps_do_repo(repo, sessao, progresso), versao, hash_, chamado, motivo
        )


def avaliar_numero(
    versionamento: Versionamento, existentes: list[str], numero: str
) -> tuple[str, str]:
    """(previa, erro) do que esta digitado. Campo vazio nao e erro ainda."""
    numero = numero.strip()
    if not numero:
        return "", ""
    esquema = versionamento.esquema
    try:
        numero = esquema.validar(numero)
        tipo = esquema.tipo(numero)
    except MotorError as erro:
        return "", str(erro)
    if numero in existentes:
        return "", f"versao {numero} ja existe - use Atualizar"
    try:
        base = esquema.base(numero, existentes, versionamento.principal)
    except MotorError as erro:
        return "", str(erro)
    if tipo is None:
        return f"base {base}", ""
    return f"{tipo} · base {base}", ""


def runners_com_progresso(relatar: RelatorProgresso) -> Runners:
    # O relator entra por `partial`, nao na assinatura dos runners que a TUI
    # chama: assim os aliases (VerifyRunner e companhia) e os doubles dos testes
    # seguem com a mesma aridade, e quem injeta runner nao precisa saber que
    # progresso existe.
    return Runners(
        partial(repos_do_ambiente, progresso=relatar),
        partial(versoes_do_repo, progresso=relatar),
        partial(verificar_repo, progresso=relatar),
        partial(atualizar_repo, progresso=relatar),
        partial(continuar_repo, progresso=relatar),
        partial(abortar_repo, progresso=relatar),
        partial(consultar_repo, progresso=relatar),
        partial(criar_repo, progresso=relatar),
        previa_atualizacao=partial(previa_repo, progresso=relatar),
        ler_conflito=partial(ler_conflito_repo, progresso=relatar),
        ler_arquivo_conflito=partial(ler_arquivo_conflito_repo, progresso=relatar),
        resolver_arquivo_conflito=partial(
            resolver_arquivo_conflito_repo, progresso=relatar
        ),
        reabrir_arquivo_conflito=partial(
            reabrir_arquivo_conflito_repo, progresso=relatar
        ),
        propor_resolucao=partial(propor_resolucao_repo, progresso=relatar),
        listar_orfaos=partial(orfaos_repo, progresso=relatar),
        julgar_orfao=partial(julgar_orfao_repo, progresso=relatar),
    )
