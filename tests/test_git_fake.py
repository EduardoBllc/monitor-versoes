"""Porte de internal/adapters/git/fake_test.go."""

import datetime
import inspect

import pytest

from motor.adapters.git.fake import FakeGit
from motor.domain.types import CommitRef
from motor.errors import MotorError
from motor.ports import CherryPickOutcome


def test_fake_git_remote_url():
    g = FakeGit()
    g.remote_urls["origin"] = "git@bitbucket.org:acme/monitor.git"
    assert g.remote_url("origin") == "git@bitbucket.org:acme/monitor.git"


def test_fake_git_cherry_pick_aplica_e_encadeia_trailer():
    g = FakeGit()
    base = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", base)
    g.add_commit("base-tip", "", "base", base)
    g.set_branch("13.7.0", "base-tip")

    outcome = g.cherry_pick_x("origem1")

    assert outcome == CherryPickOutcome.APLICADO, f"outcome = {outcome}, quer APLICADO"

    novo_tip = g.branches["13.7.0"]
    commit = g.commits[novo_tip]
    assert commit.origem_hash == "origem1", f"origem_hash = {commit.origem_hash!r}, quer origem1"


def test_fake_git_cherry_pick_conflito_e_continue():
    g = FakeGit()
    now = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: algo", now)
    g.add_commit("base-tip", "", "base", now)
    g.set_branch("13.7.0", "base-tip")
    g.conflict_on["origem1"] = True

    outcome = g.cherry_pick_x("origem1")

    assert outcome == CherryPickOutcome.CONFLITO, f"outcome = {outcome}, quer CONFLITO"

    paths = g.conflicted_paths()
    assert len(paths) > 0, "esperava arquivos em conflito"

    hash_, ok = g.pending_cherry_pick()
    assert ok and hash_ == "origem1", f"pending_cherry_pick = {hash_!r}, {ok}; quer origem1, True"

    g.continue_cherry_pick()

    assert g.conflicted_paths() == [], "apos continue, nao deveria sobrar conflito"

    _, ok = g.pending_cherry_pick()
    assert not ok, "nao deveria sobrar cherry-pick pendente apos continue"


def test_fake_git_read_write_file():
    g = FakeGit()
    g.write_file("13.7.0", "VERSAO.lock", b"{}", "atualiza lock")

    conteudo = g.read_file("13.7.0", "VERSAO.lock")

    assert conteudo == b"{}", f"conteudo = {conteudo!r}, quer {{}}"


def test_fake_git_is_ancestor_e_merge_base():
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("c1", "", "primeiro", t0)
    g.add_commit("c2", "c1", "segundo", t0)
    g.set_branch("master", "c2")

    ok = g.is_ancestor("c1", "master")
    assert ok, f"is_ancestor(c1, master) = {ok}, quer True"

    ok = g.is_ancestor("naoexiste", "master")
    assert not ok, f"is_ancestor(naoexiste, master) = {ok}, quer False"


def test_fake_git_merge_base_branches_divergentes():
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("r", "", "raiz", t0)
    g.add_commit("y", "r", "commit y", t0)
    g.add_commit("x", "y", "commit x", t0)
    g.add_commit("w", "r", "commit w", t0)
    g.add_commit("z", "w", "commit z", t0)
    g.set_branch("branchA", "x")
    g.set_branch("branchB", "z")

    base = g.merge_base("branchA", "branchB")

    assert base == "r", f"merge_base(branchA, branchB) = {base!r}, quer r"


def test_fake_list_version_tags_so_devolve_tags():
    git = FakeGit(branches={"13.34.0": "aaa", "14.0.0": "bbb"},
                  tags={"13.34.0": True})
    assert git.list_version_tags() == ["13.34.0"]


def test_fake_list_version_branches_filtra_por_formato():
    # Espelha o adapter real (subprocess.py:352). Sem o filtro, 'master' entra
    # no conjunto e versoes_abertas estoura em chave("master").
    git = FakeGit(branches={"master": "m", "13.34.0": "aaa"}, tags={"13.33.0": True})
    assert git.list_version_branches() == ["13.33.0", "13.34.0"]


def test_fake_list_version_branches_respeita_tag_false():
    # tags dict tem valores bool: True = tag existe, False = nao existe.
    # list_version_branches deve respeitar isso — versao com False nao deve aparecer.
    git = FakeGit(
        branches={"13.34.0": "aaa"},
        tags={"13.33.0": True, "13.35.0": False}
    )
    assert git.list_version_branches() == ["13.33.0", "13.34.0"]
    assert git.list_version_tags() == ["13.33.0"]


def test_fake_list_version_branches_inclui_ref_de_rastreamento():
    """Espelha o adapter real: `git fetch origin` cria refs/remotes/origin/X e
    NENHUM head local, entao uma versao aberta e empurrada de outra maquina so
    aparece pela ref de rastreamento. Fake diferente do real esconde bug.
    """
    git = FakeGit(branches={"13.34.0": "aaa"}, remote_refs={"13.35.0": "bbb"})
    assert git.list_version_branches() == ["13.34.0", "13.35.0"]


def test_fake_nome_puro_nao_resolve_ref_de_rastreamento():
    """Tambem como o git: `rev-parse X` olha refs/heads e refs/tags, nunca
    refs/remotes/<remoto>/X. Um fake que resolvesse o nome puro esconderia o
    erro que o BaseResolver tem de contornar.
    """
    git = FakeGit(remote_refs={"13.35.0": "bbb"})

    with pytest.raises(MotorError):
        git.resolve_ref("13.35.0")
    assert git.resolve_ref("refs/remotes/origin/13.35.0") == "bbb"


def test_fake_culpados_por_linha_devolve_a_fixture():
    """O fake nao faz matematica de hunk: a atribuicao vem configurada, como
    conflict_on e merge_predictions.
    """
    culpado = CommitRef(hash_origem="c200", msg="fix: ch200 mexe a linha 3")
    git = FakeGit(culpados_por_linha_por_commit={"c400": {"a.txt": [culpado]}})

    assert git.culpados_por_linha("base", "c300", "c400", ["a.txt"]) == {
        "a.txt": [culpado]
    }


def test_fake_culpados_por_linha_filtra_pelos_arquivos_pedidos():
    """Sem o filtro, um teste de engine passaria arquivos_conflito=[] e ainda
    veria culpados — o real nunca faria isso.
    """
    culpado = CommitRef(hash_origem="c200", msg="fix: ch200")
    git = FakeGit(culpados_por_linha_por_commit={"c400": {"a.txt": [culpado]}})

    assert git.culpados_por_linha("base", "c300", "c400", ["outro.txt"]) == {}


def test_fake_culpados_por_linha_sem_fixture_e_vazio():
    git = FakeGit()
    assert git.culpados_por_linha("base", "c300", "c400", ["a.txt"]) == {}


def test_fake_culpados_por_linha_tem_a_assinatura_do_adapter_real():
    """Fake divergente do real deixa a suite verde num caminho que quebra em
    producao — o mesmo custo que o contrato de EstadoRepo existe para evitar.
    """
    from motor.adapters.git.subprocess import GitSubprocess

    assert inspect.signature(FakeGit.culpados_por_linha) == inspect.signature(
        GitSubprocess.culpados_por_linha
    )
