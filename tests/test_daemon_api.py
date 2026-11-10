import contextlib
import json
import threading
from dataclasses import replace
from http import HTTPStatus
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import motor.operacoes as operacoes
from motor.daemon.app import INTERVALO_EVENTOS_S, EventoSse, criar_app
from motor.daemon.erros import TipoErro
from motor.daemon.execucoes import EstadoExecucao
from motor.domain.types import VersionStatus
from motor.engine.atualizar import AtualizarResult, AtualizarStatus
from motor.errors import BackendIndisponivel, MotorError
from motor.inscricoes import INTERVALO_PADRAO
from motor.operacoes import RepoOption, Runners, VersionOption
from motor.progresso import Progresso, RelatorProgresso
from tests.versionamento import ESCALONADO_COMPOSTA

PORTA = 8765
ESPERA_S = 5.0
REPO = "meu-repo"
VERSAO = "14.0.0"
CLONE = "/tmp/clones/meu-repo"
REPOS = [RepoOption(REPO, CLONE), RepoOption("sem-clone", None)]


class Ambiente:
    def __init__(self, tmp_path: Path) -> None:
        self.chamadas: list[tuple[Any, ...]] = []
        self.soltar = threading.Event()
        self.relatar: RelatorProgresso | None = None
        self.iniciou = threading.Event()
        self.versoes = [VersionOption("14.0.0", True), VersionOption("13.0.0", True)]
        self.resultado: VersionStatus | AtualizarResult = VersionStatus(verde=True)
        self.inscricoes = tmp_path / "inscricoes.json"

    def fabrica(self, relatar: RelatorProgresso) -> Runners:
        def executar(repo: RepoOption, versao: str, auditar: bool) -> VersionStatus:
            self.chamadas.append((repo.nome, versao, auditar))
            self.relatar = relatar
            self.iniciou.set()
            self.soltar.wait(ESPERA_S)
            return cast(VersionStatus, self.resultado)

        return Runners(
            lambda: REPOS,
            lambda repo: self.versoes,
            executar,
            versionamento_repo=lambda repo: ESCALONADO_COMPOSTA(),
        )


@pytest.fixture
def amb(tmp_path: Path) -> Ambiente:
    return Ambiente(tmp_path)


@pytest.fixture
def cliente(amb: Ambiente, tmp_path: Path) -> TestClient:
    app = criar_app(
        amb.fabrica,
        porta=PORTA,
        estaticos=tmp_path,
        inscricoes_em=amb.inscricoes,
    )
    return TestClient(app, base_url=f"http://127.0.0.1:{PORTA}")


def _esperar(c: TestClient, repo: str = REPO) -> None:
    assert cast(FastAPI, c.app).state.execucoes.aguardar(repo, ESPERA_S)


def _eventos(c: TestClient, repo: str = REPO) -> list[tuple[str, Any]]:
    corpo = c.get(f"/api/repos/{repo}/execucao/eventos").text
    saida = []
    for bloco in corpo.strip().split("\n\n"):
        nome, dados = bloco.split("\n")
        saida.append(
            (nome.removeprefix("event: "), json.loads(dados.removeprefix("data: ")))
        )
    return saida


def test_lista_repos_e_versoes(cliente: TestClient) -> None:
    repos = cliente.get("/api/repos").json()
    assert repos[0]["caminho"] == CLONE
    assert repos[1]["caminho"] is None
    versoes = cliente.get(f"/api/repos/{REPO}/versoes").json()
    assert [v["numero"] for v in versoes] == ["14.0.0", "13.0.0"]


def test_operacao_em_repo_sem_checkout_da_404_com_mensagem_do_motor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, amb: Ambiente
) -> None:
    monkeypatch.setattr(operacoes, "abrir_sessao", lambda: contextlib.nullcontext(None))
    real = Runners(lambda: REPOS, lambda repo: [], operacoes.verificar_repo)
    app = criar_app(
        lambda relatar: real,
        porta=PORTA,
        estaticos=tmp_path,
        inscricoes_em=amb.inscricoes,
    )
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORTA}")
    r = c.post(
        "/api/repos/sem-clone/versoes/14.0.0/verificacao", json={"auditar": False}
    )
    assert r.status_code == HTTPStatus.ACCEPTED
    assert app.state.execucoes.aguardar("sem-clone", ESPERA_S)
    execucao = c.get("/api/repos/sem-clone/execucao").json()
    assert execucao["estado"] == EstadoExecucao.FALHOU
    assert execucao["erro"]["tipo"] == TipoErro.NAO_ENCONTRADO


def test_rota_com_versao_pontuada_e_repo_com_hifen(
    cliente: TestClient, amb: Ambiente
) -> None:
    amb.soltar.set()
    r = cliente.post(
        f"/api/repos/{REPO}/versoes/{VERSAO}/verificacao", json={"auditar": False}
    )
    assert r.status_code == HTTPStatus.ACCEPTED
    _esperar(cliente)
    assert amb.chamadas == [(REPO, VERSAO, False)]


