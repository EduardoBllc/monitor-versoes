from __future__ import annotations

import datetime
import json
from enum import StrEnum
from pathlib import Path

import pytest

from motor.adapters.notificador.fake import FakeNotificador
from motor.domain.inscricao import Desfecho, Resultado, UltimaExecucao
from motor.errors import ErroDeEntrada, RespostaInvalida
from motor.inscricoes import (
    Inscricao,
    carregar,
    disparar_subprocesso,
    inscrever,
    parse_intervalo,
    registrar_execucao,
    remover,
    rodar,
    salvar,
    vencidas,
)

HORA = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC)
TITULO = "monitor-versoes 1.0"
MIN30 = datetime.timedelta(minutes=30)


class Repo(StrEnum):
    A = "/repo/a"
    B = "/repo/b"


class Versao(StrEnum):
    V1 = "1.0"
    V2 = "2.0"


class Ambiente(StrEnum):
    DEV = "development"


def _insc(
    clone: str = Repo.A,
    versao: str = Versao.V1,
    intervalo: datetime.timedelta = MIN30,
    ultima: UltimaExecucao | None = None,
    diretorio: str = "/tmp",
) -> Inscricao:
    return Inscricao(clone, versao, intervalo, diretorio, Ambiente.DEV, ultima)


def _ultima(hora: datetime.datetime = HORA) -> UltimaExecucao:
    return UltimaExecucao(
        hora, Desfecho.APLICOU, Desfecho.BLOQUEADA, frozenset({"sumido:abc"}), "m"
    )


@pytest.fixture
def arq(tmp_path: Path) -> Path:
    return tmp_path / "sub" / "inscricoes.json"


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("30m", datetime.timedelta(minutes=30)),
        ("2h", datetime.timedelta(hours=2)),
    ],
)
def test_parse_intervalo(texto: str, esperado: datetime.timedelta) -> None:
    assert parse_intervalo(texto) == esperado


@pytest.mark.parametrize("texto", ["0m", "5s", "m", "-1h", "", "05m"])
def test_parse_intervalo_invalido(texto: str) -> None:
    with pytest.raises(ErroDeEntrada):
        parse_intervalo(texto)


def test_ida_e_volta_do_arquivo(arq: Path) -> None:
    lista = [_insc(ultima=_ultima()), _insc(Repo.B, Versao.V2)]
    salvar(arq, lista)
    assert carregar(arq) == lista


def test_arquivo_ausente_da_lista_vazia(arq: Path) -> None:
    assert carregar(arq) == []


@pytest.mark.parametrize("conteudo", ["{nao e json", "[{}]", '{"a": 1}'])
def test_arquivo_corrompido_da_resposta_invalida(arq: Path, conteudo: str) -> None:
    arq.parent.mkdir(parents=True)
    arq.write_text(conteudo)
    with pytest.raises(RespostaInvalida, match=str(arq)):
        carregar(arq)
    assert arq.read_text() == conteudo


def test_campo_com_tipo_errado_da_resposta_invalida(arq: Path) -> None:
    salvar(arq, [_insc(ultima=_ultima())])
    dados = json.loads(arq.read_text())
    dados[0]["ultima"]["hora"] = "ontem"
    arq.write_text(json.dumps(dados))
    with pytest.raises(RespostaInvalida, match=str(arq)):
        carregar(arq)


def test_reinscrever_troca_so_intervalo(arq: Path) -> None:
    salvar(arq, [_insc(ultima=_ultima())])
    horas = datetime.timedelta(hours=1)
    inscrever(arq, _insc(intervalo=horas, diretorio="/outro"))
    (unica,) = carregar(arq)
    assert unica.intervalo == horas
    assert unica.ultima == _ultima()
    assert unica.diretorio == "/tmp"


def test_inscrever_nova_acrescenta(arq: Path) -> None:
    inscrever(arq, _insc())
    inscrever(arq, _insc(Repo.B))
    assert len(carregar(arq)) == 2


def test_remover_inexistente_da_erro_de_entrada(arq: Path) -> None:
    with pytest.raises(ErroDeEntrada):
        remover(arq, Repo.A, Versao.V1)


