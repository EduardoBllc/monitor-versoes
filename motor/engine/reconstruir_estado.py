"""Regenera as atribuicoes a partir do git quando o estado e perdido.

Operacao de recuperacao, fora do fluxo principal. Nunca interativa:
PENDING_JUDGMENT e valor de retorno, quem pergunta ao humano e o front-end.
Nao recupera exclusoes nem sem_entrega — julgamento humano so vive no banco.

Numa versao ja congelada (liberada_em preenchida) a trigger recusa a escrita.
Recuperar o snapshot de uma versao liberada exige apagar a linha primeiro:
  delete from versao where repo_id = ... and numero = '13.34.0';
Depois rode reconstruir-estado e so entao verificar, que reobserva a tag e
congela de novo. A ordem importa: verificar antes congelaria o estado vazio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from motor.domain.types import VersaoInfo
from motor.domain.version import inferir_tipo
from motor.engine.deps import Deps
from motor.services.base_resolver import BaseResolver
from motor.services.reconstrutor import reconstruir_atribuicoes


class ReconstructStatus(IntEnum):
    DONE = 0
    PENDING_JUDGMENT = 1


@dataclass
class ReconstructResult:
    status: ReconstructStatus
    orfaos: list[str] = field(default_factory=list)


def reconstruir_estado(deps: Deps, versao: str) -> ReconstructResult:
    # Antes de ler qualquer ref, nao depois: a base de uma versao nunca
    # registrada sai do ref store local (list_version_branches, tag_exists em
    # BaseResolver) e o commits_in_range abaixo le o tip local da branch alvo.
    # Sem buscar primeiro, uma base recem-cortada em outra maquina nao
    # apareceria - e como registrar_versao so grava na primeira chamada, a
    # base errada ficaria definitiva - ou a varredura ignoraria cherry-picks
    # ja empurrados para a branch por outra maquina.
    deps.git.fetch("origin")

    info = deps.estado.versao(deps.repo, versao)
    if info is None:
        resolvida = BaseResolver(git=deps.git).resolve(versao)
        deps.estado.registrar_versao(
            deps.repo,
            VersaoInfo(
                numero=versao,
                tipo=inferir_tipo(versao),
                base_ref=resolvida.ref,
                base_commit=resolvida.commit,
            ),
        )
        base_commit = resolvida.commit
    else:
        # Mesma regra do verificar: a base gravada manda.
        base_commit = info.base_commit

    atribuicoes, orfaos = reconstruir_atribuicoes(deps.git, base_commit, versao)
    deps.estado.substituir_atribuicoes(deps.repo, versao, atribuicoes)

    if orfaos:
        return ReconstructResult(status=ReconstructStatus.PENDING_JUDGMENT, orfaos=orfaos)
    return ReconstructResult(status=ReconstructStatus.DONE)
