"""Tipos do domínio (§ver internal/domain/types.go). Só dados, sem comportamento."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import IntEnum


class VersionType(IntEnum):
    FECHADA = 0  # X.0.0
    AJUSTADA = 1  # X.Y.0
    CLIENTE = 2  # X.Y.Z


class Presence(IntEnum):
    AUSENTE = 0
    ANCESTRAL = 1
    TRAILER = 2
    PATCH_ID = 3


@dataclass(frozen=True)
class BaseRef:
    ref: str = ""  # "13.6.0"
    commit: str = ""  # hash


@dataclass(frozen=True)
class Version:
    numero: str = ""  # "13.7.0"
    tipo: VersionType = VersionType.FECHADA
    base: BaseRef = field(default_factory=BaseRef)


@dataclass(frozen=True)
class CommitRef:
    hash_origem: str = ""
    parent: str = ""  # pai do commit na branch de origem (necessario pra PredictMerge)
    chamado: str = ""  # "255514"
    task: str = ""  # "VB-2354"
    titulo: str = ""
    commit_date: datetime.datetime = field(default_factory=lambda: datetime.datetime.min)
    msg: str = ""


@dataclass(frozen=True)
class TaskTarget:
    chamado: str = ""  # numero do chamado — chave externa
    task: str = ""  # "VB-xxxx"
    titulo: str = ""
    commits: list[CommitRef] = field(default_factory=list)


# TargetSet = task->commits resolvido (§4). Chave = chamado.
TargetSet = dict[str, TaskTarget]


class ExclusionReason(IntEnum):
    AUTOMATICA = 0  # recomputavel via Presente()
    JULGAMENTO = 1  # irredutivel, so existe no lock


@dataclass(frozen=True)
class Exclusion:
    commit: str = ""
    chamado: str = ""
    motivo: str = ""
    reason: ExclusionReason = ExclusionReason.AUTOMATICA


@dataclass(frozen=True)
class Lock:
    versao: str = ""
    tipo: VersionType = VersionType.FECHADA
    base: BaseRef = field(default_factory=BaseRef)
    tasks: TargetSet = field(default_factory=dict)
    excluidos: list[Exclusion] = field(default_factory=list)
    # chamados reconhecidos como sem commit/PR neste projeto (julgamento
    # manual, so vive no lock) - impede que a task caia em tasks_sem_commits.
    tasks_sem_entrega: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VersionStatus:
    verde: bool = False
    tasks_novas: list[str] = field(default_factory=list)  # em ClickUp, fora do lock
    tasks_removidas: list[str] = field(default_factory=list)  # no lock, fora do ClickUp
    lock_integro: bool = False
    commits_sumidos: list[str] = field(default_factory=list)  # no lock, ausentes no git
    faltantes: list[CommitRef] = field(default_factory=list)
    ancestrais: list[CommitRef] = field(default_factory=list)  # presente no historico mas fora do lock (ancestral, trailer ou patch-id)
    conflitantes: list[CommitRef] = field(default_factory=list)  # subconjunto de Faltantes que da conflito (merge-tree)
    tasks_sem_commits: list[str] = field(default_factory=list)  # task no ClickUp sem nenhum commit achado e nao reconhecida em tasks_sem_entrega
