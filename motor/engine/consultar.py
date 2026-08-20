"""Consulta o snapshot persistido de uma versão sem recalculá-lo."""

from __future__ import annotations

from dataclasses import dataclass, replace

from motor.domain.types import CommitRef
from motor.engine.deps import Deps
from motor.errors import MotorError


@dataclass(frozen=True)
class ChamadoConsultado:
    chamado: str
    estado: str
    commits: list[CommitRef]


def consultar(deps: Deps, versao: str) -> list[ChamadoConsultado]:
    resultado: list[ChamadoConsultado] = []
    for atribuicao in deps.estado.atribuicoes(deps.repo, versao):
        commits: list[CommitRef] = []
        for hash_origem in atribuicao.commits:
            try:
                commit = deps.git.commit_meta(hash_origem)
            except MotorError:
                commit = CommitRef(
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
    return resultado