def test_remover_tira_so_a_escolhida(arq: Path) -> None:
    salvar(arq, [_insc(), _insc(Repo.B)])
    remover(arq, Repo.A, Versao.V1)
    assert [i.clone for i in carregar(arq)] == [Repo.B]


def test_vencidas() -> None:
    nunca = _insc(Repo.A)
    no_limite = _insc(Repo.B, ultima=_ultima(HORA - MIN30))
    recente = _insc(Repo.B, Versao.V2, ultima=_ultima(HORA - MIN30 / 2))
    assert vencidas([nunca, no_limite, recente], HORA) == [nunca, no_limite]


def test_registrar_notifica_e_grava(arq: Path) -> None:
    salvar(arq, [_insc()])
    fake = FakeNotificador()
    r = Resultado(Desfecho.APLICOU, n_aplicados=2, chamados_aplicados=("100",))
    registrar_execucao(arq, Repo.A, Versao.V1, r, fake, HORA, TITULO)
    (unica,) = carregar(arq)
    assert unica.ultima is not None
    assert unica.ultima.desfecho == Desfecho.APLICOU
    assert unica.ultima.hora == HORA
    (titulo, corpo) = fake.enviadas[0]
    assert titulo == TITULO
    assert "100" in corpo


def test_falha_do_notificador_nao_impede_gravacao(arq: Path) -> None:
    salvar(arq, [_insc()])
    r = Resultado(Desfecho.APLICOU, n_aplicados=1, chamados_aplicados=("1",))
    registrar_execucao(
        arq, Repo.A, Versao.V1, r, FakeNotificador(falhar=True), HORA, TITULO
    )
    (unica,) = carregar(arq)
    assert unica.ultima is not None


def test_encerrada_sai_do_arquivo(arq: Path) -> None:
    salvar(arq, [_insc(), _insc(Repo.B)])
    fake = FakeNotificador()
    registrar_execucao(
        arq, Repo.A, Versao.V1, Resultado(Desfecho.ENCERRADA), fake, HORA, TITULO
    )
    assert [i.clone for i in carregar(arq)] == [Repo.B]
    assert len(fake.enviadas) == 1


def test_registrar_de_inscricao_removida_nao_recria(arq: Path) -> None:
    salvar(arq, [_insc(Repo.B)])
    fake = FakeNotificador()
    registrar_execucao(
        arq, Repo.A, Versao.V1, Resultado(Desfecho.NADA), fake, HORA, TITULO
    )
    assert [i.clone for i in carregar(arq)] == [Repo.B]


def test_rodar_falha_de_um_nao_para_os_outros_e_grava_erro(arq: Path) -> None:
    salvar(arq, [_insc(Repo.A), _insc(Repo.B)])
    fake = FakeNotificador()
    chamadas: list[str] = []

    def disparar(i: Inscricao) -> int:
        chamadas.append(i.clone)
        if i.clone == Repo.A:
            return -1
        registrar_execucao(
            arq, i.clone, i.versao, Resultado(Desfecho.NADA), fake, HORA, TITULO
        )
        return 0

    rodar(arq, HORA, disparar, fake)
    assert chamadas == [Repo.A, Repo.B]
    a, b = carregar(arq)
    assert a.ultima is not None
    assert a.ultima.desfecho == Desfecho.ERRO
    assert a.ultima.mensagem == "execução terminou com código -1 sem gravar resultado"
    assert b.ultima is not None
    assert b.ultima.desfecho == Desfecho.NADA


def test_rodar_inscricao_removida_pelo_filho_nao_e_recriada(arq: Path) -> None:
    salvar(arq, [_insc()])

    def disparar(i: Inscricao) -> int:
        salvar(arq, [])
        return 0

    rodar(arq, HORA, disparar, FakeNotificador())
    assert carregar(arq) == []


def test_disparar_subprocesso_diretorio_sumido_devolve_menos_um(
    tmp_path: Path,
) -> None:
    assert disparar_subprocesso(_insc(diretorio=str(tmp_path / "nao-existe"))) == -1
