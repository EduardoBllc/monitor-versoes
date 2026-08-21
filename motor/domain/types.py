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
    parent: str = ""  # pai do commit na origem (necessario pro predict_merge)
    chamado: str = ""  # "255514"
    commit_date: datetime.datetime = field(default_factory=lambda: datetime.datetime.min)
    msg: str = ""


@dataclass(frozen=True)
class TaskTarget:
    chamado: str = ""  # numero do chamado — identidade unica da tarefa
    marcada: str = ""  # versao para a qual o Tickio marcou
    commits: list[CommitRef] = field(default_factory=list)


# TargetSet = chamado -> TaskTarget resolvido.
TargetSet = dict[str, TaskTarget]


@dataclass(frozen=True)
class Alvo:
    """Resultado da resolucao de alvo: as tarefas mais o que deu errado nelas."""

    tasks: TargetSet = field(default_factory=dict)
    # chamado marcado em mais de uma versao — dado inconsistente no Tickio.
    ambiguas: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Exclusion:
    """Julgamento humano: commit que nao entra. Estado irredutivel — nao e
    re-derivavel do Tickio nem do git.

    As exclusoes automaticas ("ja presente na base") sumiram: eram
    recomputaveis por definicao e quem responde isso e o oraculo de presenca.
    """

    hash_origem: str = ""
    versao_numero: str | None = None  # None = vale para toda versao do repo
    motivo: str = ""


@dataclass(frozen=True)
class Atribuicao:
    chamado: str = ""
    marcada: str = ""  # versao para a qual o Tickio marcou
    estado: str = "pendente"  # pendente | aplicado
    commits: list[str] = field(default_factory=list)  # hashes de origem


@dataclass(frozen=True)
class VersaoInfo:
    numero: str = ""
    tipo: VersionType = VersionType.FECHADA
    base_ref: str = ""
    base_commit: str = ""
    liberada_em: datetime.datetime | None = None


@dataclass(frozen=True)
class RepoInfo:
    nome: str = ""  # canonico, nunca o alias
    tickio_sistema_id: int = 0


@dataclass(frozen=True)
class VersionStatus:
    verde: bool = False
    tasks_novas: list[str] = field(default_factory=list)  # no Tickio, fora do estado
    tasks_removidas: list[str] = field(default_factory=list)  # no estado, fora do Tickio
    estado_integro: bool = False
    tasks_ambiguas: list[str] = field(default_factory=list)  # chamado marcado em mais de uma versao aberta
    commits_sumidos: list[str] = field(default_factory=list)  # no estado, ausentes no git
    faltantes: list[CommitRef] = field(default_factory=list)
    ancestrais: list[CommitRef] = field(default_factory=list)  # presente no historico, sem cherry-pick a fazer (ancestral, trailer ou patch-id)
    conflitantes: list[CommitRef] = field(default_factory=list)  # subconjunto de Faltantes que da conflito (merge-tree)
    suspeitos_conteudo: list[CommitRef] = field(default_factory=list)  # subconjunto de Faltantes com match de mensagem+arquivos no alvo (provavel cherry-pick manual com conteudo divergente) - so alerta, nao conta como presente
    # hash_origem conflitante -> chamados que tocaram as mesmas linhas antes
    # dele e nao estao nesta versao. E a resposta para "de que alteracao esse
    # cherry-pick depende": sem ela o operador sabe que conflita, nao por que.
    conflito_causado_por: dict[str, list[str]] = field(default_factory=dict)
    tasks_sem_commits: list[str] = field(default_factory=list)  # tarefa no Tickio sem nenhum commit achado e nao reconhecida em sem_entrega
    # Preenchidos so no snapshot de versao liberada (spec §4): sem eles a saida
    # e byte-a-byte igual a de uma versao verde em construcao — nada de data,
    # nada de chamados — e um snapshot vazio imprime "verde: True" porque
    # all([]) e True. O operador nao conseguia distinguir "fez o trabalho" de
    # "recusou-se a recalcular".
    liberada_em: datetime.datetime | None = None
    chamados: list[str] = field(default_factory=list)  # chamados do snapshot congelado
