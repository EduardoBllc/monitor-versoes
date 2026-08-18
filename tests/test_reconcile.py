from __future__ import annotations

from motor.domain.reconcile import (
    atribuicoes_de,
    diff_tasks,
    filtrar_excluidos,
    reconciliar,
)
from motor.domain.types import (
    Alvo,
    Atribuicao,
    CommitRef,
    Exclusion,
    Presence,
    TaskTarget,
)


def _alvo(**tasks) -> dict:
    return {
        ch: TaskTarget(chamado=ch, marcada="13.34.0",
                       commits=[CommitRef(hash_origem=h, chamado=ch) for h in hashes])
        for ch, hashes in tasks.items()
    }


def test_filtrar_excluidos_remove_exclusao_global_e_da_versao():
    alvo = _alvo(**{"1": ["aaa", "bbb", "ccc"]})
    excluidos = [
        Exclusion(hash_origem="aaa", versao_numero=None, motivo="revertido"),
        Exclusion(hash_origem="bbb", versao_numero="13.34.0", motivo="nao se aplica"),
        Exclusion(hash_origem="ccc", versao_numero="14.0.0", motivo="outra versao"),
    ]

    filtrado = filtrar_excluidos(alvo, excluidos, "13.34.0")

    assert [c.hash_origem for c in filtrado["1"].commits] == ["ccc"]


def test_diff_tasks_acusa_nova_e_removida():
    alvo = _alvo(**{"1": ["aaa"], "2": ["bbb"]})
    anteriores = [
        Atribuicao(chamado="2", marcada="13.34.0", estado="aplicado", commits=["bbb"]),
        Atribuicao(chamado="3", marcada="13.34.0", estado="aplicado", commits=["ccc"]),
    ]

    novas, removidas = diff_tasks(alvo, anteriores)

    assert novas == ["1"]
    assert removidas == ["3"]


def test_reconciliar_verde_quando_tudo_bate():
    alvo = Alvo(tasks=_alvo(**{"1": ["aaa"]}))
    anteriores = [
        Atribuicao(chamado="1", marcada="13.34.0", estado="aplicado", commits=["aaa"])
    ]
    status = reconciliar(alvo, anteriores, {}, {"aaa": Presence.TRAILER}, [], [])

    assert status.verde is True
    assert status.faltantes == []


def test_reconciliar_nao_fica_verde_com_tarefa_ambigua():
    alvo = Alvo(tasks=_alvo(**{"1": ["aaa"]}), ambiguas=["1"])
    anteriores = [
        Atribuicao(chamado="1", marcada="13.34.0", estado="aplicado", commits=["aaa"])
    ]
    status = reconciliar(alvo, anteriores, {}, {"aaa": Presence.TRAILER}, [], [])

    assert status.verde is False
    assert status.tasks_ambiguas == ["1"]


def test_reconciliar_acusa_tarefa_sem_commit_e_aceita_sem_entrega():
    alvo = Alvo(tasks=_alvo(**{"1": []}))
    assert reconciliar(alvo, [], {}, {}, [], []).tasks_sem_commits == ["1"]

    reconhecida = reconciliar(alvo, [], {"1": "so backend"}, {}, [], [])
    assert reconhecida.tasks_sem_commits == []


def test_reconciliar_acusa_commit_que_sumiu_do_git():
    alvo = Alvo(tasks=_alvo(**{"1": ["aaa"]}))
    anteriores = [
        Atribuicao(chamado="1", marcada="13.34.0", estado="aplicado",
                   commits=["aaa", "sumido"])
    ]
    status = reconciliar(alvo, anteriores, {}, {"aaa": Presence.TRAILER}, [], [])

    assert status.estado_integro is False
    assert status.commits_sumidos == ["sumido"]


def test_atribuicoes_de_marca_aplicado_so_quando_presente():
    alvo = _alvo(**{"1": ["aaa"], "2": ["bbb"]})
    presentes = {"aaa": Presence.TRAILER, "bbb": Presence.AUSENTE}

    por_chamado = {a.chamado: a for a in atribuicoes_de(alvo, presentes)}

    assert por_chamado["1"].estado == "aplicado"
    assert por_chamado["2"].estado == "pendente"
    assert por_chamado["1"].commits == ["aaa"]
