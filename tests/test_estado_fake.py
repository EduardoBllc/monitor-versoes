from __future__ import annotations

import datetime

import pytest

from motor.adapters.estado.fake import FakeEstado
from motor.domain.types import Atribuicao, RepoInfo, VersaoInfo
from motor.errors import MotorError


def _info(numero: str, liberada=None) -> VersaoInfo:
    return VersaoInfo(
        numero=numero,
        tipo="ajustada",
        base_ref="13.33.0",
        base_commit="aaa",
        liberada_em=liberada,
    )


def test_substituir_atribuicoes_sobrescreve():
    estado = FakeEstado(repos={"r": RepoInfo(nome="r")})
    estado.registrar_versao("r", _info("13.34.0"))

    estado.substituir_atribuicoes(
        "r",
        "13.34.0",
        [
            Atribuicao(
                chamado="1", marcada="13.34.0", estado="pendente", commits=["a"]
            ),
        ],
    )
    estado.substituir_atribuicoes(
        "r",
        "13.34.0",
        [
            Atribuicao(
                chamado="2", marcada="13.34.0", estado="aplicado", commits=["b"]
            ),
        ],
    )

    assert [a.chamado for a in estado.atribuicoes("r", "13.34.0")] == ["2"]


def test_substituir_atribuicoes_recusa_versao_liberada():
    estado = FakeEstado(repos={"r": RepoInfo(nome="r")})
    estado.registrar_versao("r", _info("13.34.0"))
    estado.marcar_liberadas("r", {"13.34.0": datetime.datetime(2026, 8, 1)})

    with pytest.raises(MotorError, match="imutavel"):
        estado.substituir_atribuicoes("r", "13.34.0", [])


def test_substituir_atribuicoes_recusa_versao_nao_registrada():
    # Espelha a FK atribuicao.versao_id -> versao.id: sem registrar_versao
    # antes, o SQLite rejeitaria o insert. Mensagem distinta da versao
    # liberada, para nao confundir os dois motivos de recusa.
    estado = FakeEstado(repos={"r": RepoInfo(nome="r")})

    with pytest.raises(MotorError, match="nao registrada"):
        estado.substituir_atribuicoes("r", "13.34.0", [])


def test_marcar_liberadas_ignora_versao_que_nao_esta_no_estado():
    estado = FakeEstado(repos={"r": RepoInfo(nome="r")})
    estado.marcar_liberadas("r", {"9.9.9": datetime.datetime(2026, 8, 1)})
    assert estado.versao("r", "9.9.9") is None


def test_marcar_liberadas_nao_reescreve_data_ja_gravada():
    estado = FakeEstado(repos={"r": RepoInfo(nome="r")})
    estado.registrar_versao("r", _info("13.34.0"))
    # Com fuso: a coluna e timestamptz e o fake normaliza naive para UTC, entao
    # data naive aqui compararia contra a normalizada e o teste falaria de fuso
    # em vez de falar de sobrescrita. O fuso tem contrato proprio, em
    # tests/test_estado_contrato.py.
    primeira = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    estado.marcar_liberadas("r", {"13.34.0": primeira})
    estado.marcar_liberadas(
        "r", {"13.34.0": datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)}
    )
    gravada = estado.versao("r", "13.34.0")
    assert gravada is not None
    assert gravada.liberada_em == primeira


def test_registrar_versao_nao_sobrescreve_a_base_ja_gravada():
    # A base e gravada uma vez, na criacao. Recomputar faria a base de uma
    # X.0.0 seguir o tip atual do master.
    estado = FakeEstado(repos={"r": RepoInfo(nome="r")})
    estado.registrar_versao("r", _info("14.0.0"))
    estado.registrar_versao(
        "r",
        VersaoInfo(
            numero="14.0.0",
            tipo="fechada",
            base_ref="master",
            base_commit="OUTRO",
        ),
    )
    gravada = estado.versao("r", "14.0.0")
    assert gravada is not None
    assert gravada.base_commit == "aaa"
