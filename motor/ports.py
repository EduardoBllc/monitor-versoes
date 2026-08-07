"""Portas (interfaces) — transcrição 1-pra-1 de internal/ports/ports.go."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol

from motor.domain.types import CommitRef


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
    """Fonte de tarefas (Tickio, lista manual)."""

    def fetch(self, versao: str) -> list[str]:
        """Numeros de chamado marcados para a versao."""
        ...


class CommitSource(Protocol):
    """Fonte de commits de uma tarefa (grep em master, PR do Bitbucket).

    Recebe o lote inteiro para permitir uma varredura unica — grep com o
    --grep de todos os chamados juntos. Pode omitir chamado sem commit; a
    completude e garantida pelo TargetResolver.
    """

    def resolve(self, chamados: list[str]) -> dict[str, list[CommitRef]]:
        """Acha os commits de cada chamado."""
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

    def changed_files(self, hash: str) -> frozenset[str]:
        """Caminhos alterados pelo commit (para o nível 4 do oráculo de presença)."""
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

    def fetch(self, remote: str) -> None:
        """Atualiza as referencias remote-tracking (ex: origin/master), sem
        tocar em branch local nenhuma."""
        ...

    def list_version_branches(self) -> list[str]:
        """Lista branches de versão."""
        ...

    def list_version_tags(self) -> list[str]:
        """Tags no formato X.Y.Z. Versao com tag = liberada (§6)."""
        ...

    def read_file(self, branch: str, path: str) -> bytes:
        """Lê arquivo em branch."""
        ...

    def write_file(
        self, branch: str, path: str, content: bytes, mensagem_commit: str
    ) -> None:
        """Escreve arquivo em branch."""
        ...
