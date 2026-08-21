"""Porte de internal/domain/commits.go."""

from __future__ import annotations

import re

from motor.domain.types import CommitRef

padrao_chamado = re.compile(r"\bch(\d+)\b")


def match_exato(candidatos: list[CommitRef], chamado: str) -> list[CommitRef]:
    """Filtra candidatos de grep por word-boundary: `ch5514` nao pode casar
    dentro de `ch255514`. search_commits do GitRepo so traz candidatos brutos.
    """
    if not chamado:
        return []
    padrao = re.compile(r"\bch" + re.escape(chamado) + r"\b")
    return [c for c in candidatos if padrao.search(c.msg)]


def extrair_chamado(msg: str) -> str | None:
    """Acha o numero do chamado na mensagem. Usado na reconstrucao do estado,
    para reagrupar por chamado a partir do trailer de cherry-pick.
    """
    m = padrao_chamado.search(msg)
    return None if m is None else m.group(1)


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


def ordenar_por_data(commits: list[CommitRef]) -> list[CommitRef]:
    """Ordena por commit_date asc - nao depende de flag do git (§5
    "Ordenacao"). Nao muta a lista de entrada.
    """
    return sorted(commits, key=lambda c: c.commit_date)
