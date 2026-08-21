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
_PADRAO_HUNK_ORIGEM = re.compile(r"^@@ -(\d+)(?:,(\d+))? ")
_PADRAO_BRANCH_VERSAO = re.compile(r"^\d+\.\d+\.\d+$")
# So refs/remotes/origin/: e o unico remoto que o motor usa (todo entry point
# faz fetch("origin"), e push/pull/remote_branch_exists passam o literal).
# Aceitar qualquer remoto aqui punha no conjunto aberto uma versao que o
# BaseResolver depois nao resolve — ele so tenta refs/remotes/origin/.
_PREFIXO_REF_REMOTA = re.compile(r"^refs/remotes/origin/")
_PADRAO_VERSAO_GIT = re.compile(r"git version (\d+)\.(\d+)")
_CREDENCIAL_EM_URL = re.compile(r"(https?://)[^/@\s]+@", re.IGNORECASE)


def _saida_git_publica(saida: str) -> str:
    return _CREDENCIAL_EM_URL.sub(r"\1[credenciais]@", saida)


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


def _ranges_de_hunks(diff: str) -> list[tuple[int, int]]:
    """Ranges do lado `a` de um diff -U0 — coordenadas do lado esquerdo, que e
    exatamente o que o `log -L` exige (ele rastreia a partir da revisao final
    do range, e nas nossas chamadas essa revisao e o proprio lado `a`).

    Comprimento 0 aparece em dois casos e os dois precisam de tratamento:
    insercao pura (`@@ -3,0 +4 @@`, ancorada *depois* da linha 3) e arquivo
    inexistente no lado `a` (`@@ -0,0 +1,5 @@`). O primeiro colapsa na linha de
    ancoragem; o segundo devolve inicio 0, que o chamador usa para saber que
    nao ha linha nenhuma a rastrear.
    """
    ranges: list[tuple[int, int]] = []
    for linha in diff.split("\n"):
        m = _PADRAO_HUNK_ORIGEM.match(linha)
        if m is None:
            continue
        inicio = int(m.group(1))
        tamanho = 1 if m.group(2) is None else int(m.group(2))
        if tamanho == 0:
            ranges.append((inicio, inicio))
        else:
            ranges.append((inicio, inicio + tamanho - 1))
    return ranges


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
            saida = _saida_git_publica((proc.stdout or "") + (proc.stderr or ""))
            raise MotorError(f"git {' '.join(args)}: exit status {proc.returncode}: {saida}")

    def _output(self, dir_: str, *args: str) -> str:
        with _cronometrar(*args):
            proc = subprocess.run(["git", *args], cwd=dir_, capture_output=True, text=True)
        if proc.returncode != 0:
            raise MotorError(
                f"git {' '.join(args)}: exit status {proc.returncode}: "
                f"{_saida_git_publica(proc.stderr)}"
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
            "git merge-base --is-ancestor: exit status "
            f"{proc.returncode}: {_saida_git_publica(proc.stderr)}"
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
        # %cI (data do COMMITTER), nao %aI como nas varreduras de range: o unico
        # consumidor de commit_date daqui e a data de liberacao (a tag aponta um
        # commit, e "quando essa versao saiu" e quando o commit entrou nesta
        # branch). Num cherry-pick a data do autor e a da escrita original, que
        # pode ser de meses antes. As varreduras seguem em %aI porque
        # ordenar_por_data quer a ordem de autoria.
        out = self._output(
            self.repo_path,
            "show",
            "-s",
            f"--format=%H{SEPARADOR_CAMPO}%cI{SEPARADOR_CAMPO}%B",
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
                "git patch-id --stable: exit status "
                f"{patch.returncode}: {_saida_git_publica(patch.stderr)}"
            )
        campos = patch.stdout.split()
        if not campos:
            raise MotorError(f"patch-id vazio para {hash}")
        return campos[0]

    def changed_files(self, hash: str) -> frozenset[str]:
        out = self._output(
            self.repo_path, "diff-tree", "--no-commit-id", "--name-only", "-r", hash
        )
        return frozenset(l for l in out.split("\n") if l != "")

    def resolve_ref(self, ref: str) -> str:
        # ^{commit} descasca tag anotada: as tags de release deste projeto sao
        # anotadas, e `rev-parse refs/tags/X` devolve o SHA do OBJETO DE TAG,
        # nao do commit. Sem descascar, BaseResolver gravaria esse SHA em
        # versao.base_commit (coluna de auditoria que entao nao nomeia commit
        # nenhum: `git show` mostra a tag e o join com
        # atribuicao_commit.hash_origem nao acha nada) e commit_meta devolveria
        # "tag X\nTagger: ...". No-op para branch, tag leve e hash cru — X^{commit}
        # nao muda nada quando X ja resolve para um commit.
        return self._output(self.repo_path, "rev-parse", f"{ref}^{{commit}}")

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
        saida = _saida_git_publica((proc.stdout or "") + (proc.stderr or ""))
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
            saida = _saida_git_publica((proc.stdout or "") + (proc.stderr or ""))
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
            return MergePrediction(
                conflita=False,
                arquivos_conflito=[],
                arvore_resultante=proc.stdout.strip(),
            )
        saida = _saida_git_publica((proc.stdout or "") + (proc.stderr or ""))
        if proc.returncode == 1:
            return MergePrediction(conflita=True, arquivos_conflito=_parse_conflict_files(saida))
        raise MotorError(
            f"git merge-tree --write-tree --merge-base={parent} {branch_tip} {commit}: "
            f"exit status {proc.returncode}: {saida}"
        )

    def culpados_por_linha(
        self, base: str, parent: str, commit: str, arquivos: list[str]
    ) -> dict[str, list[CommitRef]]:
        formato = f"--format=%H{SEPARADOR_CAMPO}%aI{SEPARADOR_CAMPO}%B{SEPARADOR_REGISTRO}"
        resultado: dict[str, list[CommitRef]] = {}
        for arquivo in arquivos:
            diff = self._output(
                self.repo_path, "diff", "-U0", parent, commit, "--", arquivo
            )
            ranges = _ranges_de_hunks(diff)
            if not ranges:
                continue
            if any(inicio == 0 for inicio, _ in ranges):
                # Arquivo nao existe em `parent` (conflito modify/delete, ou
                # arquivo que so o `commit` cria): nao ha linha a rastrear e o
                # `-L` erraria com "there is no path". Quem tocou o arquivo no
                # range e o candidato — e num modify/delete e literalmente quem
                # o apagou.
                commits = _parse_log(
                    self._output(
                        self.repo_path, "log", formato, f"{base}..{parent}", "--", arquivo
                    )
                )
            else:
                # -s: sem ele o `log -L` imprime o patch das linhas rastreadas
                # dentro do campo %B, e extrair_chamado passaria a casar `chNNN`
                # que estivesse no *codigo*, nao na mensagem.
                args = ["log", "-s", formato]
                args += [f"-L{a},{b}:{arquivo}" for a, b in ranges]
                args.append(f"{base}..{parent}")
                commits = _parse_log(self._output(self.repo_path, *args))
            if commits:
                resultado[arquivo] = commits
        return resultado

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

    def remote_url(self, remote: str) -> str:
        return self._output(self.repo_path, "remote", "get-url", remote)

    def push_branch(self, remote: str, branch: str) -> None:
        self._run(self._worktree_dir(branch), "push", "-u", remote, branch)

    def pull_branch(self, remote: str, branch: str) -> None:
        self._run(self._worktree_dir(branch), "pull", "--ff-only", remote, branch)

    def fetch(self, remote: str) -> None:
        self._run(self.repo_path, "fetch", remote)

    def list_version_branches(self) -> list[str]:
        # %(refname) + strip manual do prefixo, nao %(refname:short): quando
        # branch e tag tem o mesmo nome (versao fechada, tag criada, branch
        # ainda nao apagada), o short-name fica ambiguo entre refs/heads/X e
        # refs/tags/X e o git devolve "heads/X"/"tags/X" em vez de "X", o que
        # faz a versao sumir do padrao \d+\.\d+\.\d+. Inclui refs/tags/ pra
        # tambem enxergar versoes fechadas cuja branch ja foi apagada, e
        # refs/remotes/origin/ pelo mesmo motivo do outro lado da ausencia: `git
        # fetch origin` cria refs/remotes/origin/X e NENHUM head local, entao
        # uma versao aberta e empurrada de outra maquina so aparece por ai —
        # sem isso `versoes_abertas` seria uma visao local do conjunto aberto e
        # `fontes_de_alvo` omitiria essa versao em silencio (spec §2).
        # `versoes_abertas = todas - tags` continua excluindo as liberadas.
        # Preco aceito: refs/remotes/origin/X velho de branch apagada e nunca
        # liberada le como aberta ate alguem rodar `git fetch --prune`.
        out = self._output(
            self.repo_path,
            "for-each-ref",
            "--format=%(refname)",
            "refs/heads/",
            "refs/tags/",
            "refs/remotes/origin/",
        )
        if out == "":
            return []
        # set: a mesma versao aparece como head local E ref de rastreamento.
        nomes = set()
        for linha in out.split("\n"):
            nome = _PREFIXO_REF_REMOTA.sub("", linha)
            nome = nome.removeprefix("refs/heads/").removeprefix("refs/tags/")
            if _PADRAO_BRANCH_VERSAO.match(nome):
                nomes.add(nome)
        return sorted(nomes)

    def list_version_tags(self) -> list[str]:
        # So refs/tags/ — diferente de list_version_branches, que inclui heads
        # e refs/remotes tambem de proposito (para inferir_base achar versao
        # fechada cuja branch ja foi apagada, e versao aberta em outra maquina).
        out = self._output(
            self.repo_path, "for-each-ref", "--format=%(refname)", "refs/tags/"
        )
        if out == "":
            return []
        nomes = set()
        for linha in out.split("\n"):
            nome = linha.removeprefix("refs/tags/")
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
                f"{_saida_git_publica(proc.stderr.decode(errors='replace'))}"
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
