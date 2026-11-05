from __future__ import annotations

import datetime

import pytest

from motor.domain.inscricao import (
    Desfecho,
    Evento,
    Resultado,
    TipoEvento,
    TipoVermelho,
    UltimaExecucao,
    consolidar,
    eventos,
    vermelhos_de,
)
from motor.domain.types import CommitRef, VersionStatus

HORA = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC)
AMBIGUA = f"{TipoVermelho.AMBIGUA}:100"
SUMIDO = f"{TipoVermelho.SUMIDO}:abc"
CONFLITANTE = f"{TipoVermelho.CONFLITANTE}:def"
SEM_COMMITS = f"{TipoVermelho.SEM_COMMITS}:200"


def _ultima(
    desfecho: Desfecho, vermelhos: frozenset[str] = frozenset()
) -> UltimaExecucao:
    return UltimaExecucao(HORA, desfecho, desfecho, vermelhos)


@pytest.mark.parametrize(
    ("anterior", "resultado", "esperado"),
    [
        pytest.param(
            None,
            Resultado(Desfecho.NADA, vermelhos=frozenset({AMBIGUA, SUMIDO})),
            [(TipoEvento.NOVO_VERMELHO, [AMBIGUA, SUMIDO])],
            id="primeira_execucao_todos_novos",
        ),
        pytest.param(
            _ultima(Desfecho.NADA),
            Resultado(
                Desfecho.APLICOU,
                vermelhos=frozenset(),
                chamados_aplicados=("1", "2"),
                n_aplicados=3,
            ),
            [(TipoEvento.APLICOU, ["3", "1", "2"])],
            id="aplicou",
        ),
        pytest.param(
            _ultima(Desfecho.NADA),
            Resultado(
                Desfecho.BLOQUEADA,
                vermelhos=frozenset(),
                commit_bloqueado="abc123",
                arquivos=("a.py",),
                culpados=("77",),
            ),
            [(TipoEvento.BLOQUEOU, ["abc123", "a.py", "77"])],
            id="bloqueada_com_culpados",
        ),
        pytest.param(
            _ultima(Desfecho.NADA),
            Resultado(Desfecho.ERRO, mensagem="falhou"),
            [(TipoEvento.ERRO, ["falhou"])],
            id="erro_apos_nada_avisa",
        ),
        pytest.param(
            _ultima(Desfecho.ERRO),
            Resultado(Desfecho.ERRO, mensagem="falhou"),
            [],
            id="erro_apos_erro_nao_avisa",
        ),
        pytest.param(
            _ultima(Desfecho.NADA),
            Resultado(Desfecho.PULADA),
            [],
            id="pulada",
        ),
        pytest.param(
            _ultima(Desfecho.NADA),
            Resultado(Desfecho.ENCERRADA),
            [(TipoEvento.ENCERRADA, [])],
            id="encerrada",
        ),
        pytest.param(
            _ultima(Desfecho.NADA, frozenset({AMBIGUA})),
            Resultado(Desfecho.NADA, vermelhos=frozenset()),
            [],
            id="sai_do_vermelho",
        ),
        pytest.param(
            _ultima(Desfecho.NADA, frozenset({AMBIGUA})),
            Resultado(Desfecho.NADA, vermelhos=frozenset({AMBIGUA, SEM_COMMITS})),
            [(TipoEvento.NOVO_VERMELHO, [SEM_COMMITS])],
            id="so_o_novo_vermelho",
        ),
    ],
)
def test_eventos(
    anterior: UltimaExecucao | None,
    resultado: Resultado,
    esperado: list[tuple[TipoEvento, list[str]]],
):
    obtidos = eventos(anterior, resultado)

    assert [e.tipo for e in obtidos] == [t for t, _ in esperado]
    for evento, (_, trechos) in zip(obtidos, esperado, strict=True):
        assert all(t in evento.detalhe for t in trechos)


def test_erro_pulada_erro_avisa_uma_vez():
    erro = Resultado(Desfecho.ERRO, mensagem="falhou")
    a1 = consolidar(None, erro, HORA)
    a2 = consolidar(a1, Resultado(Desfecho.PULADA), HORA)

    assert eventos(None, erro) == [Evento(TipoEvento.ERRO, "falhou")]
    assert eventos(a2, erro) == []


def test_consolidar_herda_vermelhos_em_pulada_e_erro():
    base = _ultima(Desfecho.NADA, frozenset({AMBIGUA}))

    pulada = consolidar(base, Resultado(Desfecho.PULADA), HORA)
    erro = consolidar(pulada, Resultado(Desfecho.ERRO, mensagem="x"), HORA)

    assert pulada.vermelhos == base.vermelhos
    assert pulada.desfecho == Desfecho.PULADA
    assert pulada.desfecho_aviso == Desfecho.NADA
    assert erro.vermelhos == base.vermelhos
    assert erro.desfecho_aviso == Desfecho.ERRO
    assert erro.mensagem == "x"
    assert consolidar(None, Resultado(Desfecho.PULADA), HORA).vermelhos == frozenset()


def test_vermelhos_de_ignora_suspeitos():
    status = VersionStatus(
        tasks_ambiguas=["100"],
        tasks_sem_commits=["200"],
        commits_sumidos=["abc"],
        conflitantes=[CommitRef(hash_origem="def")],
        suspeitos_conteudo=[CommitRef(hash_origem="zzz")],
    )

    assert vermelhos_de(status) == {AMBIGUA, SEM_COMMITS, SUMIDO, CONFLITANTE}
