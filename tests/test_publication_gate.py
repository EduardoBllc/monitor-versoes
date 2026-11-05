"""Porte de internal/services/publication_gate_test.go."""

from motor.adapters.git.fake import FakeGit
from motor.ports import GitRepo
from motor.services.catalogo import Catalogo
from motor.services.publication_gate import PublicationGate
from motor.services.versionamento import versionamento_padrao


def _gate(git: GitRepo) -> PublicationGate:
    return PublicationGate(git, Catalogo(git, versionamento_padrao()))


def test_publication_gate_tag_local():
    g = FakeGit()
    g.tags["13.7.0"] = True

    gate = _gate(g)
    ok = gate.publicada("13.7.0")

    assert ok, f"publicada = {ok}, quer True"


def test_publication_gate_branch_remota():
    g = FakeGit()
    g.remotes["13.7.0"] = True

    gate = _gate(g)
    ok = gate.publicada("13.7.0")

    assert ok, f"publicada = {ok}, quer True"


def test_publication_gate_nao_publicada():
    g = FakeGit()

    gate = _gate(g)
    ok = gate.publicada("13.7.0")

    assert not ok, f"publicada = {ok}, quer False"


def test_liberada_e_so_o_criterio_nao_a_branch_remota():
    git = FakeGit(tags={"13.34.0": True}, remotes={"14.0.0": True})
    gate = _gate(git)

    assert gate.liberada("13.34.0") is True
    # branch remota nao e liberacao: e so trabalho compartilhado
    assert gate.liberada("14.0.0") is False
    assert gate.publicada("14.0.0") is True
