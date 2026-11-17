"""O cenário das jornadas da web produz, com git de verdade, o estado de cada papel."""

from __future__ import annotations

import pytest

from motor.engine.atualizar import AtualizarStatus
from motor.operacoes import (
    RepoOption,
    atualizar_repo,
    orfaos_repo,
    repos_do_ambiente,
    verificar_repo,
)
from tests.e2e.cenario import Manifesto, PapelVersao, montar


def _aplicar(manifesto: Manifesto, monkeypatch) -> Manifesto:
    for nome, valor in manifesto.ambiente.items():
        monkeypatch.setenv(nome, valor)
    return manifesto


@pytest.fixture(scope="module")
def _cenario_compartilhado(tmp_path_factory) -> Manifesto:
    """Um cenário para os testes que só consultam: no Windows, montar custa ~12 s."""
    return montar(tmp_path_factory.mktemp("cenario") / "cenario")


@pytest.fixture
def cenario(_cenario_compartilhado, monkeypatch) -> Manifesto:
    return _aplicar(_cenario_compartilhado, monkeypatch)


@pytest.fixture
def cenario_proprio(tmp_path, monkeypatch) -> Manifesto:
    """Para quem muda o que o teste seguinte veria: o clone, ou o estado de outro
    jeito que não a gravação idempotente do `verificar`."""
    return _aplicar(montar(tmp_path / "cenario"), monkeypatch)


def _repo(manifesto: Manifesto) -> RepoOption:
    return next(r for r in repos_do_ambiente() if r.nome == manifesto.repo)


# (verde, liberada, papéis cujo chamado falta, papéis cujo chamado conflita)
_ESPERADO = {
    PapelVersao.LIBERADA: (True, True, set(), set()),
    PapelVersao.VERDE: (True, False, set(), set()),
    PapelVersao.FALTANTES: (False, False, {PapelVersao.FALTANTES}, set()),
    PapelVersao.CONFLITO: (
        False,
        False,
        {PapelVersao.CONFLITO},
        {PapelVersao.CONFLITO},
    ),
    PapelVersao.VAZIO: (False, False, {PapelVersao.VAZIO}, set()),
    PapelVersao.ORFAO: (True, False, set(), set()),
}


@pytest.mark.parametrize("papel", list(PapelVersao))
def test_verificar_devolve_o_estado_do_papel(cenario, papel):
    status = verificar_repo(_repo(cenario), cenario.versoes[papel], False)

    verde, liberada, faltam, conflitam = _ESPERADO[papel]
    assert status.verde is verde
    assert (status.liberada_em is not None) is liberada
    assert {c.chamado for c in status.faltantes} == {
        cenario.chamados[p] for p in faltam
    }
    assert {c.chamado for c in status.conflitantes} == {
        cenario.chamados[p] for p in conflitam
    }


def test_atualizar_trava_no_conflito_e_fecha_o_pick_vazio(cenario_proprio):
    repo = _repo(cenario_proprio)

    bloqueado = atualizar_repo(repo, cenario_proprio.versoes[PapelVersao.CONFLITO])
    vazio = atualizar_repo(repo, cenario_proprio.versoes[PapelVersao.VAZIO])

    assert bloqueado.status == AtualizarStatus.BLOCKED
    assert cenario_proprio.arquivo_conflito in bloqueado.arquivos_conflito
    assert vazio.status == AtualizarStatus.DONE
    assert [c.chamado for c in vazio.vazios] == [
        cenario_proprio.chamados[PapelVersao.VAZIO]
    ]
    assert vazio.aplicados == []


def test_orfao_aparece_na_lista_da_versao(cenario):
    orfaos = orfaos_repo(_repo(cenario), cenario.versoes[PapelVersao.ORFAO])

    assert len(orfaos) == 1
    assert orfaos[0].julgamento is None


def test_repo_sem_checkout_fica_indisponivel(cenario):
    repos = {r.nome: r for r in repos_do_ambiente()}

    assert repos[cenario.repo].disponivel
    assert not repos[cenario.repo_sem_checkout].disponivel
