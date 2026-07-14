"""Porte de internal/services/presence_oracle_test.go."""

import datetime

from motor.adapters.git.fake import FakeGit
from motor.domain.types import Presence
from motor.errors import MotorError
from motor.services.presence_oracle import PresenceOracle


def test_presence_oracle_ancestral_direto():
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("c1", "", "primeiro", t0)
    g.add_commit("c2", "c1", "segundo", t0)
    g.set_branch("14.0.0", "c2")

    oracle = PresenceOracle(git=g)
    ok = oracle.presente("c1", "master", "14.0.0")

    assert ok == Presence.ANCESTRAL, "esperava presente=true (ancestral direto)"


def test_presence_oracle_via_trailer():
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: algo", t0)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")

    g.cherry_pick_x("origem1")

    oracle = PresenceOracle(git=g)
    ok = oracle.presente("origem1", "13.6.0", "13.7.0")

    assert ok == Presence.TRAILER, "esperava presente=true (via trailer)"


def test_presence_oracle_ausente():
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: nunca aplicado", t0)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")

    oracle = PresenceOracle(git=g)
    ok = oracle.presente("origem1", "13.6.0", "13.7.0")

    assert ok == Presence.AUSENTE, "esperava presente=false"


def test_presence_oracle_commits_in_range_falha_trata_como_ausente():
    """Cobre o fallback do §2 ("senao -> ausente"): se commits_in_range nao
    consegue confirmar (ex.: o objeto sumiu do historico, git levanta erro),
    presente deve reportar ausente sem propagar o erro.
    """
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: algo", t0)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")
    g.commits_in_range_err = MotorError("objeto sumiu do historico (simulado)")

    oracle = PresenceOracle(git=g)
    ok = oracle.presente("origem1", "13.6.0", "13.7.0")

    assert ok == Presence.AUSENTE, "esperava presente=false quando commits_in_range falha"


def test_presence_oracle_patch_id_origem_falha_trata_como_ausente():
    """Merge commits "limpos" tem diff vazio no `git show` default, entao
    `git patch-id` nao retorna nada e GitSubprocess.patch_id levanta erro.
    O nivel 3 (patch-id) deve degradar para ausente em vez de propagar,
    simetrico ao fallback ja aplicado ao patch-id dos candidatos.
    """
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("base-tip", "", "base", t0)
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "base-tip")

    oracle = PresenceOracle(git=g)
    ok = oracle.presente("merge-sem-patch-id", "13.6.0", "13.7.0")

    assert ok == Presence.AUSENTE, "esperava presente=false quando patch_id do hash de origem falha"
