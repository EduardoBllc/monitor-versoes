from __future__ import annotations

import datetime

import pytest

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import CommitRef
from motor.errors import BackendIndisponivel, MotorError
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


@pytest.mark.parametrize(
    "chamados, abertas, esperado",
    [
        pytest.param(
            {"13.34.0": ["123123", "123123"]},
            ["13.34.0"],
            [],
            id="repeticao_na_mesma_versao_nao_e_ambiguidade",
        ),
        pytest.param(
            {"13.33.1": ["123123"], "13.34.0": ["123123"]},
            ["13.33.1", "13.34.0"],
            ["123123"],
            id="marcado_em_duas_versoes_e_ambiguidade",
        ),
    ],
)
def test_resolve_ambiguidade_so_entre_versoes_diferentes(chamados, abertas, esperado):
    # As duas variacoes tem que conviver no mesmo teste: repeticao dentro do
    # fetch de uma versao e dedup (nao ambiguidade), repeticao entre fetches
    # de versoes diferentes e ambiguidade. Separadas em dois testes, cada um
    # so prova metade da regra e a outra metade pode sumir sem quebrar nada.
    tasks = FakeTaskSource(chamados=chamados)
    commits = FakeCommitSource(por_chamado={"123123": [_commit("aaa", "123123")]})
    resolver = TargetResolver(tasks=tasks, commits=commits)

    alvo = resolver.resolve("13.34.0", abertas)

    assert alvo.ambiguas == esperado


def test_resolve_propaga_erro_da_fonte_como_motorerror():
    # A fonte ja levanta MotorError (adapters reclassificados nas tasks 3-6) -
    # o resolver so agrega contexto via add_note, nao embrulha mais.
    tasks = FakeTaskSource(err=MotorError("timeout"))
    resolver = TargetResolver(tasks=tasks, commits=FakeCommitSource())

    with pytest.raises(MotorError) as capturado:
        resolver.resolve("13.34.0", ["13.34.0"])

    assert "buscando tasks da versao 13.34.0" in capturado.value.__notes__


def test_o_tipo_do_adapter_sobrevive_a_fronteira_do_resolver():
    """Embrulhar em MotorError puro achatava a subclasse exatamente onde o
    chamador precisa dela: distinguir "o Tickio esta fora" de "o Tickio
    respondeu lixo".
    """

    class _TickioFora:
        def fetch(self, versao: str, /) -> list[str]:
            raise BackendIndisponivel("Tickio respondeu 503")

    resolver = TargetResolver(tasks=_TickioFora(), commits=FakeCommitSource())

    with pytest.raises(BackendIndisponivel) as capturado:
        resolver.resolve("13.34.0", ["13.34.0"])

    # o contexto continua chegando ao operador, agora como nota
    assert "buscando tasks da versao 13.34.0" in capturado.value.__notes__


def test_excecao_fora_do_contrato_propaga_sem_embrulho():
    class _TickioComBug:
        def fetch(self, versao: str, /) -> list[str]:
            raise RuntimeError("bug no adapter")

    resolver = TargetResolver(tasks=_TickioComBug(), commits=FakeCommitSource())

    with pytest.raises(RuntimeError, match="bug no adapter"):
        resolver.resolve("13.34.0", ["13.34.0"])


def test_nota_de_buscando_commits_das_tasks_tambem_preserva_o_tipo():
    """O segundo site de add_note deste arquivo (linha 59) nao tinha teste
    nenhum: FakeCommitSource(err=...) nunca era usado na suite.
    """
    tasks = FakeTaskSource(chamados={"13.34.0": ["123456"]})
    commits = FakeCommitSource(err=BackendIndisponivel("Bitbucket fora do ar"))
    resolver = TargetResolver(tasks=tasks, commits=commits)

    with pytest.raises(BackendIndisponivel) as capturado:
        resolver.resolve("13.34.0", ["13.34.0"])

    assert "buscando commits das tasks" in capturado.value.__notes__
