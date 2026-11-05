"""Execução de uma inscrição: um passo do `atualizar` com desfecho classificado."""

from __future__ import annotations

from motor.domain.inscricao import Desfecho, Resultado, vermelhos_de
from motor.engine.atualizar import AtualizarStatus, atualizar, versao_liberada
from motor.engine.deps import Deps
from motor.errors import MotorError


def executar_inscricao(deps: Deps, versao: str) -> Resultado:
    try:
        return _executar(deps, versao)
    except MotorError as e:
        return Resultado(Desfecho.ERRO, mensagem=str(e))


def _executar(deps: Deps, versao: str) -> Resultado:
    if versao_liberada(deps, versao):
        return Resultado(Desfecho.ENCERRADA)
    deps.git.use_worktree(deps.versionamento().branch(versao))
    _, pendente = deps.git.pending_cherry_pick()
    if pendente:
        return Resultado(Desfecho.PULADA)

    r = atualizar(deps, versao)
    vermelhos = vermelhos_de(r.status_versao) if r.status_versao else None
    if r.status == AtualizarStatus.BLOCKED:
        return Resultado(
            Desfecho.BLOQUEADA,
            vermelhos=vermelhos,
            commit_bloqueado=r.blocked_commit,
            arquivos=tuple(r.arquivos_conflito),
            culpados=tuple(r.culpados),
        )
    if not r.aplicados:
        return Resultado(Desfecho.NADA, vermelhos=vermelhos)
    return Resultado(
        Desfecho.APLICOU,
        vermelhos=vermelhos,
        chamados_aplicados=tuple(dict.fromkeys(c.chamado for c in r.aplicados)),
        n_aplicados=len(r.aplicados),
    )
