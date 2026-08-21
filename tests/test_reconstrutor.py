"""Sucessor de tests/test_lock_store.py: a varredura de trailers saiu do
LockStore e virou services/reconstrutor.py. Sem estes testes o modulo novo
embarcaria sem cobertura, e os ramos de origem-sumida e de falha do git
continuariam descobertos mesmo depois de `reconstruir-estado` existir.
"""

from __future__ import annotations

import datetime

import pytest

from motor.adapters.git.fake import FakeGit
from motor.errors import MotorError
from motor.services.reconstrutor import extrair_trailer, reconstruir_atribuicoes

D = datetime.datetime(2026, 1, 1)


def _git(*mensagens: str) -> FakeGit:
    """`base` e a base da varredura; cada mensagem vira um commit acima dela.

    commits_in_range para em `base`, entao so os commits da branch sao varridos
    — e a ordem da varredura e do tip para tras (pN ... p1).
    """
    git = FakeGit()
    git.add_commit("base", "", "raiz", D)
    anterior = "base"
    for i, msg in enumerate(mensagens, start=1):
        git.add_commit(f"p{i}", anterior, msg, D)
        anterior = f"p{i}"
    git.set_branch("13.34.0", anterior)
    return git


def test_extrair_trailer():
    assert extrair_trailer("alfa\n\n(cherry picked from commit aaa)") == "aaa"
    assert extrair_trailer("sem trailer nenhum") is None
    # trailer truncado nao pode devolver o resto da mensagem como se fosse hash
    assert extrair_trailer("alfa\n\n(cherry picked from commit aaa") is None


def test_reagrupa_por_chamado_guardando_o_hash_de_origem():
    """Dois picks do mesmo chamado. Os hashes saem ordenados, nao na ordem da
    varredura (que e do tip para tras, logo zzz antes de aaa)."""
    git = _git(
        "ch123456 primeira\n\n(cherry picked from commit aaa)",
        "ch123456 segunda\n\n(cherry picked from commit zzz)",
    )
    git.add_commit("aaa", "", "ch123456 primeira", D)
    git.add_commit("zzz", "", "ch123456 segunda", D)

    atribuicoes, orfaos = reconstruir_atribuicoes(git, "base", "13.34.0")

    assert orfaos == []
    assert [a.chamado for a in atribuicoes] == ["123456"]
    # o hash de ORIGEM, nao o do pick: o pick e local desta branch
    assert atribuicoes[0].commits == ["aaa", "zzz"]
    assert atribuicoes[0].estado == "aplicado"
    # a varredura nao sabe para que versao o Tickio marcou a tarefa
    assert atribuicoes[0].marcada == ""


def test_commit_direto_na_branch_e_sua_propria_origem():
    git = _git("ch123456 alfa")

    atribuicoes, _ = reconstruir_atribuicoes(git, "base", "13.34.0")

    assert atribuicoes[0].commits == ["p1"]


def test_commit_sem_chamado_vira_orfao():
    git = _git("ajuste solto sem identificador")

    atribuicoes, orfaos = reconstruir_atribuicoes(git, "base", "13.34.0")

    assert atribuicoes == []
    assert orfaos == ["p1"]


def test_origem_que_sumiu_do_historico_e_ignorada():
    """O trailer aponta para um objeto que nao existe mais. Nao da para
    atribuir nem para chamar de orfao — o chamado do pick nao e confiavel,
    quem manda e a mensagem da origem."""
    git = _git("ch123456 alfa\n\n(cherry picked from commit desaparecido)")

    atribuicoes, orfaos = reconstruir_atribuicoes(git, "base", "13.34.0")

    assert atribuicoes == []
    assert orfaos == []


def test_falha_do_git_vira_erro_limpo():
    # O git ja levanta MotorError (adapters reclassificados nas tasks 3-6) - a
    # reconstrucao so agrega contexto via add_note, nao embrulha mais.
    git = _git("ch123456 alfa")
    git.commits_in_range_err = MotorError("git morreu")

    with pytest.raises(MotorError) as capturado:
        reconstruir_atribuicoes(git, "base", "13.34.0")

    assert "varrendo commits" in capturado.value.__notes__


def test_excecao_fora_do_contrato_propaga_sem_embrulho():
    git = _git("ch123456 alfa")
    git.commits_in_range_err = RuntimeError("git morreu de verdade")

    with pytest.raises(RuntimeError, match="git morreu de verdade"):
        reconstruir_atribuicoes(git, "base", "13.34.0")
