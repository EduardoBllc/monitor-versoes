"""Transcrição 1-pra-1 de internal/adapters/git/subprocess.go.

GitSubprocess fala com git via subprocess (equivalente a os/exec no Go).
Assume git >= 2.38 (`merge-tree --write-tree`). rerere.enabled/autoUpdate
são configurados aqui, no construtor (`new_git_subprocess`) — não no
engine — espelhando onde o Go liga isso.
"""

from __future__ import annotations

import contextlib
import datetime
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field

from motor.domain.types import CommitRef
from motor.errors import MotorError
from motor.ports import CherryPickOutcome, MergePrediction

logger = logging.getLogger(__name__)

SEPARADOR_CAMPO = "\x1f"
SEPARADOR_REGISTRO = "\x1e"


@contextlib.contextmanager
def _cronometrar(*args: str):
    inicio = time.monotonic()
    try:
        yield
    finally:
        logger.debug("git %s: %.3fs", " ".join(args), time.monotonic() - inicio)

_PADRAO_CONFLITO = re.compile(r"^CONFLICT \([^)]*\): .* in (\S.*)$")
_PADRAO_BRANCH_VERSAO = re.compile(r"^\d+\.\d+\.\d+$")
_PADRAO_VERSAO_GIT = re.compile(r"git version (\d+)\.(\d+)")


def _checar_versao_git() -> None:
    try:
        proc = subprocess.run(["git", "version"], capture_output=True, text=True)
    except OSError as e:
        raise MotorError(f"git nao encontrado: {e}") from e
    if proc.returncode != 0:
        raise MotorError(f"git nao encontrado: exit status {proc.returncode}")
    m = _PADRAO_VERSAO_GIT.match(proc.stdout.strip())
    if not m:
        return  # formato inesperado - nao bloqueia, so nao valida
    major, minor = int(m.group(1)), int(m.group(2))
    if major < 2 or (major == 2 and minor < 38):
        raise MotorError(
            f"git {major}.{minor} encontrado, motor precisa de >= 2.38 "
            "(merge-tree --write-tree)"
        )


def _parse_log(out: str) -> list[CommitRef]:
    if out == "":
        return []
    resultado: list[CommitRef] = []
    for entrada in out.split(SEPARADOR_REGISTRO):
        entrada = entrada.strip("\n")
        if entrada == "":
            continue
        campos = entrada.split(SEPARADOR_CAMPO, 2)
        if len(campos) != 3:
            continue
        try:
            data = datetime.datetime.fromisoformat(campos[1])
        except ValueError as e:
            raise MotorError(f"parseando data do commit {campos[0]}: {e}") from e
        resultado.append(CommitRef(hash_origem=campos[0], commit_date=data, msg=campos[2]))
    return resultado


def _parse_conflict_files(out: str) -> list[str]:
    arquivos: list[str] = []
    for linha in out.split("\n"):
        m = _PADRAO_CONFLITO.match(linha)
        if m:
            arquivos.append(m.group(1))
    return arquivos


