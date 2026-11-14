import threading
from pathlib import Path

from fastapi.testclient import TestClient

from motor.daemon.app import criar_app
from motor.daemon.disparo import laco, ligar_disparo
from motor.domain.types import VersionStatus
from motor.errors import RespostaInvalida
from motor.operacoes import Runners

PORTA = 8765
TIMEOUT_S = 5
SEM_INTERVALO_S = 0
RODADAS_ATE_PARAR = 2


def test_daemon_dispara_inscricoes_enquanto_de_pe(tmp_path: Path) -> None:
    disparou = threading.Event()
    app = criar_app(
        lambda relatar: Runners(
            lambda: [], lambda repo: [], lambda *a: VersionStatus()
        ),
        porta=PORTA,
        estaticos=tmp_path,
        inscricoes_em=tmp_path / "inscricoes.json",
    )
    ligar_disparo(app, disparou.set)

    with TestClient(app, base_url=f"http://127.0.0.1:{PORTA}"):
        assert disparou.wait(TIMEOUT_S)

    app.state.disparo.join(TIMEOUT_S)
    assert not app.state.disparo.is_alive()


def test_rodada_que_falha_nao_derruba_o_laco() -> None:
    parar = threading.Event()
    chamadas: list[int] = []

    def rodada() -> None:
        chamadas.append(len(chamadas))
        if len(chamadas) == 1:
            raise RespostaInvalida("arquivo corrompido")
        parar.set()

    laco(parar, rodada, SEM_INTERVALO_S)

    assert len(chamadas) == RODADAS_ATE_PARAR
