"""Consulta o snapshot persistido de uma versão sem recalculá-lo."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, replace

from motor.domain.types import SEM_DATA, CommitRef
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
    metas = deps.git.commits_meta(
        [h for atribuicao in atribuicoes for h in atribuicao.commits]
    )
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
                commits=commits,
            )
        )
    # Mais recente primeiro, pela data do commit de ORIGEM mais novo do chamado.
    # Nao e a data do cherry-pick: o estado guarda so hash_origem, o commit
    # espelho na branch da versao nao esta em lugar nenhum. Ordem pratica e
    # quase a mesma e nao custa varredura de git.
    #
    # Chamado sem commit legivel (meta indisponivel, ou lista vazia) cai em
    # SEM_DATA e vai para o fim.
    resultado.sort(key=_mais_recente, reverse=True)
    return resultado


def _mais_recente(chamado: ChamadoConsultado) -> datetime.datetime:
    return max(
        (c.commit_date for c in chamado.commits), default=SEM_DATA
    )
