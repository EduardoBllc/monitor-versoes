"""Portas (interfaces) — transcrição 1-pra-1 de internal/ports/ports.go."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol

from motor.domain.types import Atribuicao, CommitRef, Exclusion, RepoInfo, VersaoInfo


class CherryPickOutcome(IntEnum):
    """Estados do cherry-pick."""

    APLICADO = 0
    CONFLITO = 1


@dataclass(frozen=True)
class MergePrediction:
    """Previsão de merge; se limpa, traz a árvore que alimenta o próximo."""

    conflita: bool
    arquivos_conflito: list[str]
    arvore_resultante: str = ""


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

    def commits_meta(self, hashes: list[str]) -> dict[str, CommitRef]:
        """Metadados de vários commits numa varredura só.

        Nao existe no ports.go: o Go le meta commit por commit, e num snapshot
        de versao inteira isso e um processo git por commit (dois, com o parent).
        Recebe o lote pelo mesmo motivo que o CommitSource recebe: deixar o
        adapter varrer uma vez.

        Hash desconhecido simplesmente falta no retorno — quem chama decide o
        fallback. Contrato igual ao de `commit_meta` no resto: mesmos campos,
        mesma data (a do committer), `parent` = primeiro pai.
        """
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

    def culpados_por_linha(
        self, base: str, parent: str, commit: str, arquivos: list[str]
    ) -> dict[str, list[CommitRef]]:
        """Commits em base..parent que tocaram as mesmas linhas que `commit`
        altera nos `arquivos`. Atribui o conflito a quem o causou.
        """
        ...

    def worktree_add(self, branch: str, base: str) -> None:
        """Cria worktree."""
        ...

    def worktree_gc(self, manter: int, atual: str) -> list[str]:
        """Descarta worktrees de versao alem das `manter` de uso mais recente.

        `atual` sobrevive sempre que `manter >= 1`. Com `manter == 0` remove
        todas, inclusive a `atual`. Devolve as removidas. Nunca leva trabalho
        embora: worktree com alteracao nao commitada ou cherry-pick pendente e
        pulada.
        """
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


class EstadoRepo(Protocol):
    """Estado persistente. Projecao materializada para versao em construcao;
    registro unico e imutavel para versao liberada.
    """

    def registrar_repo(self, nome: str, tickio_sistema_id: int) -> None:
        """Cadastra um repo canonico. MotorError se nome ou alias ja existir."""
        ...

    def resolver_repo(self, basename: str) -> RepoInfo:
        """Resolve nome ou alias para o repo canonico. MotorError se
        desconhecido — nunca cria linha sozinho, senao um clone com nome
        diferente fragmenta o estado."""
        ...

    def listar_repos(self) -> list[RepoInfo]:
        """Repos canonicos cadastrados, em ordem de nome; aliases nao entram."""
        ...

    def registrar_versao(self, repo: str, info: VersaoInfo) -> None:
        """Upsert da versao operada. Nao toca `liberada_em`."""
        ...

    def marcar_liberadas(
        self, repo: str, liberadas: dict[str, datetime.datetime]
    ) -> None:
        """Grava a data de liberacao das versoes que ganharam tag. Ignora
        versao ausente do estado e nao reescreve data ja gravada."""
        ...

    def versao(self, repo: str, numero: str) -> VersaoInfo | None:
        """A versao como esta no estado. A `base` daqui e a autoritativa —
        recomputar BaseResolver a cada run faria a base de uma X.0.0 seguir o
        tip atual do master em vez do ponto onde a branch foi cortada."""
        ...

    def atribuicoes(self, repo: str, versao: str) -> list[Atribuicao]: ...

    def substituir_atribuicoes(
        self, repo: str, versao: str, novas: list[Atribuicao]
    ) -> None:
        """Apaga e reinsere. MotorError se a versao ja estiver liberada."""
        ...

    def exclusoes(self, repo: str) -> list[Exclusion]: ...

    def sem_entrega(self, repo: str) -> dict[str, str]:
        """chamado -> motivo."""
        ...

    def commits_de_pr(self, repo: str, pr_ids: list[int]) -> dict[int, list[CommitRef]]:
        """Commits em cache das PRs pedidas, ordenados por data.

        PR ausente do dict = nunca consultada, e a fonte tem que ir na API.
        Lista vazia significaria "PR sem commit nenhum", e a diferenca importa:
        confundir as duas faria a PR nova nunca mais ser buscada.
        """
        ...

    def gravar_commits_de_pr(
        self, repo: str, commits: dict[int, list[CommitRef]]
    ) -> None:
        """Guarda os commits de PRs MERGED. Upsert por (repo, pr_id, hash).

        So fato imutavel entra: PR mergeada nao ganha nem perde commit. O
        `chamado` fica de fora porque vem da busca, nao da PR — duas tarefas
        podem apontar para a mesma PR.
        """
        ...
