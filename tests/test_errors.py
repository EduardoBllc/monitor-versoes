"""Hierarquia de erro: a promessa de que a migracao e aditiva.

Toda subclasse herda de MotorError, entao `except MotorError` continua pegando
tudo. Sem este teste, alguem introduz uma classe irma por engano e todo
`except MotorError` do projeto passa a deixar passar um caso.
"""

from __future__ import annotations

import pytest

from motor.errors import (
    BackendIndisponivel,
    ErroDeEntrada,
    MotorError,
    NaoEncontrado,
    RecusaDeInvariante,
    RespostaInvalida,
)

_SUBCLASSES = [
    RecusaDeInvariante,
    NaoEncontrado,
    BackendIndisponivel,
    RespostaInvalida,
    ErroDeEntrada,
]


@pytest.mark.parametrize("classe", _SUBCLASSES)
def test_toda_subclasse_e_capturada_como_motorerror(classe):
    # E o que faz a migracao ser aditiva: nenhum `except MotorError` existente
    # muda de comportamento ao reclassificarmos os 64 raises.
    with pytest.raises(MotorError):
        raise classe("mensagem")


@pytest.mark.parametrize("classe", _SUBCLASSES)
def test_toda_subclasse_preserva_a_mensagem(classe):
    assert str(classe("mensagem")) == "mensagem"


def test_as_subclasses_nao_se_capturam_entre_si():
    # RecusaDeInvariante x NaoEncontrado e a distincao que a suite de contrato
    # precisa fazer por tipo. Se uma herdasse da outra, o teste passaria por
    # vazio.
    with pytest.raises(NaoEncontrado):
        try:
            raise NaoEncontrado("nao achei")
        except RecusaDeInvariante:  # pragma: no cover - nao deve capturar
            pytest.fail("NaoEncontrado nao pode ser RecusaDeInvariante")


def test_add_note_sobrevive_ao_reraise():
    """Base da decisao da secao 5.1 da spec: os services agregam contexto com
    add_note e re-levantam, em vez de embrulhar em MotorError puro. Se
    add_note nao preservasse o tipo, a taxonomia morreria na primeira fronteira.
    """
    with pytest.raises(BackendIndisponivel) as capturado:
        try:
            raise BackendIndisponivel("Tickio fora do ar")
        except MotorError as e:
            e.add_note("buscando tasks da versao 13.34.0")
            raise

    assert capturado.value.__notes__ == ["buscando tasks da versao 13.34.0"]
