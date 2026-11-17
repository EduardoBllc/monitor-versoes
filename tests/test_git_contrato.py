"""Contrato de GitRepo: as mesmas asserções contra o `GitSubprocess` e o `FakeGit`.

O lado real testa o adapter que a aplicação usa; o lado fake obriga o dublê,
que sai no pacote (`motor/conformidade.py`), a se comportar igual. Semear é a
única coisa que difere: o git recebe commits por plumbing, o fake recebe dicts.
"""

from __future__ import annotations

import datetime
import os
import subprocess
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import pytest

from motor.adapters.git.fake import FakeGit
from motor.adapters.git.subprocess import new_git_subprocess
from motor.domain.conflito import Estagios
from motor.errors import MotorError
from motor.ports import CherryPickOutcome, GitRepo

ARQUIVO = "arquivo.txt"
PRINCIPAL = "principal"
V1, V2, V3, V4 = "13.1.0", "13.2.0", "13.3.0", "13.4.0"
#: Branches das versões conhecidas, da mais recente para a mais antiga.
NOSSAS = [V4, V3, V2, V1]
CEDO = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
TARDE = CEDO + datetime.timedelta(days=5)
TRAILER_PICK = "(cherry picked from commit {})"
HASH_AUSENTE = "f" * 40
FORA_DO_FORMATO = "v1.0"


class Implementacao(StrEnum):
    FAKE = "fake"
    GIT = "git"


class Semente(Protocol):
    @property
    def git(self) -> GitRepo: ...

    def commit(
        self,
        pai: str | None,
        msg: str,
        arquivos: dict[str, str],
        data: datetime.datetime,
    ) -> str: ...
    def branch(self, nome: str, commit: str) -> None: ...
    def ref_remota(self, nome: str, commit: str) -> None: ...
    def tag(self, nome: str, commit: str) -> None: ...
    def conflito(self, commit: str, arquivo: str) -> None: ...


class _SementeFake:
    def __init__(self) -> None:
        self.git = FakeGit()
        self._n = 0

    def commit(
        self,
        pai: str | None,
        msg: str,
        arquivos: dict[str, str],
        data: datetime.datetime,
    ) -> str:
        self._n += 1
        hash_ = f"c{self._n}"
        self.git.add_commit(hash_, pai or "", msg, data)
        return hash_

    def branch(self, nome: str, commit: str) -> None:
        self.git.branches[nome] = commit

    def ref_remota(self, nome: str, commit: str) -> None:
        self.git.remote_refs[nome] = commit

    def tag(self, nome: str, commit: str) -> None:
        self.git.tags[nome] = True
        self.git.tag_commits[nome] = commit

    def conflito(self, commit: str, arquivo: str) -> None:
        # O fake não faz merge: o conflito que o git acha pelo conteúdo vem configurado.
        self.git.conflict_on[commit] = True
        self.git.estagios_on[commit] = {
            arquivo: Estagios(None, None, None, None, binario=False)
        }


