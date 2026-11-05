"""Porte de internal/domain/commits.go."""

from __future__ import annotations

from motor.domain.referencia import Referencia, regex_de_extracao, regex_do_chamado
from motor.domain.types import CommitRef


def match_exato(
    candidatos: list[CommitRef], chamado: str, ref: Referencia
) -> list[CommitRef]:
    """Filtra candidatos de grep pela fronteira da referencia: com `ch{id}`,
    `ch5514` nao pode casar dentro de `ch255514`. search_commits do GitRepo so
    traz candidatos brutos.

    Sem olhar caixa, em par com o `-i` do `search_commits`: quem traz o
    candidato "CH5514" nao pode perde-lo aqui.
    """
    if not chamado:
        return []
    padrao = regex_do_chamado(ref, chamado)
    return [c for c in candidatos if padrao.search(c.msg)]


def extrair_chamado(msg: str, ref: Referencia) -> str | None:
    """Acha o ID da tarefa na mensagem. Usado na reconstrucao do estado,
    para reagrupar por chamado a partir do trailer de cherry-pick.
    """
    m = regex_de_extracao(ref).search(msg)
    return None if m is None else m.group("id")


def agrupar_por_chamado(commits: list[CommitRef]) -> dict[str, list[CommitRef]]:
    """Agrupa preservando a ordem de 1a aparicao de cada chamado.

    Commit sem chamado (orfao) cai numa chave propria pelo hash curto, em vez de
    todos se juntarem numa cesta `""`: o CLI e a TUI listam essas chaves como
    titulo, e uma cesta unica esconderia quantos orfaos distintos existem.
    """
    grupos: dict[str, list[CommitRef]] = {}
    for c in commits:
        grupos.setdefault(c.chamado or c.hash_origem[:8], []).append(c)
    return grupos


def ordenar_por_grafo(commits: list[CommitRef], ordem: list[str]) -> list[CommitRef]:
    """Ordem de aplicacao do lote: a posicao em `ordem` (topologica, do git).
    Quem o git nao conhece vai para o fim, na ordem de entrada. Data nenhuma
    entra: o rebase preserva a do autor, e o commit rebasado em cima de outro
    pode ter sido escrito antes dele (ch257911). Nao muta a entrada.
    """
    posicao = {h: i for i, h in enumerate(ordem)}
    return sorted(commits, key=lambda c: posicao.get(c.hash_origem, len(ordem)))
