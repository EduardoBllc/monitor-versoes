"""ChainCommitSource: lista de fontes onde a ordem e a prioridade."""

from motor.adapters.commitsource.chain import ChainCommitSource
from motor.adapters.commitsource.fake import FakeCommitSource
from motor.domain.types import CommitRef, TaskTarget

TASKS = [
    TaskTarget(chamado="100", task="VB-1", titulo="A"),
    TaskTarget(chamado="200", task="VB-2", titulo="B"),
]


def test_primeira_fonte_com_commits_ganha_a_task():
    primaria = FakeCommitSource(por_chamado={"100": [CommitRef(hash_origem="pr-100")]})
    secundaria = FakeCommitSource(por_chamado={"100": [CommitRef(hash_origem="grep-100")]})

    chain = ChainCommitSource(sources=[primaria, secundaria])
    resultado = chain.resolve(TASKS)

    assert resultado["100"].commits[0].hash_origem == "pr-100", (
        f"primaria deveria ganhar: {resultado['100'].commits!r}"
    )


def test_cai_para_proxima_fonte_quando_primeira_nao_acha():
    primaria = FakeCommitSource(por_chamado={"100": [CommitRef(hash_origem="pr-100")]})
    secundaria = FakeCommitSource(por_chamado={"200": [CommitRef(hash_origem="grep-200")]})

    chain = ChainCommitSource(sources=[primaria, secundaria])
    resultado = chain.resolve(TASKS)

    assert resultado["100"].commits[0].hash_origem == "pr-100"
    assert resultado["200"].commits[0].hash_origem == "grep-200", (
        f"200 deveria cair pra secundaria: {resultado.get('200')!r}"
    )


def test_task_que_nenhuma_fonte_acha_fica_de_fora():
    chain = ChainCommitSource(sources=[FakeCommitSource(), FakeCommitSource()])
    resultado = chain.resolve(TASKS)

    assert resultado == {}, f"nenhuma fonte achou nada: {resultado!r}"