class _SementeGit:
    def __init__(self, raiz: Path) -> None:
        self._repo = raiz / "repo"
        self._repo.mkdir()
        self._git("init", "-q", "-b", PRINCIPAL)
        self._git("config", "user.name", "contrato")
        self._git("config", "user.email", "contrato@example.com")
        self.git = new_git_subprocess(str(self._repo))

    def _git(self, *args: str, entrada: str | None = None, data: str = "") -> str:
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1"}
        if data:
            env |= {"GIT_AUTHOR_DATE": data, "GIT_COMMITTER_DATE": data}
        return subprocess.run(
            ["git", *args],
            cwd=self._repo,
            input=entrada,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def commit(
        self,
        pai: str | None,
        msg: str,
        arquivos: dict[str, str],
        data: datetime.datetime,
    ) -> str:
        linhas = "".join(
            f"100644 blob {self._git('hash-object', '-w', '--stdin', entrada=conteudo)}\t{nome}\0"
            for nome, conteudo in arquivos.items()
        )
        # -z: no Windows o stdin em modo texto vira \r\n e o \r entraria no nome.
        arvore = self._git("mktree", "-z", entrada=linhas)
        pais = ["-p", pai] if pai else []
        return self._git("commit-tree", arvore, *pais, "-m", msg, data=data.isoformat())

    def branch(self, nome: str, commit: str) -> None:
        self._git("branch", nome, commit)

    def ref_remota(self, nome: str, commit: str) -> None:
        self._git("update-ref", f"refs/remotes/origin/{nome}", commit)

    def tag(self, nome: str, commit: str) -> None:
        self._git("tag", nome, commit)

    def conflito(self, commit: str, arquivo: str) -> None:
        """O conteúdo dos commits já produz o conflito."""


@pytest.fixture(params=list(Implementacao))
def semente(request, tmp_path) -> Semente:
    if request.param == Implementacao.FAKE:
        return _SementeFake()
    return _SementeGit(tmp_path)


def _raiz(s: Semente) -> str:
    return s.commit(None, "raiz", {ARQUIVO: "v0\n"}, CEDO)


# -- refs ------------------------------------------------------------------------


def test_listar_branches_inclui_ref_de_rastreamento(semente):
    """`git fetch` cria refs/remotes/origin/X sem head local: uma versão empurrada
    de outra máquina só aparece por aí."""
    c = _raiz(semente)
    semente.branch(V3, c)
    semente.ref_remota(V4, c)

    assert semente.git.listar_branches() == [V3, V4]


def test_nome_puro_nao_resolve_ref_de_rastreamento(semente):
    c = _raiz(semente)
    semente.ref_remota(V4, c)

    with pytest.raises(MotorError):
        semente.git.resolve_ref(V4)
    assert semente.git.resolve_ref(f"refs/remotes/origin/{V4}") == c


def test_ref_ausente_e_erro(semente):
    _raiz(semente)

    with pytest.raises(MotorError):
        semente.git.resolve_ref(V4)


def test_branches_e_tags_sem_filtro_e_com_o_mesmo_nome(semente):
    """Versão liberada cuja branch não foi apagada tem branch e tag com o mesmo
    nome: as duas listas a mostram."""
    c = _raiz(semente)
    semente.branch(PRINCIPAL, c)
    semente.branch(V4, c)
    semente.branch(V2, c)
    semente.tag(V2, c)
    semente.tag(V3, c)
    semente.tag(FORA_DO_FORMATO, c)

    assert semente.git.listar_branches() == [V2, V4, PRINCIPAL]
    assert semente.git.listar_tags() == [V2, V3, FORA_DO_FORMATO]


# -- metadados e grafo -----------------------------------------------------------


def test_commits_meta_omite_hash_ausente_e_bate_com_commit_meta(semente):
    raiz = _raiz(semente)
    filho = semente.commit(raiz, "filho", {ARQUIVO: "v1\n"}, TARDE)

    lote = semente.git.commits_meta([raiz, filho, HASH_AUSENTE])

    assert set(lote) == {raiz, filho}
    assert lote[raiz] == semente.git.commit_meta(raiz)
    assert lote[filho] == semente.git.commit_meta(filho)
    assert semente.git.commits_meta([HASH_AUSENTE]) == {}
    assert semente.git.commits_meta([]) == {}


def test_ordem_topologica_segue_o_grafo_e_ignora_data_e_hash_ausente(semente):
    raiz = _raiz(semente)
    pai = semente.commit(raiz, "escrito depois", {ARQUIVO: "v1\n"}, TARDE)
    filho = semente.commit(
        pai, "escrito antes, rebasado em cima", {ARQUIVO: "v2\n"}, CEDO
    )

    assert semente.git.ordem_topologica([filho, HASH_AUSENTE, pai]) == [pai, filho]
    assert semente.git.ordem_topologica([]) == []


def test_is_ancestor(semente):
    raiz = _raiz(semente)
    filho = semente.commit(raiz, "filho", {ARQUIVO: "v1\n"}, CEDO)
    lateral = semente.commit(raiz, "lateral", {ARQUIVO: "lateral\n"}, CEDO)
    semente.branch(PRINCIPAL, filho)

    assert semente.git.is_ancestor(raiz, PRINCIPAL)
    assert not semente.git.is_ancestor(lateral, PRINCIPAL)


def test_ancestral_de_branch_inexistente_e_erro(semente):
    raiz = _raiz(semente)

    with pytest.raises(MotorError):
        semente.git.is_ancestor(raiz, V4)


def test_commit_fora_do_clone_nao_e_ancestral(semente):
    """Commit de PR rebaseada ou squashada não existe no clone: a verificação
    segue para os outros níveis em vez de cair."""
    semente.branch(PRINCIPAL, _raiz(semente))

    assert not semente.git.is_ancestor(HASH_AUSENTE, PRINCIPAL)


def test_merge_base_de_branches_divergentes_e_a_raiz_comum(semente):
    raiz = _raiz(semente)
    a = semente.commit(raiz, "a", {ARQUIVO: "a\n"}, CEDO)
    b = semente.commit(raiz, "b", {ARQUIVO: "b\n"}, CEDO)
    semente.branch(V3, semente.commit(a, "a2", {ARQUIVO: "a2\n"}, CEDO))
    semente.branch(V4, semente.commit(b, "b2", {ARQUIVO: "b2\n"}, CEDO))

    assert semente.git.merge_base(V3, V4) == raiz


# -- cherry-pick -----------------------------------------------------------------


def test_cherry_pick_aplicado_encadeia_o_trailer_da_origem(semente):
    raiz = _raiz(semente)
    origem = semente.commit(
        raiz, "fix: ch255514 corrige logs", {ARQUIVO: "v0\n", "novo.txt": "x\n"}, CEDO
    )
    semente.branch(V4, raiz)
    semente.git.use_worktree(V4)

    assert semente.git.cherry_pick_x(origem) == CherryPickOutcome.APLICADO

    tip = semente.git.commit_meta(semente.git.resolve_ref(V4))
    assert TRAILER_PICK.format(origem) in tip.msg


def test_cherry_pick_em_conflito_fica_pendente_ate_o_continue(semente):
    raiz = _raiz(semente)
    origem = semente.commit(raiz, "origem", {ARQUIVO: "origem\n"}, CEDO)
    semente.branch(V4, semente.commit(raiz, "base", {ARQUIVO: "base\n"}, CEDO))
    semente.conflito(origem, ARQUIVO)
    semente.git.use_worktree(V4)

    assert semente.git.cherry_pick_x(origem) == CherryPickOutcome.CONFLITO
    assert semente.git.conflicted_paths() == [ARQUIVO]
    assert semente.git.pending_cherry_pick() == (origem, True)

    assert semente.git.continue_cherry_pick() == CherryPickOutcome.APLICADO
    assert semente.git.conflicted_paths() == []
    assert semente.git.pending_cherry_pick() == ("", False)


# -- worktrees -------------------------------------------------------------------


def _usadas(semente: Semente, *branches: str) -> None:
    c = _raiz(semente)
    for b in branches:
        semente.branch(b, c)
        semente.git.use_worktree(b)


def test_worktree_add_de_branch_que_ja_existe_e_recusado(semente):
    c = _raiz(semente)
    semente.branch(V4, c)

    with pytest.raises(MotorError):
        semente.git.worktree_add(V4, c)


def test_worktree_gc_mantem_as_mais_usadas(semente):
    _usadas(semente, V1, V2, V3)

    assert semente.git.worktree_gc(2, V3, NOSSAS) == [V1]


def test_worktree_gc_promove_a_worktree_reusada(semente):
    _usadas(semente, V1, V2, V3)
    semente.git.use_worktree(V1)

    assert semente.git.worktree_gc(2, V1, NOSSAS) == [V2]


def test_worktree_gc_com_manter_zero_remove_todas_e_a_removida_sai(semente):
    _usadas(semente, V1)

    assert semente.git.worktree_gc(0, V1, NOSSAS) == [V1]
    assert semente.git.worktree_gc(0, V1, NOSSAS) == []


def test_worktree_gc_conta_a_criada_por_worktree_add(semente):
    c = _raiz(semente)
    semente.branch(PRINCIPAL, c)

    semente.git.worktree_add(V4, PRINCIPAL)

    assert semente.git.worktree_gc(0, "", NOSSAS) == [V4]


def test_worktree_gc_so_considera_as_versoes_conhecidas(semente):
    fora = "experimento"
    _usadas(semente, V1, fora)

    assert semente.git.worktree_gc(0, "", [V1]) == [V1]
    assert semente.git.worktree_gc(0, "", [V1, fora]) == [fora]
