"""Porte de internal/services/publication_gate_test.go."""

from motor.adapters.git.fake import FakeGit
from motor.services.publication_gate import PublicationGate


def test_publication_gate_tag_local():
    g = FakeGit()
    g.tags["13.7.0"] = True

    gate = PublicationGate(git=g)
    ok = gate.publicada("13.7.0")

    assert ok, f"publicada = {ok}, quer True"


def test_publication_gate_branch_remota():
    g = FakeGit()
    g.remotes["13.7.0"] = True

    gate = PublicationGate(git=g)
    ok = gate.publicada("13.7.0")

    assert ok, f"publicada = {ok}, quer True"


def test_publication_gate_nao_publicada():
    g = FakeGit()

    gate = PublicationGate(git=g)
    ok = gate.publicada("13.7.0")

    assert not ok, f"publicada = {ok}, quer False"


def test_liberada_e_so_a_tag_nao_a_branch_remota():
    git = FakeGit(tags={"13.34.0": True}, remotes={"14.0.0": True})
    gate = PublicationGate(git=git)

    assert gate.liberada("13.34.0") is True
    # branch remota nao e liberacao: e so trabalho compartilhado
    assert gate.liberada("14.0.0") is False
    assert gate.publicada("14.0.0") is True
