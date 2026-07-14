"""Porte de internal/domain/commits.go."""

from __future__ import annotations

import re

from motor.domain.types import CommitRef

padrao_chamado = re.compile(r"\bch(\d+)\b")
padrao_vb = re.compile(r"\b(VB-\d+)\b")


def match_exato(candidatos: list[CommitRef], chamado: str, vb_id: str) -> list[CommitRef]:
    """Filtra candidatos de grep por word-boundary - ch<num> e VB-<num>
    exatos, nao substring (§4 "Precisao do match"). search_commits do GitRepo so
    traz candidatos brutos.
    """
    padroes = []
    if chamado:
        padroes.append(re.compile(r"\bch" + re.escape(chamado) + r"\b"))
    if vb_id:
        padroes.append(re.compile(r"\b" + re.escape(vb_id) + r"\b"))

    resultado = []
    for c in candidatos:
        for p in padroes:
            if p.search(c.msg):
                resultado.append(c)
                break
    return resultado


def extrair_chamado(msg: str) -> str | None:
    """Acha um numero de chamado (ch<num>) na mensagem, usado na
    reconstrucao do lock (§3) para reagrupar por chamado a partir do trailer.
    """
    m = padrao_chamado.search(msg)
    if m is None:
        return None
    return m.group(1)


def extrair_vb_id(msg: str) -> str | None:
    """Acha um id VB-<num> na mensagem."""
    m = padrao_vb.search(msg)
    if m is None:
        return None
    return m.group(1)


def ordenar_por_data(commits: list[CommitRef]) -> list[CommitRef]:
    """Ordena por commit_date asc - nao depende de flag do git (§5
    "Ordenacao"). Nao muta a lista de entrada.
    """
    return sorted(commits, key=lambda c: c.commit_date)
