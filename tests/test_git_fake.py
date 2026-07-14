"""Porte de internal/adapters/git/fake_test.go."""

import datetime

from motor.adapters.git.fake import FakeGit
from motor.ports import CherryPickOutcome


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
