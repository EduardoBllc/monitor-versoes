"""Vigência do carimbo da verificação: quando um resultado pode ser reaproveitado."""

from __future__ import annotations

import datetime
import hashlib

from motor.domain.types import Exclusion, Verificacao
from motor.engine.deps import Deps

VALIDADE_VERIFICACAO = datetime.timedelta(minutes=5)


def impressao_do_julgamento(
    exclusoes: list[Exclusion], sem_entrega: dict[str, str]
) -> str:
    # repr e não tupla: versao_numero None e str não se comparam.
    itens = sorted(repr(x) for x in (*exclusoes, *sem_entrega.items()))
    return hashlib.sha256("\n".join(itens).encode()).hexdigest()


def verificacao_vigente(deps: Deps, versao: str) -> Verificacao | None:
    v = deps.estado.verificacao(deps.repo, versao)
    if v is None or deps.agora() - v.verificado_em > VALIDADE_VERIFICACAO:
        return None
    if v.tip != deps.git.resolve_ref(versao):
        return None
    atual = impressao_do_julgamento(
        deps.estado.exclusoes(deps.repo), deps.estado.sem_entrega(deps.repo)
    )
    return v if v.impressao == atual else None
