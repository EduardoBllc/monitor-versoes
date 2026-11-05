"""Os esquemas embutidos passam pela suite publicada, e ela reprova o relogio."""

import datetime

import pytest

from motor.conformidade import ConformidadeEsquema, verificar_liberacoes
from motor.esquemas.semver import Semver
from motor.esquemas.vendabem import VendaBem
from motor.ports import EsquemaVersao, GitRepo

_EXEMPLOS = ["1.0.0", "1.1.0", "1.1.1", "2.0.0"]


class TestSemver(ConformidadeEsquema):
    esquema_cls = Semver
    exemplos = _EXEMPLOS


class TestVendaBem(ConformidadeEsquema):
    esquema_cls = VendaBem
    exemplos = _EXEMPLOS


class EsquemaDoRelogio(Semver):
    """Libera tudo na hora em que perguntam: o defeito que a suite existe para pegar."""

    def liberacoes(
        self, git: GitRepo, versoes: list[str], /
    ) -> dict[str, datetime.datetime] | None:
        return dict.fromkeys(versoes, datetime.datetime.now(datetime.UTC))


def test_conformidade_reprova_data_de_liberacao_vinda_do_relogio():
    esquema: EsquemaVersao = EsquemaDoRelogio()

    with pytest.raises(AssertionError):
        verificar_liberacoes(esquema, _EXEMPLOS)
