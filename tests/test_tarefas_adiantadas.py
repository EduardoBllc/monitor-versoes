from __future__ import annotations

import threading
from concurrent.futures import Future
from dataclasses import dataclass, field

import pytest

from motor.errors import BackendIndisponivel
from motor.services.tarefas_adiantadas import TarefasAdiantadas

ALVO = "17.0.0"
OUTRA = "16.9.0"


@dataclass
class _FonteContadora:
    chamadas: list[str] = field(default_factory=list)
    adiantada: Future[list[str]] | None = None
    # adiantada.done() no instante de cada chamada
    adiantada_terminada: list[bool] = field(default_factory=list)

    def fetch(self, versao: str, /) -> list[str]:
        self.chamadas.append(versao)
        if self.adiantada is not None:
            self.adiantada_terminada.append(self.adiantada.done())
        return [f"ch-{versao}"]


def test_alvo_vem_do_adiantado_sem_chamar_a_fonte():
    fonte = _FonteContadora()
    adiantada: Future[list[str]] = Future()
    adiantada.set_result(["123"])

    assert TarefasAdiantadas(fonte, ALVO, adiantada).fetch(ALVO) == ["123"]
    assert fonte.chamadas == []


def test_outra_versao_espera_o_adiantado_e_usa_a_fonte():
    adiantada: Future[list[str]] = Future()
    fonte = _FonteContadora(adiantada=adiantada)
    threading.Timer(0.05, adiantada.set_result, args=(["123"],)).start()

    resultado = TarefasAdiantadas(fonte, ALVO, adiantada).fetch(OUTRA)

    # a fonte nao e thread-safe: so pode ser chamada com o adiantado terminado
    assert fonte.adiantada_terminada == [True]
    assert resultado == [f"ch-{OUTRA}"]
    assert fonte.chamadas == [OUTRA]


def test_erro_do_adiantado_sai_na_posicao_do_alvo():
    adiantada: Future[list[str]] = Future()
    adiantada.set_exception(BackendIndisponivel("fora do ar"))
    tarefas = TarefasAdiantadas(_FonteContadora(), ALVO, adiantada)

    assert tarefas.fetch(OUTRA) == [f"ch-{OUTRA}"]
    with pytest.raises(BackendIndisponivel):
        tarefas.fetch(ALVO)
