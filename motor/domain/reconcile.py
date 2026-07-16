"""Porte de internal/domain/reconcile.go."""

from __future__ import annotations

from dataclasses import replace

from motor.domain.types import CommitRef, Exclusion, Lock, TargetSet, VersionStatus, Presence


def filtrar_excluidos(alvo: TargetSet, excluidos: list[Exclusion]) -> TargetSet:
    """Remove do alvo os commits ja marcados como excluidos no
    lock (§3) - sem isso, todo verificar reportaria o mesmo falso-positivo pra
    sempre.
    """
    excluido = {e.commit for e in excluidos}
    filtrado: TargetSet = {}
    for chamado, tt in alvo.items():
        commits = [c for c in tt.commits if c.hash_origem not in excluido]
        filtrado[chamado] = replace(tt, commits=commits)
    return filtrado


def diff_tasks(alvo: TargetSet, lock_tasks: TargetSet) -> tuple[list[str], list[str]]:
    """Calcula a diferenca simetrica entre alvo e lock (§5, §9)."""
    novas = [
        chamado for chamado, tt in alvo.items() if chamado not in lock_tasks and tt.commits
    ]
    removidas = [chamado for chamado in lock_tasks if chamado not in alvo]
    return sorted(novas), sorted(removidas)


def reconciliar(
    alvo: TargetSet,
    lock: Lock,
    presentes: dict[str, Presence],
    conflitantes: list[CommitRef],
) -> VersionStatus:
    """Cruza as 3 fontes (§2, §9) e produz o VersionStatus. `presentes`
    e `conflitantes` sao pre-computados pelo chamador (services.PresenceOracle e
    GitRepo.PredictMerge) - esta funcao fica pura.
    """
    novas, removidas = diff_tasks(alvo, lock.tasks)

    faltantes: list[CommitRef] = []
    ancestrais: list[CommitRef] = []
    for tt in alvo.values():
        for c in tt.commits:
            p = presentes.get(c.hash_origem, Presence.AUSENTE)
            if p == Presence.AUSENTE:
                faltantes.append(c)
            else:
                # ANCESTRAL, TRAILER ou PATCH_ID - ja presente no historico,
                # sem cherry-pick a fazer (§2/§9 "pick manual sem o tool").
                ancestrais.append(c)

    lock_integro = True
    sumidos: list[str] = []
    for tt in lock.tasks.values():
        for c in tt.commits:
            if presentes.get(c.hash_origem, Presence.AUSENTE) == Presence.AUSENTE:
                lock_integro = False
                sumidos.append(c.hash_origem)
    sumidos = sorted(sumidos)

    # Task no ClickUp sem nenhum commit achado: nao pode passar despercebida
    # (falso-verde). So sai da lista se reconhecida manualmente em
    # tasks_sem_entrega (task sem entrega neste projeto, julgamento do operador).
    reconhecidas = set(lock.tasks_sem_entrega)
    sem_commits = sorted(
        chamado
        for chamado, tt in alvo.items()
        if not tt.commits and chamado not in reconhecidas
    )

    verde = (
        len(novas) == 0
        and len(removidas) == 0
        and lock_integro
        and len(faltantes) == 0
        and len(sem_commits) == 0
    )

    return VersionStatus(
        verde=verde,
        tasks_novas=novas,
        tasks_removidas=removidas,
        lock_integro=lock_integro,
        commits_sumidos=sumidos,
        faltantes=faltantes,
        ancestrais=ancestrais,
        conflitantes=conflitantes,
        tasks_sem_commits=sem_commits,
    )