@dataclass
class GitSubprocess:
    repo_path: str
    _current_branch: str = field(default="", repr=False)

    def _worktree_dir(self, branch: str) -> str:
        base = os.path.basename(self.repo_path.rstrip(os.sep))
        parent = os.path.dirname(self.repo_path.rstrip(os.sep))
        return os.path.join(parent, base + "-worktrees", branch)

    def _run(self, dir_: str, *args: str) -> None:
        with _cronometrar(*args):
            proc = subprocess.run(["git", *args], cwd=dir_, capture_output=True, text=True)
        if proc.returncode != 0:
            saida = (proc.stdout or "") + (proc.stderr or "")
            raise MotorError(f"git {' '.join(args)}: exit status {proc.returncode}: {saida}")

    def _output(self, dir_: str, *args: str) -> str:
        with _cronometrar(*args):
            proc = subprocess.run(["git", *args], cwd=dir_, capture_output=True, text=True)
        if proc.returncode != 0:
            raise MotorError(
                f"git {' '.join(args)}: exit status {proc.returncode}: {proc.stderr}"
            )
        return proc.stdout.strip()

    # -- GitRepo --------------------------------------------------------

    def merge_base(self, a: str, b: str) -> str:
        return self._output(self.repo_path, "merge-base", a, b)

    def is_ancestor(self, commit: str, branch: str) -> bool:
        with _cronometrar("merge-base", "--is-ancestor", commit, branch):
            proc = subprocess.run(
                ["git", "merge-base", "--is-ancestor", commit, branch],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )
        if proc.returncode == 0:
            return True
        if proc.returncode == 1:
            return False
        raise MotorError(
            f"git merge-base --is-ancestor: exit status {proc.returncode}: {proc.stderr}"
        )

    def search_commits(self, padroes: list[str], refs: str) -> list[CommitRef]:
        args = [
            "log",
            refs,
            "--no-merges",
            f"--format=%H{SEPARADOR_CAMPO}%aI{SEPARADOR_CAMPO}%B{SEPARADOR_REGISTRO}",
        ]
        for p in padroes:
            if p != "":
                args.append(f"--grep={p}")
        out = self._output(self.repo_path, *args)
        return _parse_log(out)

    def commits_in_range(self, from_: str, to: str) -> list[CommitRef]:
        out = self._output(
            self.repo_path,
            "log",
            f"{from_}..{to}",
            f"--format=%H{SEPARADOR_CAMPO}%aI{SEPARADOR_CAMPO}%B{SEPARADOR_REGISTRO}",
        )
        return _parse_log(out)

    def commit_meta(self, hash: str) -> CommitRef:
        out = self._output(
            self.repo_path,
            "show",
            "-s",
            f"--format=%H{SEPARADOR_CAMPO}%aI{SEPARADOR_CAMPO}%B",
            hash,
        )
        campos = out.split(SEPARADOR_CAMPO, 2)
        if len(campos) != 3:
            raise MotorError(f"saida inesperada de git show: {out!r}")
        try:
            data = datetime.datetime.fromisoformat(campos[1])
        except ValueError as e:
            raise MotorError(f"parseando data do commit {campos[0]}: {e}") from e
        try:
            parent = self._output(self.repo_path, "rev-parse", hash + "^")
        except MotorError:
            parent = ""
        return CommitRef(hash_origem=campos[0], commit_date=data, msg=campos[2], parent=parent)

    def patch_id(self, hash: str) -> str:
        with _cronometrar("show", hash, "|", "patch-id"):
            show = subprocess.Popen(
                ["git", "show", hash], cwd=self.repo_path, stdout=subprocess.PIPE
            )
            try:
                patch = subprocess.run(
                    ["git", "patch-id", "--stable"],
                    cwd=self.repo_path,
                    stdin=show.stdout,
                    capture_output=True,
                    text=True,
                )
            finally:
                if show.stdout is not None:
                    show.stdout.close()
                show_ret = show.wait()
        if show_ret != 0:
            raise MotorError(f"git show {hash}: exit status {show_ret}")
        if patch.returncode != 0:
            raise MotorError(
                f"git patch-id --stable: exit status {patch.returncode}: {patch.stderr}"
            )
        campos = patch.stdout.split()
        if not campos:
            raise MotorError(f"patch-id vazio para {hash}")
        return campos[0]

    def resolve_ref(self, ref: str) -> str:
        return self._output(self.repo_path, "rev-parse", ref)

    def use_worktree(self, branch: str) -> None:
        """Se a worktree ja existe em disco, so usa. Senao, tenta adotar uma
        branch ja existente (local ou remota) - caso de branch de versao
        criada manualmente (ex: Bitbucket) sem passar por `criar`."""
        dir_ = self._worktree_dir(branch)
        if not os.path.exists(dir_):
            try:
                self._run(self.repo_path, "worktree", "add", dir_, branch)
            except MotorError as e:
                raise MotorError(
                    f"worktree de {branch} nao encontrada em {dir_} e branch "
                    f"{branch} nao existe pra adotar (rode 'motor criar {branch}' "
                    f"primeiro): {e}"
                ) from e
        self._current_branch = branch

    def cherry_pick_x(self, hash: str) -> CherryPickOutcome:
        dir_ = self._worktree_dir(self._current_branch)
        with _cronometrar("cherry-pick", "-x", hash):
            proc = subprocess.run(
                ["git", "cherry-pick", "-x", hash], cwd=dir_, capture_output=True, text=True
            )
        if proc.returncode == 0:
            return CherryPickOutcome.APLICADO
        _, pendente = self.pending_cherry_pick()
        if pendente:
            return CherryPickOutcome.CONFLITO
        saida = (proc.stdout or "") + (proc.stderr or "")
        raise MotorError(
            f"git cherry-pick -x {hash}: exit status {proc.returncode}: {saida}"
        )

    def conflicted_paths(self) -> list[str]:
        dir_ = self._worktree_dir(self._current_branch)
        out = self._output(dir_, "diff", "--name-only", "--diff-filter=U")
        if out == "":
            return []
        return out.split("\n")

    def pending_cherry_pick(self) -> tuple[str, bool]:
        dir_ = self._worktree_dir(self._current_branch)
        try:
            hash_ = self._output(dir_, "rev-parse", "CHERRY_PICK_HEAD")
        except MotorError:
            return "", False
        return hash_, True

    def continue_cherry_pick(self) -> None:
        dir_ = self._worktree_dir(self._current_branch)
        self._run(dir_, "add", "-A")
        env = os.environ.copy()
        env["GIT_EDITOR"] = "true"
        with _cronometrar("cherry-pick", "--continue"):
            proc = subprocess.run(
                ["git", "cherry-pick", "--continue"],
                cwd=dir_,
                capture_output=True,
                text=True,
                env=env,
            )
        if proc.returncode != 0:
            saida = (proc.stdout or "") + (proc.stderr or "")
            raise MotorError(f"git cherry-pick --continue: exit status {proc.returncode}: {saida}")

    def abort_cherry_pick(self) -> None:
        self._run(self._worktree_dir(self._current_branch), "cherry-pick", "--abort")

    def predict_merge(self, parent: str, branch_tip: str, commit: str) -> MergePrediction:
        args = ("merge-tree", "--write-tree", f"--merge-base={parent}", branch_tip, commit)
        with _cronometrar(*args):
            proc = subprocess.run(
                ["git", *args],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )
        if proc.returncode == 0:
            return MergePrediction(conflita=False, arquivos_conflito=[])
        saida = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 1:
            return MergePrediction(conflita=True, arquivos_conflito=_parse_conflict_files(saida))
        raise MotorError(
            f"git merge-tree --write-tree --merge-base={parent} {branch_tip} {commit}: "
            f"exit status {proc.returncode}: {saida}"
        )

    def worktree_add(self, branch: str, base: str) -> None:
        dir_ = self._worktree_dir(branch)
        self._run(self.repo_path, "worktree", "add", "-b", branch, dir_, base)
        self._current_branch = branch

    def worktree_remove(self, branch: str) -> None:
        # --force: descarta cruft nao rastreado (deps instaladas, .env etc) que
        # bloquearia a remocao - a branch ja esta com tudo commitado e pushado
        # nesse ponto, nao ha nada de valor no diretorio da worktree em si.
        self._run(self.repo_path, "worktree", "remove", "--force", self._worktree_dir(branch))

    def tag_exists(self, tag: str) -> bool:
        out = self._output(self.repo_path, "tag", "-l", tag)
        return out != ""

    def remote_branch_exists(self, remote: str, branch: str) -> bool:
        out = self._output(self.repo_path, "ls-remote", "--heads", remote, branch)
        return out != ""

    def push_branch(self, remote: str, branch: str) -> None:
        self._run(self._worktree_dir(branch), "push", "-u", remote, branch)

    def pull_branch(self, remote: str, branch: str) -> None:
        self._run(self._worktree_dir(branch), "pull", "--ff-only", remote, branch)

    def list_version_branches(self) -> list[str]:
        # %(refname) + strip manual do prefixo, nao %(refname:short): quando
        # branch e tag tem o mesmo nome (versao fechada, tag criada, branch
        # ainda nao apagada), o short-name fica ambiguo entre refs/heads/X e
        # refs/tags/X e o git devolve "heads/X"/"tags/X" em vez de "X", o que
        # faz a versao sumir do padrao \d+\.\d+\.\d+. Inclui refs/tags/ pra
        # tambem enxergar versoes fechadas cuja branch ja foi apagada.
        out = self._output(
            self.repo_path,
            "for-each-ref",
            "--format=%(refname)",
            "refs/heads/",
            "refs/tags/",
        )
        if out == "":
            return []
        nomes = set()
        for linha in out.split("\n"):
            nome = linha.removeprefix("refs/heads/").removeprefix("refs/tags/")
            if _PADRAO_BRANCH_VERSAO.match(nome):
                nomes.add(nome)
        return sorted(nomes)

    def read_file(self, branch: str, path: str) -> bytes:
        proc = subprocess.run(
            ["git", "show", f"{branch}:{path}"], cwd=self.repo_path, capture_output=True
        )
        if proc.returncode != 0:
            raise MotorError(
                f"git show {branch}:{path}: exit status {proc.returncode}: "
                f"{proc.stderr.decode(errors='replace')}"
            )
        return proc.stdout

    def write_file(
        self, branch: str, path: str, content: bytes, mensagem_commit: str
    ) -> None:
        dir_ = self._worktree_dir(branch)
        full_path = os.path.join(dir_, path)
        with open(full_path, "wb") as f:
            f.write(content)
        self._run(dir_, "add", path)

        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", path],
            cwd=dir_,
            capture_output=True,
        )
        if diff.returncode == 0:
            return  # conteudo igual ao ja commitado - nada a fazer

        self._run(dir_, "commit", "-m", mensagem_commit)


def new_git_subprocess(repo_path: str) -> GitSubprocess:
    """Espelha git.NewGitSubprocess: valida versão e liga rerere aqui."""
    _checar_versao_git()
    g = GitSubprocess(repo_path=repo_path)
    g._run(repo_path, "config", "rerere.enabled", "true")
    g._run(repo_path, "config", "rerere.autoUpdate", "true")
    return g
