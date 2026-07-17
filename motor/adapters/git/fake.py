"""Double em memória de GitRepo, para testes de services/engine.

Transcrição 1-pra-1 de internal/adapters/git/fake.go. Não simula merge de
verdade: conflitos e previsão de merge são configurados explicitamente via
os atributos públicos abaixo.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from motor.domain.types import CommitRef
from motor.errors import MotorError
from motor.ports import CherryPickOutcome, MergePrediction


@dataclass
class FakeCommit:
    hash: str
    parent: str
    msg: str
    date: datetime.datetime
    origem_hash: str = ""  # preenchido quando este commit foi criado via cherry_pick_x


@dataclass
class FakeGit:
    commits: dict[str, FakeCommit] = field(default_factory=dict)
    branches: dict[str, str] = field(default_factory=dict)
    tags: dict[str, bool] = field(default_factory=dict)
    remotes: dict[str, bool] = field(default_factory=dict)
    remote_urls: dict[str, str] = field(default_factory=dict)
    files: dict[str, dict[str, bytes]] = field(default_factory=dict)

    conflict_on: dict[str, bool] = field(default_factory=dict)
    file_changes: dict[str, frozenset[str]] = field(default_factory=dict)  # fixture: arquivos alterados por commit (nivel 4)
    merge_predictions: dict[str, MergePrediction] = field(default_factory=dict)
    commits_in_range_err: Exception | None = None  # fixture: forca commits_in_range a falhar (§2 fallback "ausente")
    pulled: list[str] = field(default_factory=list)  # espiao de teste: branches que sofreram pull_branch
    fetched: list[str] = field(default_factory=list)  # espiao de teste: remotos que sofreram fetch
    removed_worktrees: list[str] = field(default_factory=list)  # espiao de teste: branches com worktree removida

    _current_branch: str = ""
    _pending_pick: str = ""
    _conflicted: list[str] = field(default_factory=list)

    def add_commit(self, hash: str, parent: str, msg: str, date: datetime.datetime) -> None:
        """Registra um commit direto no grafo (fixture de teste)."""
        self.commits[hash] = FakeCommit(hash=hash, parent=parent, msg=msg, date=date)

    def set_branch(self, branch: str, hash: str) -> None:
        """Posiciona o tip de uma branch e a torna a branch ativa (fixture de teste)."""
        self.branches[branch] = hash
        self._current_branch = branch

    def merge_base(self, a: str, b: str) -> str:
        ancestors_of_a: dict[str, bool] = {}
        h = self._resolve_ref_local(a)
        while h != "":
            ancestors_of_a[h] = True
            c = self.commits.get(h)
            if c is None:
                break
            h = c.parent

        h = self._resolve_ref_local(b)
        while h != "":
            if ancestors_of_a.get(h):
                return h
            c = self.commits.get(h)
            if c is None:
                break
            h = c.parent
        raise MotorError(f"merge-base nao encontrado entre {a} e {b}")

    def _resolve_ref_local(self, ref: str) -> str:
        return self.branches.get(ref, ref)

    def is_ancestor(self, commit: str, branch: str) -> bool:
        h = self._resolve_ref_local(branch)
        while h != "":
            if h == commit:
                return True
            c = self.commits.get(h)
            if c is None:
                break
            h = c.parent
        return False

    def search_commits(self, padroes: list[str], refs: str) -> list[CommitRef]:
        h = self._resolve_ref_local(refs)
        resultado: list[CommitRef] = []
        while h != "":
            c = self.commits.get(h)
            if c is None:
                break
            for p in padroes:
                if p != "" and p in c.msg:
                    resultado.append(
                        CommitRef(hash_origem=c.hash, parent=c.parent, msg=c.msg, commit_date=c.date)
                    )
                    break
            h = c.parent
        return resultado

    def commits_in_range(self, from_: str, to: str) -> list[CommitRef]:
        if self.commits_in_range_err is not None:
            raise self.commits_in_range_err
        stop_at = self._resolve_ref_local(from_)
        h = self._resolve_ref_local(to)
        resultado: list[CommitRef] = []
        while h != "" and h != stop_at:
            c = self.commits.get(h)
            if c is None:
                break
            resultado.append(CommitRef(hash_origem=c.hash, parent=c.parent, msg=c.msg, commit_date=c.date))
            h = c.parent
        return resultado

    def commit_meta(self, hash: str) -> CommitRef:
        c = self.commits.get(hash)
        if c is None:
            raise MotorError(f"commit {hash} nao encontrado")
        return CommitRef(hash_origem=c.hash, parent=c.parent, msg=c.msg, commit_date=c.date)

    def patch_id(self, hash: str) -> str:
        if hash not in self.commits:
            raise MotorError(f"commit {hash} nao encontrado")
        return "patchid-" + hash

    def changed_files(self, hash: str) -> frozenset[str]:
        if hash not in self.commits:
            raise MotorError(f"commit {hash} nao encontrado")
        return self.file_changes.get(hash, frozenset())

    def resolve_ref(self, ref: str) -> str:
        if ref in self.branches:
            return self.branches[ref]
        if ref in self.commits:
            return ref
        raise MotorError(f"ref {ref} nao encontrada")

    def use_worktree(self, branch: str) -> None:
        if branch not in self.branches:
            raise MotorError(f"branch {branch} nao existe")
        self._current_branch = branch

    def cherry_pick_x(self, hash: str) -> CherryPickOutcome:
        origem = self.commits.get(hash)
        if origem is None:
            raise MotorError(f"commit {hash} nao encontrado")
        if self.conflict_on.get(hash):
            self._pending_pick = hash
            self._conflicted = ["arquivo-conflito.txt"]
            return CherryPickOutcome.CONFLITO
        self._aplicar_pick(origem)
        return CherryPickOutcome.APLICADO

    def _aplicar_pick(self, origem: FakeCommit) -> None:
        novo_hash = "pick-" + origem.hash
        tip = self.branches[self._current_branch]
        self.commits[novo_hash] = FakeCommit(
            hash=novo_hash,
            parent=tip,
            msg=origem.msg + f"\n\n(cherry picked from commit {origem.hash})",
            date=origem.date,
            origem_hash=origem.hash,
        )
        self.branches[self._current_branch] = novo_hash

    def conflicted_paths(self) -> list[str]:
        return self._conflicted

    def pending_cherry_pick(self) -> tuple[str, bool]:
        if self._pending_pick == "":
            return "", False
        return self._pending_pick, True

    def continue_cherry_pick(self) -> None:
        if self._pending_pick == "":
            raise MotorError("nenhum cherry-pick pendente")
        origem = self.commits[self._pending_pick]
        self._aplicar_pick(origem)
        self._pending_pick = ""
        self._conflicted = []

    def abort_cherry_pick(self) -> None:
        self._pending_pick = ""
        self._conflicted = []

    def predict_merge(self, parent: str, branch_tip: str, commit: str) -> MergePrediction:
        return self.merge_predictions.get(commit, MergePrediction(conflita=False, arquivos_conflito=[]))

    def worktree_add(self, branch: str, base: str) -> None:
        if branch in self.branches:
            raise MotorError(f"branch {branch} ja existe")
        self.branches[branch] = self._resolve_ref_local(base)
        self._current_branch = branch

    def worktree_remove(self, branch: str) -> None:
        # so desanexa a worktree (como o git de verdade) - a branch em si
        # continua existindo, pra use_worktree poder recria-la sob demanda.
        self.removed_worktrees.append(branch)

    def tag_exists(self, tag: str) -> bool:
        return self.tags.get(tag, False)

    def remote_branch_exists(self, remote: str, branch: str) -> bool:
        return self.remotes.get(branch, False)

    def remote_url(self, remote: str) -> str:
        url = self.remote_urls.get(remote)
        if url is None:
            raise MotorError(f"remoto {remote} nao configurado")
        return url

    def push_branch(self, remote: str, branch: str) -> None:
        if branch not in self.branches:
            raise MotorError(f"branch {branch} nao existe")
        self.remotes[branch] = True

    def pull_branch(self, remote: str, branch: str) -> None:
        if branch not in self.branches:
            raise MotorError(f"branch {branch} nao existe")
        self.pulled.append(branch)

    def fetch(self, remote: str) -> None:
        self.fetched.append(remote)

    def list_version_branches(self) -> list[str]:
        return sorted(self.branches.keys())

    def read_file(self, branch: str, path: str) -> bytes:
        arquivos = self.files.get(branch)
        if arquivos is None:
            raise MotorError(f"branch {branch} nao tem arquivos")
        conteudo = arquivos.get(path)
        if conteudo is None:
            raise MotorError(f"arquivo {path} nao encontrado em {branch}")
        return conteudo

    def write_file(self, branch: str, path: str, content: bytes, mensagem_commit: str) -> None:
        if branch not in self.files:
            self.files[branch] = {}
        self.files[branch][path] = content
