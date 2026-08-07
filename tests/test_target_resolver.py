from __future__ import annotations

import datetime

import pytest

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import CommitRef
from motor.errors import MotorError
from motor.services.target_resolver import TargetResolver


def _commit(hash_: str, chamado: str) -> CommitRef:
    return CommitRef(
        hash_origem=hash_, chamado=chamado, commit_date=datetime.datetime(2026, 1, 1)
    )


def test_resolve_une_as_versoes_abertas_menores_ou_iguais():
    # Cenario da spec §2 passo 2: ch123123 marcada p/ 13.33.1 cai na 14.0.0.
    tasks = FakeTaskSource(chamados={"13.33.1": ["123123"], "13.34.0": ["123456"],
                                     "14.0.0": []})
    commits = FakeCommitSource(por_chamado={
        "123123": [_commit("aaa", "123123")],
        "123456": [_commit("bbb", "123456")],
    })
    resolver = TargetResolver(tasks=tasks, commits=commits)

    alvo = resolver.resolve("14.0.0", ["13.33.1", "13.34.0", "14.0.0"])

    assert set(alvo.tasks) == {"123123", "123456"}
    assert alvo.tasks["123123"].marcada == "13.33.1"
    assert alvo.tasks["123456"].marcada == "13.34.0"
    assert alvo.ambiguas == []


def test_resolve_ignora_versao_aberta_maior_que_o_alvo():
    tasks = FakeTaskSource(chamados={"13.33.1": ["123123"], "14.1.0": ["999111"]})
    commits = FakeCommitSource(por_chamado={"123123": [_commit("aaa", "123123")]})
    resolver = TargetResolver(tasks=tasks, commits=commits)

    alvo = resolver.resolve("13.33.1", ["13.33.1", "14.1.0"])

    assert set(alvo.tasks) == {"123123"}


def test_resolve_mantem_chamado_sem_commit_no_alvo():
    # Falso-verde: tarefa marcada sem nenhum commit tem que sobreviver ao alvo
    # para o verificar poder pinta-la vermelha.
    tasks = FakeTaskSource(chamados={"13.34.0": ["123456"]})
    resolver = TargetResolver(tasks=tasks, commits=FakeCommitSource())

    alvo = resolver.resolve("13.34.0", ["13.34.0"])

    assert alvo.tasks["123456"].commits == []


def test_resolve_reporta_chamado_marcado_em_duas_versoes():
    tasks = FakeTaskSource(chamados={"13.33.1": ["123123"], "13.34.0": ["123123"]})
    commits = FakeCommitSource(por_chamado={"123123": [_commit("aaa", "123123")]})
    resolver = TargetResolver(tasks=tasks, commits=commits)

    alvo = resolver.resolve("13.34.0", ["13.33.1", "13.34.0"])

    assert alvo.ambiguas == ["123123"]


def test_resolve_nao_reporta_ambiguidade_por_repeticao_na_mesma_versao():
    tasks = FakeTaskSource(chamados={"13.34.0": ["123123", "123123"]})
    commits = FakeCommitSource(por_chamado={"123123": [_commit("aaa", "123123")]})
    resolver = TargetResolver(tasks=tasks, commits=commits)

    alvo = resolver.resolve("13.34.0", ["13.34.0"])

    assert alvo.ambiguas == []


def test_resolve_propaga_erro_da_fonte_como_motorerror():
    tasks = FakeTaskSource(err=RuntimeError("timeout"))
    resolver = TargetResolver(tasks=tasks, commits=FakeCommitSource())

    with pytest.raises(MotorError, match="buscando tasks"):
        resolver.resolve("13.34.0", ["13.34.0"])
