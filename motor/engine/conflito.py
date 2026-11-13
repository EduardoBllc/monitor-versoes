"""Caso de uso do editor de conflito de 3 vias sobre o pick pendente da versão."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from motor.domain.commits import extrair_chamado
from motor.domain.conflito import (
    PedidoAoProvedor,
    PropostaDeBloco,
    TipoArquivo,
    blocos,
    marcadores_restantes,
    tipo_do_arquivo,
)
from motor.engine.deps import Deps
from motor.errors import (
    ErroDeEntrada,
    NaoEncontrado,
    RespostaInvalida,
    VersaoDesatualizada,
)


@dataclass(frozen=True)
class ArquivoDoConflito:
    caminho: str
    tipo: TipoArquivo
    resolvido: bool


@dataclass(frozen=True)
class ConflitoAberto:
    commit: str
    mensagem: str
    chamado: str | None
    arquivos: list[ArquivoDoConflito]
    sugestao_disponivel: bool = False


@dataclass(frozen=True)
class ConteudoDoConflito:
    tipo: TipoArquivo
    base: str | None
    ours: str | None
    theirs: str | None
    disco: str | None
    versao_disco: str


def _versao_do_disco(disco: str | None) -> str:
    return "" if disco is None else hashlib.sha256(disco.encode()).hexdigest()


def _abrir(deps: Deps, versao: str) -> tuple[str, dict[str, bool]]:
    deps.git.use_worktree(deps.versionamento().branch(versao))
    commit, pendente = deps.git.pending_cherry_pick()
    if not pendente:
        raise NaoEncontrado(f"nenhum cherry-pick pendente na versão {versao}")
    return commit, deps.git.arquivos_do_pick()


def _do_conflito(arquivos: dict[str, bool], versao: str, caminho: str) -> bool:
    # Só a comparação exata com as chaves: caminho de fora não chega ao disco.
    if caminho not in arquivos:
        raise NaoEncontrado(f"{caminho} não está no conflito da versão {versao}")
    return arquivos[caminho]


def _resolvido(deps: Deps, versao: str, caminho: str) -> bool:
    return _do_conflito(_abrir(deps, versao)[1], versao, caminho)


def _sugestao_disponivel(deps: Deps) -> bool:
    try:
        return deps.sugestao() is not None
    except ErroDeEntrada:
        return False


def _mensagem_e_chamado(deps: Deps, commit: str) -> tuple[str, str | None]:
    mensagem = deps.git.commit_meta(commit).msg
    return mensagem, extrair_chamado(mensagem, deps.referencia())


def ler_conflito(deps: Deps, versao: str) -> ConflitoAberto:
    commit, arquivos = _abrir(deps, versao)
    mensagem, chamado = _mensagem_e_chamado(deps, commit)
    return ConflitoAberto(
        commit=commit,
        mensagem=mensagem,
        chamado=chamado,
        arquivos=[
            ArquivoDoConflito(c, tipo_do_arquivo(deps.git.estagios(c)), resolvido)
            for c, resolvido in arquivos.items()
        ],
        sugestao_disponivel=_sugestao_disponivel(deps),
    )


def ler_arquivo(deps: Deps, versao: str, caminho: str) -> ConteudoDoConflito:
    _resolvido(deps, versao, caminho)
    e = deps.git.estagios(caminho)
    return ConteudoDoConflito(
        tipo=tipo_do_arquivo(e),
        base=e.base,
        ours=e.ours,
        theirs=e.theirs,
        disco=e.disco,
        versao_disco=_versao_do_disco(e.disco),
    )


def resolver_arquivo(
    deps: Deps, versao: str, caminho: str, conteudo: str | None, versao_disco: str
) -> None:
    _resolvido(deps, versao, caminho)
    e = deps.git.estagios(caminho)
    if tipo_do_arquivo(e) == TipoArquivo.OUTRO:
        raise ErroDeEntrada(f"{caminho} não se resolve pela web; use o terminal")
    if _versao_do_disco(e.disco) != versao_disco:
        raise VersaoDesatualizada(f"{caminho} mudou fora da web; recarregue")
    if conteudo is not None and (linhas := marcadores_restantes(conteudo)):
        raise ErroDeEntrada(
            f"{caminho} ainda tem marcador de conflito nas linhas "
            + ", ".join(map(str, linhas))
        )
    deps.git.resolver(caminho, conteudo)


def reabrir_arquivo(deps: Deps, versao: str, caminho: str) -> None:
    # Reabrir um pendente regeraria os marcadores e jogaria fora a edição no disco.
    if not _resolvido(deps, versao, caminho):
        raise ErroDeEntrada(f"{caminho} ainda está pendente; não há o que reabrir")
    deps.git.reabrir(caminho)


def _conferir(
    ordens: list[int], propostas: list[PropostaDeBloco]
) -> list[PropostaDeBloco]:
    if sorted(p.ordem for p in propostas) != sorted(ordens):
        raise RespostaInvalida("o provedor não propôs exatamente os blocos pedidos")
    if any(not p.justificativa.strip() for p in propostas):
        raise RespostaInvalida("o provedor devolveu proposta sem justificativa")
    return sorted(propostas, key=lambda p: p.ordem)


def propor_resolucao(
    deps: Deps, versao: str, caminho: str, versao_disco: str, ordens: list[int]
) -> list[PropostaDeBloco]:
    """Pede ao provedor a proposta dos blocos pedidos; só lê, nunca grava."""
    provedor = deps.sugestao()
    if provedor is None:
        raise ErroDeEntrada("sem [sugestao] provedor no config.toml central")
    commit, arquivos = _abrir(deps, versao)
    if _do_conflito(arquivos, versao, caminho):
        raise ErroDeEntrada(f"{caminho} já está resolvido; não há o que propor")
    e = deps.git.estagios(caminho)
    if tipo_do_arquivo(e) != TipoArquivo.CONTEUDO:
        raise ErroDeEntrada(f"{caminho} não é um conflito de conteúdo")
    if _versao_do_disco(e.disco) != versao_disco:
        raise VersaoDesatualizada(f"{caminho} mudou fora da web; recarregue")
    achados = blocos(e.disco or "")
    if (
        not ordens
        or len(set(ordens)) != len(ordens)
        or any(o not in range(len(achados)) for o in ordens)
    ):
        raise ErroDeEntrada(f"ordens inválidas para os {len(achados)} blocos abertos")
    mensagem, chamado = _mensagem_e_chamado(deps, commit)
    pedido = PedidoAoProvedor(
        caminho, mensagem, chamado, [achados[o] for o in sorted(ordens)]
    )
    return _conferir(ordens, provedor.propor(pedido))
