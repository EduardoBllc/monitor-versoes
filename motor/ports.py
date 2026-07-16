"""Portas (interfaces) — transcrição 1-pra-1 de internal/ports/ports.go."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol

from motor.domain.types import CommitRef, TargetSet, TaskTarget


class CherryPickOutcome(IntEnum):
    """Estados do cherry-pick."""

    APLICADO = 0
    CONFLITO = 1


@dataclass(frozen=True)
class MergePrediction:
    """Previsão de merge."""

    conflita: bool
    arquivos_conflito: list[str]


class TaskSource(Protocol):
    """Fonte de tarefas (ClickUp, etc)."""

    def fetch(self, versao: str) -> list[TaskTarget]:
        """Busca tarefas para a versão."""
        ...


class CommitSource(Protocol):
    """Fonte de commits de uma task (grep em master, PR do Bitbucket, etc).

    Recebe o lote de tasks (batch) pra permitir uma varredura única — ex.
    grep com --grep de todos os chamados juntos. Chave do TargetSet = chamado.
    Pode omitir tasks sem commit; a completude (task vazia sobrevive ao alvo)
    é garantida pelo TargetResolver.
    """

    def resolve(self, tasks: list[TaskTarget]) -> TargetSet:
        """Acha os commits de cada task."""
        ...


class GitRepo(Protocol):
    """Repositório Git."""

    def merge_base(self, a: str, b: str) -> str:
        """Base comum de dois commits."""
        ...

    def is_ancestor(self, commit: str, branch: str) -> bool:
        """Verifica se commit é ancestral de branch."""
        ...

    def search_commits(self, padroes: list[str], refs: str) -> list[CommitRef]:
        """Busca commits que correspondem a padrões."""
        ...

    def commits_in_range(self, from_: str, to: str) -> list[CommitRef]:
        """Commits no intervalo from_ até to."""
        ...

    def commit_meta(self, hash: str) -> CommitRef:
        """Metadados do commit."""
        ...

    def patch_id(self, hash: str) -> str:
        """ID do patch (para comparação de conteúdo)."""
        ...

    def resolve_ref(self, ref: str) -> str:
        """Resolve uma referência para hash."""
        ...

    def use_worktree(self, branch: str) -> None:
        """Seleciona worktree por branch."""
        ...

    def cherry_pick_x(self, hash: str) -> CherryPickOutcome:
        """Cherry-pick de um commit."""
        ...

    def conflicted_paths(self) -> list[str]:
        """Caminhos em conflito (após cherry-pick)."""
        ...

    def pending_cherry_pick(self) -> tuple[str, bool]:
        """Cherry-pick pendente: (hash, ok)."""
        ...

    def continue_cherry_pick(self) -> None:
        """Continua cherry-pick."""
        ...

    def abort_cherry_pick(self) -> None:
        """Aberta cherry-pick."""
        ...

    def predict_merge(self, parent: str, branch_tip: str, commit: str) -> MergePrediction:
        """Prevê merge."""
        ...

    def worktree_add(self, branch: str, base: str) -> None:
        """Cria worktree."""
        ...

    def worktree_remove(self, branch: str) -> None:
        """Remove worktree."""
        ...

    def tag_exists(self, tag: str) -> bool:
        """Verifica se tag existe."""
        ...

    def remote_branch_exists(self, remote: str, branch: str) -> bool:
        """Verifica se branch remota existe."""
        ...

    def remote_url(self, remote: str) -> str:
        """URL do remoto (ex: git@bitbucket.org:ws/repo.git)."""
        ...

    def push_branch(self, remote: str, branch: str) -> None:
        """Publica branch no remoto (-u)."""
        ...

    def pull_branch(self, remote: str, branch: str) -> None:
        """Atualiza a branch local com o remoto (fast-forward only)."""
        ...

    def list_version_branches(self) -> list[str]:
        """Lista branches de versão."""
        ...

    def read_file(self, branch: str, path: str) -> bytes:
        """Lê arquivo em branch."""
        ...

    def write_file(
        self, branch: str, path: str, content: bytes, mensagem_commit: str
    ) -> None:
        """Escreve arquivo em branch."""
        ...
