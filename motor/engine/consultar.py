"""Consulta o snapshot persistido de uma versão sem recalculá-lo."""

from __future__ import annotations

from dataclasses import dataclass, replace

from motor.domain.commits import ordenar_por_grafo
from motor.domain.types import CommitRef
from motor.engine.deps import Deps
from motor.progresso import Progresso


@dataclass(frozen=True)
class ChamadoConsultado:
    chamado: str
    estado: str
    commits: list[CommitRef]


def consultar(deps: Deps, versao: str) -> list[ChamadoConsultado]:
    atribuicoes = deps.estado.atribuicoes(deps.repo, versao)
    # Uma varredura para a versao inteira, nao uma por commit: era processo git
    # por commit (dois, com o parent), e o snapshot de uma versao passa de cem.
    # Fase sem contagem porque o custo esta todo aqui dentro, num comando so.
    deps.progresso(Progresso("lendo commits do snapshot"))
    hashes = [h for atribuicao in atribuicoes for h in atribuicao.commits]
    metas = deps.git.commits_meta(hashes)
    # Commits do chamado na ordem do lote (ancestral primeiro), nao na
    # alfabetica em que o estado os guarda.
    ordem = deps.git.ordem_topologica(hashes)
    resultado: list[ChamadoConsultado] = []
    for atribuicao in atribuicoes:
        commits: list[CommitRef] = []
        for hash_origem in atribuicao.commits:
            commit = metas.get(hash_origem) or CommitRef(
                hash_origem=hash_origem,
                msg="mensagem indisponível",
            )
            commits.append(replace(commit, chamado=atribuicao.chamado))
        resultado.append(
            ChamadoConsultado(
                chamado=atribuicao.chamado,
                estado=atribuicao.estado,
                commits=ordenar_por_grafo(commits, ordem),
            )
        )
    # Mais recente primeiro: o chamado cujo commit de ORIGEM esta mais adiante
    # no grafo. Data nao decide (o rebase preserva a do autor, ch257911).
    #
    # Chamado sem commit que o git conheca (meta indisponivel, ou lista vazia)
    # fica com -1 e vai para o fim.
    posicao = {h: i for i, h in enumerate(ordem)}
    resultado.sort(
        key=lambda ch: max(
            (posicao.get(c.hash_origem, -1) for c in ch.commits), default=-1
        ),
        reverse=True,
    )
    return resultado
