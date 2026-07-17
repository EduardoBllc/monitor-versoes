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


def test_presence_oracle_suspeita_por_conteudo_match_msg_e_arquivos():
    """Cherry-pick manual sem -x que altera o conteudo na resolucao do
    conflito muda o patch-id (nivel 3 nao pega) mas preserva a mensagem - o
    nivel 4 (fora do oraculo formal) deve achar o match por mensagem+arquivos.
    """
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("base-tip", "", "base", t0)
    g.add_commit("alvo1", "base-tip", "fix: ch255514 corrige logs", t0)  # cherry-pick manual, conteudo divergente
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "alvo1")
    g.file_changes["origem1"] = frozenset({"a.txt"})
    g.file_changes["alvo1"] = frozenset({"a.txt"})

    oracle = PresenceOracle(git=g)
    assert oracle.presente("origem1", "13.6.0", "13.7.0") == Presence.AUSENTE

    suspeita = oracle.suspeita_por_conteudo("origem1", "13.6.0", "13.7.0")

    assert suspeita is not None and suspeita.hash_origem == "alvo1", f"suspeita = {suspeita!r}"


def test_presence_oracle_suspeita_por_conteudo_arquivos_diferentes_nao_bate():
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ch255514 corrige logs", t0)
    g.add_commit("base-tip", "", "base", t0)
    g.add_commit("alvo1", "base-tip", "fix: ch255514 corrige logs", t0)
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "alvo1")
    g.file_changes["origem1"] = frozenset({"a.txt"})
    g.file_changes["alvo1"] = frozenset({"b.txt"})  # mensagem igual, arquivo diferente - nao e a mesma entrega

    oracle = PresenceOracle(git=g)
    suspeita = oracle.suspeita_por_conteudo("origem1", "13.6.0", "13.7.0")

    assert suspeita is None, f"suspeita = {suspeita!r}, esperava None (arquivos divergem)"


def test_presence_oracle_suspeita_por_conteudo_consumo_evita_colisao_duplicata():
    """Msg duplicada dentro da mesma PR e comum (ex.: 'fix lint' repetido) -
    o match tem que consumir o candidato usado, senao o segundo commit de
    origem colidiria com o mesmo alvo ja usado pelo primeiro.
    """
    g = FakeGit()
    t0 = datetime.datetime.now(datetime.timezone.utc)
    g.add_commit("origem1", "", "fix: ajuste", t0)
    g.add_commit("origem2", "origem1", "fix: ajuste", t0)  # mesma msg, arquivos diferentes
    g.add_commit("base-tip", "", "base", t0)
    g.add_commit("alvo1", "base-tip", "fix: ajuste", t0)
    g.set_branch("13.6.0", "base-tip")
    g.set_branch("13.7.0", "alvo1")
    g.file_changes["origem1"] = frozenset({"a.txt"})
    g.file_changes["origem2"] = frozenset({"a.txt"})
    g.file_changes["alvo1"] = frozenset({"a.txt"})  # so 1 candidato no alvo pras 2 origens

    oracle = PresenceOracle(git=g)
    primeira = oracle.suspeita_por_conteudo("origem1", "13.6.0", "13.7.0")
    segunda = oracle.suspeita_por_conteudo("origem2", "13.6.0", "13.7.0")

    assert primeira is not None and primeira.hash_origem == "alvo1"
    assert segunda is None, f"segunda = {segunda!r}, esperava None (candidato ja consumido)"


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