def test_segunda_operacao_no_mesmo_repo_da_409(
    cliente: TestClient, amb: Ambiente
) -> None:
    url = f"/api/repos/{REPO}/versoes/{VERSAO}/verificacao"
    assert cliente.post(url, json={"auditar": False}).status_code == HTTPStatus.ACCEPTED
    r = cliente.post(url, json={"auditar": True})
    assert r.status_code == HTTPStatus.CONFLICT
    assert r.json()["tipo"] == TipoErro.OCUPADO
    amb.soltar.set()
    _esperar(cliente)


def test_eventos_de_execucao_ja_terminada_entrega_fim_na_hora(
    cliente: TestClient, amb: Ambiente
) -> None:
    amb.soltar.set()
    cliente.post(
        f"/api/repos/{REPO}/versoes/{VERSAO}/verificacao", json={"auditar": False}
    )
    _esperar(cliente)
    eventos = _eventos(cliente)
    assert [e[0] for e in eventos] == [EventoSse.FIM]
    assert eventos[0][1]["resultado"]["verde"] is True


def test_eventos_sem_execucao_mandam_fim_nulo(cliente: TestClient) -> None:
    assert _eventos(cliente) == [(EventoSse.FIM, None)]


def test_eventos_entregam_progresso_e_depois_fim(
    cliente: TestClient, amb: Ambiente
) -> None:
    cliente.post(
        f"/api/repos/{REPO}/versoes/{VERSAO}/verificacao", json={"auditar": False}
    )
    assert amb.iniciou.wait(ESPERA_S)
    assert amb.relatar is not None
    amb.relatar(Progresso("fase um", 1, 2))
    # solta depois de alguns ciclos de amostragem
    threading.Timer(INTERVALO_EVENTOS_S * 3, amb.soltar.set).start()
    eventos = _eventos(cliente)
    assert [e[0] for e in eventos] == [EventoSse.PROGRESSO, EventoSse.FIM]
    assert eventos[0][1]["fase"] == "fase um"
    assert eventos[1][1]["estado"] == EstadoExecucao.CONCLUIDA


def test_atualizar_bloqueado_continua_consultavel_por_execucao(
    cliente: TestClient, amb: Ambiente
) -> None:
    amb.soltar.set()
    amb.resultado = AtualizarResult(
        AtualizarStatus.BLOCKED,
        arquivos_conflito=["a.py"],
        culpados=["T-1"],
    )
    cliente.post(
        f"/api/repos/{REPO}/versoes/{VERSAO}/verificacao", json={"auditar": False}
    )
    _esperar(cliente)
    resultado = cliente.get(f"/api/repos/{REPO}/execucao").json()["resultado"]
    assert resultado["status"] == AtualizarStatus.BLOCKED
    assert resultado["arquivos_conflito"] == ["a.py"]
    assert resultado["culpados"] == ["T-1"]


def test_pendencias_guardam_o_bloqueio_depois_de_uma_verificacao(
    amb: Ambiente, tmp_path: Path
) -> None:
    amb.soltar.set()
    bloqueio = AtualizarResult(AtualizarStatus.BLOCKED, arquivos_conflito=["a.py"])
    app = criar_app(
        lambda relatar: replace(
            amb.fabrica(relatar), atualizar_repo=lambda repo, versao: bloqueio
        ),
        porta=PORTA,
        estaticos=tmp_path,
        inscricoes_em=amb.inscricoes,
    )
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORTA}")
    c.post(f"/api/repos/{REPO}/versoes/{VERSAO}/atualizacao")
    _esperar(c)
    c.post(f"/api/repos/{REPO}/versoes/{VERSAO}/verificacao", json={"auditar": False})
    _esperar(c)
    [pendente] = c.get(f"/api/repos/{REPO}/pendencias").json()
    assert pendente["versao"] == VERSAO
    assert pendente["resultado"]["status"] == AtualizarStatus.BLOCKED


def test_runner_opcional_ausente_falha_com_erro_claro(
    cliente: TestClient,
) -> None:
    cliente.post(f"/api/repos/{REPO}/versoes/{VERSAO}/atualizacao")
    _esperar(cliente)
    execucao = cliente.get(f"/api/repos/{REPO}/execucao").json()
    assert execucao["estado"] == EstadoExecucao.FALHOU
    assert execucao["erro"]["tipo"] == TipoErro.RECUSA


def test_avaliacao_recusa_numero_existente_e_aceita_sugestao(
    cliente: TestClient, amb: Ambiente
) -> None:
    amb.versoes = []  # só as existentes do pedido valem: nada de carregar_versoes
    url = f"/api/repos/{REPO}/versoes/avaliacao"
    existentes = [VERSAO]
    pedido = {"numero": VERSAO, "existentes": existentes}
    assert cliente.post(url, json=pedido).json()["erro"] != ""
    sugestoes = cliente.post(
        f"/api/repos/{REPO}/versoes/sugestoes", json={"existentes": existentes}
    ).json()
    assert sugestoes
    assert VERSAO not in [s["numero"] for s in sugestoes]
    pedido = {"numero": sugestoes[0]["numero"], "existentes": existentes}
    aceita = cliente.post(url, json=pedido).json()
    assert aceita["erro"] == ""
    assert aceita["previa"] != ""


def test_inscricoes_inscrever_listar_remover(cliente: TestClient) -> None:
    corpo = {"repo": REPO, "versao": VERSAO}
    assert (
        cliente.post("/api/inscricoes", json=corpo).status_code == HTTPStatus.NO_CONTENT
    )
    [vista] = cliente.get("/api/inscricoes").json()
    assert vista["repo"] == REPO
    assert vista["intervalo"] == INTERVALO_PADRAO
    assert vista["ultima"] is None
    r = cliente.request("DELETE", "/api/inscricoes", json=corpo)
    assert r.status_code == HTTPStatus.NO_CONTENT
    assert cliente.get("/api/inscricoes").json() == []


def test_inscrever_grava_sem_diretorio_nem_ambiente(
    cliente: TestClient, amb: Ambiente
) -> None:
    cliente.post("/api/inscricoes", json={"repo": REPO, "versao": VERSAO})
    [crua] = json.loads(amb.inscricoes.read_text(encoding="utf-8"))
    assert "diretorio" not in crua
    assert "ambiente" not in crua


def test_inscrever_repo_sem_checkout_da_404(cliente: TestClient) -> None:
    r = cliente.post("/api/inscricoes", json={"repo": "sem-clone", "versao": VERSAO})
    assert r.status_code == HTTPStatus.NOT_FOUND
    assert cliente.get("/api/inscricoes").json() == []


@pytest.mark.parametrize(
    ("erro", "status", "tipo"),
    [
        (
            BackendIndisponivel("sem rede"),
            HTTPStatus.SERVICE_UNAVAILABLE,
            TipoErro.BACKEND,
        ),
        (RuntimeError("segredo"), HTTPStatus.INTERNAL_SERVER_ERROR, TipoErro.INTERNO),
    ],
)
def test_erro_nas_leituras_segue_a_tabela(
    amb: Ambiente, erro: Exception, status: HTTPStatus, tipo: TipoErro
) -> None:
    def falha(repo: RepoOption) -> list[VersionOption]:
        raise erro

    original = amb.fabrica

    def fabrica(relatar: RelatorProgresso) -> Runners:
        return replace(original(relatar), carregar_versoes=falha)

    app = criar_app(
        fabrica,
        porta=PORTA,
        estaticos=amb.inscricoes.parent,
        inscricoes_em=amb.inscricoes,
    )
    # Só o erro não previsto é relançado (para o traceback ir ao log).
    r = TestClient(
        app,
        base_url=f"http://127.0.0.1:{PORTA}",
        raise_server_exceptions=isinstance(erro, MotorError),
    ).get(f"/api/repos/{REPO}/versoes")
    assert r.status_code == status
    assert set(r.json()) == {"tipo", "mensagem"}
    assert r.json()["tipo"] == tipo
    assert "segredo" not in r.json()["mensagem"]


def test_repo_desconhecido_em_operacao_da_404_na_hora(cliente: TestClient) -> None:
    r = cliente.post(
        "/api/repos/inexistente/versoes/1.0.0/verificacao", json={"auditar": False}
    )
    assert r.status_code == HTTPStatus.NOT_FOUND
    assert r.json()["tipo"] == TipoErro.NAO_ENCONTRADO


def test_corpo_invalido_segue_o_formato_da_api(cliente: TestClient) -> None:
    r = cliente.post("/api/inscricoes", json={})
    assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert set(r.json()) == {"tipo", "mensagem"}
    assert r.json()["tipo"] == TipoErro.ENTRADA


def test_spa_serve_index_em_rota_do_front(cliente: TestClient, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<p>spa</p>")
    resposta = cliente.get("/r/alpha/v/14.0.0")
    assert resposta.status_code == HTTPStatus.OK
    assert resposta.text == "<p>spa</p>"


def test_api_desconhecida_nao_cai_no_index(cliente: TestClient, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<p>spa</p>")
    resposta = cliente.get("/api/nada")
    assert resposta.status_code == HTTPStatus.NOT_FOUND
    assert resposta.json()["tipo"] == TipoErro.NAO_ENCONTRADO


def test_estatico_nao_sai_da_pasta(cliente: TestClient, tmp_path: Path) -> None:
    pasta = tmp_path / "static"
    pasta.mkdir()
    (pasta / "index.html").write_text("<p>spa</p>")
    (tmp_path / "segredo.txt").write_text("segredo")
    app = criar_app(
        lambda relatar: cast(Runners, None),
        porta=PORTA,
        estaticos=pasta,
        inscricoes_em=tmp_path / "i.json",
    )
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORTA}")
    resposta = c.get("/%2e%2e/segredo.txt")
    assert "segredo" not in resposta.text
    assert resposta.text == "<p>spa</p>"
