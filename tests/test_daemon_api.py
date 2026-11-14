import contextlib
import datetime
import hashlib
import json
import os
import threading
import time
from dataclasses import replace
from enum import StrEnum
from http import HTTPStatus
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

import motor.daemon.app as app_daemon
import motor.novidades as modulo_novidades
import motor.operacoes as operacoes
from motor.adapters.commitsource.bitbucket import Var as VarBitbucket
from motor.adapters.sugestao.fake import FakeProvedorSugestao
from motor.config import (
    CHAVE_CAMINHO,
    TABELA_AMBIENTE,
    VAR_XDG_CONFIG_HOME,
    Chave,
    Tabela,
    VarAmbiente,
)
from motor.config_edicao import AcaoAlteracao, GrupoPlugin
from motor.daemon.app import INTERVALO_EVENTOS_S, EventoSse, criar_app
from motor.daemon.erros import TipoErro
from motor.daemon.execucoes import EstadoExecucao
from motor.diagnostico import PecaTestavel
from motor.domain.conflito import PedidoAoProvedor, PropostaDeBloco, TipoArquivo
from motor.domain.types import JulgamentoOrfao, VersionStatus
from motor.engine.atualizar import AtualizarResult, AtualizarStatus
from motor.engine.conflito import (
    ArquivoDoConflito,
    ConflitoAberto,
    ConteudoDoConflito,
    propor_resolucao,
)
from motor.engine.orfaos import OrfaoDaVersao
from motor.errors import (
    BackendIndisponivel,
    ErroDeEntrada,
    MotorError,
    NaoEncontrado,
    RespostaInvalida,
    VersaoDesatualizada,
)
from motor.inscricoes import INTERVALO_PADRAO
from motor.instalacao import PACOTE_MOTOR, Origem, PluginInstalado, TipoOrigem
from motor.novidades import VALIDADE, Cache, Novidade
from motor.operacoes import (
    PedidoProposta,
    RepoOption,
    Resolucao,
    Runners,
    VersionOption,
)
from motor.progresso import Progresso, RelatorProgresso
from tests import conflito_falso
from tests.versionamento import ESCALONADO_COMPOSTA

PORTA = 8765
ESPERA_S = 5.0
REPO = "meu-repo"
VERSAO = "14.0.0"
CLONE = "/tmp/clones/meu-repo"
CAMINHO = "src/app/main.py"
VERSAO_DISCO = "v1"
JUSTIFICATIVA = "mantém o lado do HEAD"
CONFLITO = ConflitoAberto(
    "abc123",
    "msg",
    None,
    [ArquivoDoConflito(CAMINHO, TipoArquivo.CONTEUDO, False)],
    sugestao_disponivel=True,
)
CONTEUDO = ConteudoDoConflito(TipoArquivo.CONTEUDO, "b", "o", "t", "d", VERSAO_DISCO)
BASE_CONFLITO = f"/api/repos/{REPO}/versoes/{VERSAO}/conflito"
REPOS = [RepoOption(REPO, CLONE), RepoOption("sem-clone", None)]
ORFAOS = ["aaaa1111", "bbbb2222"]
DATA_ORFAO = datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)


class Ambiente:
    def __init__(self, tmp_path: Path) -> None:
        self.chamadas: list[tuple[Any, ...]] = []
        self.soltar = threading.Event()
        self.relatar: RelatorProgresso | None = None
        self.iniciou = threading.Event()
        self.versoes = [VersionOption("14.0.0", True), VersionOption("13.0.0", True)]
        self.resultado: VersionStatus | AtualizarResult = VersionStatus(verde=True)
        self.inscricoes = tmp_path / "inscricoes.json"
        self.erro_conflito: MotorError | None = None
        self.julgamentos: dict[str, JulgamentoOrfao] = {}
        self.erro_julgar: MotorError | None = None
        self.soltar_proposta = threading.Event()
        self.proposta_iniciou = threading.Event()
        self.erro_provedor: MotorError | None = None
        self.provedor = FakeProvedorSugestao(responder=self._responder)
        self.deps_proposta = conflito_falso.deps_em_conflito(
            estagios=conflito_falso.ESTAGIOS_DOIS, provedor=self.provedor
        )

    def _responder(self, pedido: PedidoAoProvedor) -> list[PropostaDeBloco]:
        self.proposta_iniciou.set()
        self.soltar_proposta.wait(ESPERA_S)
        if self.erro_provedor is not None:
            raise self.erro_provedor
        return [
            PropostaDeBloco(b.ordem, b.ours + b.theirs, JUSTIFICATIVA)
            for b in pedido.blocos
        ]

    def propor(
        self, repo: RepoOption, versao: str, pedido: PedidoProposta
    ) -> list[PropostaDeBloco]:
        return propor_resolucao(
            self.deps_proposta,
            conflito_falso.VERSAO,
            pedido.caminho,
            pedido.versao_disco,
            pedido.ordens,
        )

    def fabrica(self, relatar: RelatorProgresso) -> Runners:
        def executar(repo: RepoOption, versao: str, auditar: bool) -> VersionStatus:
            self.chamadas.append((repo.nome, versao, auditar))
            self.relatar = relatar
            self.iniciou.set()
            self.soltar.wait(ESPERA_S)
            return cast(VersionStatus, self.resultado)

        def falhar_ou(valor: Any) -> Any:
            if self.erro_conflito is not None:
                raise self.erro_conflito
            return valor

        def ler_conflito(repo: RepoOption, versao: str) -> ConflitoAberto:
            return cast(ConflitoAberto, falhar_ou(CONFLITO))

        def ler_arquivo(repo: RepoOption, versao: str, caminho: str) -> Any:
            self.chamadas.append((repo.nome, versao, caminho))
            return falhar_ou(CONTEUDO)

        def resolver(repo: RepoOption, versao: str, resolucao: Resolucao) -> None:
            self.chamadas.append(
                (resolucao.caminho, resolucao.conteudo, resolucao.versao_disco)
            )
            falhar_ou(None)

        def reabrir(repo: RepoOption, versao: str, caminho: str) -> None:
            self.chamadas.append((caminho,))
            falhar_ou(None)

        return Runners(
            lambda: REPOS,
            lambda repo: self.versoes,
            executar,
            ler_conflito=ler_conflito,
            ler_arquivo_conflito=ler_arquivo,
            resolver_arquivo_conflito=resolver,
            reabrir_arquivo_conflito=reabrir,
            propor_resolucao=self.propor,
            versionamento_repo=lambda repo: ESCALONADO_COMPOSTA(),
            listar_orfaos=self.listar_orfaos,
            julgar_orfao=self.julgar_orfao,
        )

    def listar_orfaos(self, repo: RepoOption, versao: str) -> list[OrfaoDaVersao]:
        return [
            OrfaoDaVersao(h, f"assunto {h}", DATA_ORFAO, self.julgamentos.get(h))
            for h in ORFAOS
        ]

    def julgar_orfao(
        self,
        repo: RepoOption,
        versao: str,
        hash_: str,
        chamado: str | None,
        motivo: str,
    ) -> JulgamentoOrfao:
        if self.erro_julgar is not None:
            raise self.erro_julgar
        j = JulgamentoOrfao(hash_, versao, chamado, motivo)
        self.julgamentos[hash_] = j
        return j


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
    # Sem auditar: a auditoria não trava, então não seria recusada.
    r = cliente.post(url, json={"auditar": False})
    assert r.status_code == HTTPStatus.CONFLICT
    assert r.json()["tipo"] == TipoErro.OCUPADO
    amb.soltar.set()
    _esperar(cliente)


_ROTAS_COBERTAS = [
    (f"/api/repos/{REPO}/versoes/{VERSAO}/verificacao", {"auditar": False}),
    (f"/api/repos/{REPO}/versoes/{VERSAO}/previa", None),
    (f"/api/repos/{REPO}/versoes/{VERSAO}/atualizacao", None),
    (
        f"/api/repos/{REPO}/versoes/{VERSAO}/atualizacao/continuar",
        {"allow_empty": False},
    ),
    (f"/api/repos/{REPO}/versoes/{VERSAO}/atualizacao/abortar", None),
    (f"/api/repos/{REPO}/versoes", {"numero": "14.0.1"}),
]


@pytest.mark.parametrize(
    ("url", "corpo"),
    _ROTAS_COBERTAS,
    ids=["verificar", "previa", "atualizar", "continuar", "abortar", "criar"],
)
def test_repo_travado_por_fora_da_409_sem_criar_execucao(
    cliente: TestClient, url: str, corpo: dict[str, Any] | None
) -> None:
    from motor.trava import travar

    with travar(REPO, CLONE):
        r = cliente.post(url, json=corpo)
    assert r.status_code == HTTPStatus.CONFLICT
    assert r.json()["tipo"] == TipoErro.OCUPADO
    assert f"pid {os.getpid()}" in r.json()["mensagem"]
    assert cliente.get(f"/api/repos/{REPO}/execucao").json() is None


def test_execucao_rodando_sem_lock_nao_recusa(
    cliente: TestClient, amb: Ambiente
) -> None:
    url = f"/api/repos/{REPO}/versoes/{VERSAO}/verificacao"
    assert cliente.post(url, json={"auditar": True}).status_code == HTTPStatus.ACCEPTED
    assert amb.iniciou.wait(ESPERA_S)
    assert cliente.post(url, json={"auditar": False}).status_code == HTTPStatus.ACCEPTED
    amb.soltar.set()
    _esperar(cliente)
    prazo = time.monotonic() + ESPERA_S
    while len(amb.chamadas) < 2 and time.monotonic() < prazo:
        time.sleep(0.01)
    assert sorted(c[2] for c in amb.chamadas) == [False, True]


def test_leituras_rodam_com_repo_travado(cliente: TestClient, amb: Ambiente) -> None:
    from motor.trava import travar

    amb.soltar.set()
    with travar(REPO, CLONE):
        assert cliente.get(f"/api/repos/{REPO}/versoes").status_code == HTTPStatus.OK
        r = cliente.post(
            f"/api/repos/{REPO}/versoes/{VERSAO}/verificacao", json={"auditar": True}
        )
        assert r.status_code == HTTPStatus.ACCEPTED
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


class CasoErro(StrEnum):
    INVALIDO = "invalido"
    VELHA = "velha"
    OCUPADO = "ocupado"


SEGREDO = "s3nha"
PRINCIPAL_NOVO = "trunk"
PORTA_INVALIDA = "abc"
VERSAO_INEXISTENTE = "0" * 64


def _definir(chave: str, valor: object, tabela: str, versao: str) -> dict[str, Any]:
    alteracao = {
        "acao": AcaoAlteracao.DEFINIR,
        "tabela": tabela,
        "chave": chave,
        "valor": valor,
    }
    return {"alteracoes": [alteracao], "versao": versao}


def _definir_principal(versao: str) -> dict[str, Any]:
    return _definir(Chave.PRINCIPAL, PRINCIPAL_NOVO, Tabela.BRANCHES, versao)


@pytest.fixture
def config_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VAR_XDG_CONFIG_HOME, str(tmp_path / "xdg"))


def _valor(corpo: dict[str, Any], chave: str) -> Any:
    return next(v["valor"] for v in corpo["valores"] if v["chave"] == chave)


@pytest.mark.usefixtures("config_tmp")
def test_config_get_put_ida_e_volta(cliente: TestClient) -> None:
    lida = cliente.get("/api/config").json()
    r = cliente.put("/api/config", json=_definir_principal(lida["versao"]))
    assert r.status_code == HTTPStatus.OK
    corpo = cliente.get("/api/config").json()
    assert _valor(corpo, Chave.PRINCIPAL) == PRINCIPAL_NOVO


@pytest.mark.usefixtures("config_tmp")
def test_put_config_nao_devolve_segredo(cliente: TestClient) -> None:
    versao = cliente.get("/api/config").json()["versao"]
    r = cliente.put(
        "/api/config",
        json=_definir(VarBitbucket.TOKEN, SEGREDO, TABELA_AMBIENTE, versao),
    )
    assert r.status_code == HTTPStatus.OK
    assert SEGREDO not in r.text
    assert SEGREDO not in cliente.get("/api/config").text


@pytest.mark.usefixtures("config_tmp")
@pytest.mark.parametrize(
    ("caso", "status", "tipo"),
    [
        (CasoErro.INVALIDO, HTTPStatus.UNPROCESSABLE_ENTITY, TipoErro.ENTRADA),
        (CasoErro.VELHA, HTTPStatus.CONFLICT, TipoErro.RECUSA),
        (CasoErro.OCUPADO, HTTPStatus.CONFLICT, TipoErro.OCUPADO),
    ],
)
def test_put_config_erros(
    cliente: TestClient, amb: Ambiente, caso: CasoErro, status: int, tipo: TipoErro
) -> None:
    versao = cliente.get("/api/config").json()["versao"]
    corpo = _definir(
        VarAmbiente.WORKTREES_MANTIDAS, PORTA_INVALIDA, TABELA_AMBIENTE, versao
    )
    if caso is CasoErro.VELHA:
        corpo["versao"] = VERSAO_INEXISTENTE
    if caso is CasoErro.OCUPADO:
        corpo = _definir_principal(versao)
        url = f"/api/repos/{REPO}/versoes/{VERSAO}/verificacao"
        cliente.post(url, json={"auditar": False})
    try:
        r = cliente.put("/api/config", json=corpo)
        assert (r.status_code, r.json()["tipo"]) == (status, tipo)
    finally:
        amb.soltar.set()
    if caso is CasoErro.OCUPADO:
        _esperar(cliente)


def _pedido_teste(corpo: dict[str, Any], peca: PecaTestavel) -> dict[str, Any]:
    return corpo | {"peca": peca, "repo": None}


@pytest.mark.usefixtures("config_tmp")
@pytest.mark.parametrize(
    ("caso", "status", "tipo"),
    [
        (CasoErro.INVALIDO, HTTPStatus.UNPROCESSABLE_ENTITY, TipoErro.ENTRADA),
        (CasoErro.VELHA, HTTPStatus.CONFLICT, TipoErro.RECUSA),
    ],
)
def test_testar_config_erros(
    cliente: TestClient, caso: CasoErro, status: int, tipo: TipoErro
) -> None:
    versao = cliente.get("/api/config").json()["versao"]
    corpo = _definir(
        VarAmbiente.WORKTREES_MANTIDAS, PORTA_INVALIDA, TABELA_AMBIENTE, versao
    )
    if caso is CasoErro.VELHA:
        corpo["versao"] = VERSAO_INEXISTENTE
    r = cliente.post("/api/config/testar", json=_pedido_teste(corpo, PecaTestavel.PRS))
    assert (r.status_code, r.json()["tipo"]) == (status, tipo)


@pytest.mark.usefixtures("config_tmp")
def test_testar_config_nao_e_bloqueado_por_execucao_e_nao_grava(
    cliente: TestClient, amb: Ambiente, tmp_path: Path
) -> None:
    versao = cliente.get("/api/config").json()["versao"]
    cliente.post(
        f"/api/repos/{REPO}/versoes/{VERSAO}/verificacao", json={"auditar": False}
    )
    novo = {"acao": AcaoAlteracao.CRIAR_REPO, "repo": "novo"}
    caminho = {
        "acao": AcaoAlteracao.DEFINIR,
        "repo": "novo",
        "chave": CHAVE_CAMINHO,
        "valor": str(tmp_path),
    }
    corpo = {
        "alteracoes": [novo, caminho],
        "versao": versao,
        "peca": PecaTestavel.REPO,
        "repo": "novo",
    }
    try:
        r = cliente.post("/api/config/testar", json=corpo)
        assert r.status_code == HTTPStatus.OK
        assert set(r.json()) == {"estado", "detalhe", "correcao"}
        assert cliente.get("/api/config").json()["versao"] == versao
    finally:
        amb.soltar.set()
    _esperar(cliente)


def test_conflito_le_lista_e_arquivo_com_caminho_na_query(
    cliente: TestClient, amb: Ambiente
) -> None:
    lista = cliente.get(BASE_CONFLITO)
    assert lista.status_code == HTTPStatus.OK
    assert lista.json()["arquivos"][0]["caminho"] == CAMINHO
    r = cliente.get(f"{BASE_CONFLITO}/arquivo", params={"caminho": CAMINHO})
    assert r.status_code == HTTPStatus.OK
    assert r.json()["versao_disco"] == VERSAO_DISCO
    assert amb.chamadas == [(REPO, VERSAO, CAMINHO)]


def test_conflito_resolve_e_reabre_com_204(cliente: TestClient, amb: Ambiente) -> None:
    corpo = {"caminho": CAMINHO, "conteudo": None, "versao_disco": VERSAO_DISCO}
    r = cliente.post(f"{BASE_CONFLITO}/resolucao", json=corpo)
    assert (r.status_code, r.content) == (HTTPStatus.NO_CONTENT, b"")
    r = cliente.post(f"{BASE_CONFLITO}/reabertura", json={"caminho": CAMINHO})
    assert r.status_code == HTTPStatus.NO_CONTENT
    assert amb.chamadas == [(CAMINHO, None, VERSAO_DISCO), (CAMINHO,)]


@pytest.mark.parametrize(
    ("erro", "status", "tipo"),
    [
        (NaoEncontrado("x"), HTTPStatus.NOT_FOUND, TipoErro.NAO_ENCONTRADO),
        (VersaoDesatualizada("x"), HTTPStatus.CONFLICT, TipoErro.DESATUALIZADO),
        (ErroDeEntrada("x"), HTTPStatus.UNPROCESSABLE_ENTITY, TipoErro.ENTRADA),
    ],
)
def test_conflito_traduz_erro_do_motor(
    cliente: TestClient,
    amb: Ambiente,
    erro: MotorError,
    status: HTTPStatus,
    tipo: TipoErro,
) -> None:
    amb.erro_conflito = erro
    r = cliente.post(
        f"{BASE_CONFLITO}/resolucao",
        json={"caminho": CAMINHO, "conteudo": "x", "versao_disco": VERSAO_DISCO},
    )
    assert r.status_code == status
    assert r.json()["tipo"] == tipo


@pytest.mark.parametrize(
    ("rota", "corpo"),
    [
        (
            "resolucao",
            {"caminho": CAMINHO, "conteudo": "x", "versao_disco": VERSAO_DISCO},
        ),
        ("reabertura", {"caminho": CAMINHO}),
    ],
    ids=["resolucao", "reabertura"],
)
def test_escrita_de_conflito_com_repo_travado_da_409(
    cliente: TestClient, rota: str, corpo: dict[str, Any]
) -> None:
    from motor.trava import travar

    with travar(REPO, CLONE):
        r = cliente.post(f"{BASE_CONFLITO}/{rota}", json=corpo)
    assert r.status_code == HTTPStatus.CONFLICT
    assert r.json()["tipo"] == TipoErro.OCUPADO


def test_leitura_de_conflito_roda_com_repo_travado(cliente: TestClient) -> None:
    from motor.trava import travar

    with travar(REPO, CLONE):
        assert cliente.get(BASE_CONFLITO).status_code == HTTPStatus.OK


def test_escrita_de_conflito_solta_o_repo_depois_de_erro_do_runner(
    cliente: TestClient, amb: Ambiente
) -> None:
    url = f"{BASE_CONFLITO}/reabertura"
    amb.erro_conflito = NaoEncontrado("x")
    assert (
        cliente.post(url, json={"caminho": CAMINHO}).status_code == HTTPStatus.NOT_FOUND
    )
    amb.erro_conflito = None
    r = cliente.post(url, json={"caminho": CAMINHO})
    assert r.status_code == HTTPStatus.NO_CONTENT


VERSAO_DISCO_VELHA = "leitura-velha"


def _proposta() -> dict[str, Any]:
    return {
        "caminho": conflito_falso.DOIS,
        "versao_disco": hashlib.sha256(conflito_falso.DISCO_DOIS.encode()).hexdigest(),
        "ordens": [1],
    }


def test_conflito_informa_sugestao_disponivel(cliente: TestClient) -> None:
    assert cliente.get(BASE_CONFLITO).json()["sugestao_disponivel"] is True


def test_proposta_devolve_conteudo_e_justificativa(
    cliente: TestClient, amb: Ambiente
) -> None:
    amb.soltar_proposta.set()
    r = cliente.post(f"{BASE_CONFLITO}/proposta", json=_proposta())
    assert r.status_code == HTTPStatus.OK
    assert r.json() == [
        {"ordem": 1, "conteudo": "A2\nB2\n", "justificativa": JUSTIFICATIVA}
    ]


@pytest.mark.parametrize(
    ("corpo", "status", "tipo"),
    [
        (
            {"versao_disco": VERSAO_DISCO_VELHA},
            HTTPStatus.CONFLICT,
            TipoErro.DESATUALIZADO,
        ),
        ({"ordens": [7]}, HTTPStatus.UNPROCESSABLE_ENTITY, TipoErro.ENTRADA),
    ],
    ids=["leitura-velha", "ordem-inexistente"],
)
def test_proposta_recusa_leitura_velha_e_ordem_inexistente(
    cliente: TestClient,
    amb: Ambiente,
    corpo: dict[str, Any],
    status: HTTPStatus,
    tipo: TipoErro,
) -> None:
    amb.soltar_proposta.set()
    r = cliente.post(f"{BASE_CONFLITO}/proposta", json={**_proposta(), **corpo})
    assert (r.status_code, r.json()["tipo"]) == (status, tipo)


@pytest.mark.parametrize(
    ("erro", "status", "tipo"),
    [
        (
            RespostaInvalida("sem justificativa para o bloco 1"),
            HTTPStatus.BAD_GATEWAY,
            TipoErro.RESPOSTA,
        ),
        (
            BackendIndisponivel("rede"),
            HTTPStatus.SERVICE_UNAVAILABLE,
            TipoErro.BACKEND,
        ),
        (
            ErroDeEntrada("faltando ANTHROPIC_API_KEY"),
            HTTPStatus.UNPROCESSABLE_ENTITY,
            TipoErro.ENTRADA,
        ),
    ],
)
def test_erro_do_provedor_vira_erro_da_api_sem_traceback(
    cliente: TestClient,
    amb: Ambiente,
    erro: MotorError,
    status: HTTPStatus,
    tipo: TipoErro,
) -> None:
    amb.soltar_proposta.set()
    amb.erro_provedor = erro
    r = cliente.post(f"{BASE_CONFLITO}/proposta", json=_proposta())
    assert (r.status_code, r.json()["tipo"]) == (status, tipo)
    assert str(erro) in r.json()["mensagem"]
    assert "Traceback" not in r.text


def test_proposta_nao_trava_o_repo(cliente: TestClient, amb: Ambiente) -> None:
    from motor.trava import travar

    respostas: list[int] = []
    pedido = threading.Thread(
        target=lambda: respostas.append(
            TestClient(cliente.app, base_url=str(cliente.base_url))
            .post(f"{BASE_CONFLITO}/proposta", json=_proposta())
            .status_code
        )
    )
    pedido.start()
    try:
        assert amb.proposta_iniciou.wait(ESPERA_S)
        corpo = {"caminho": CAMINHO, "conteudo": None, "versao_disco": VERSAO_DISCO}
        r = cliente.post(f"{BASE_CONFLITO}/resolucao", json=corpo)
        assert r.status_code == HTTPStatus.NO_CONTENT
        with travar(REPO, CLONE):
            pass
    finally:
        amb.soltar_proposta.set()
        pedido.join(ESPERA_S)
    assert respostas == [HTTPStatus.OK]


def test_daemon_sobe_com_provedor_inexistente(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VAR_XDG_CONFIG_HOME, str(tmp_path / "xdg"))
    central = tmp_path / "xdg" / "monitor-versoes" / "config.toml"
    central.parent.mkdir(parents=True)
    central.write_text(
        f"[sugestao]\nprovedor = \"inexistente\"\n\n[repos.r]\ncaminho = '{tmp_path}'\n"
    )
    app = criar_app(
        operacoes.runners_com_progresso,
        porta=PORTA,
        estaticos=tmp_path,
        inscricoes_em=tmp_path / "inscricoes.json",
    )
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORTA}")
    assert c.get("/api/repos").status_code == HTTPStatus.OK
    assert c.get("/api/config").status_code == HTTPStatus.OK


_ORFAOS_URL = f"/api/repos/{REPO}/versoes/{VERSAO}/orfaos"


def _julgamento_url(hash_: str) -> str:
    return f"{_ORFAOS_URL}/{hash_}/julgamento"


def test_orfaos_lista_e_julga(cliente: TestClient) -> None:
    lista = cliente.get(_ORFAOS_URL).json()
    assert [o["hash_origem"] for o in lista] == ORFAOS
    assert all(o["julgamento"] is None for o in lista)

    r = cliente.post(_julgamento_url(ORFAOS[0]), json={"chamado": "123", "motivo": "a"})
    assert r.status_code == HTTPStatus.OK
    assert r.json() == {
        "hash_origem": ORFAOS[0],
        "versao_numero": VERSAO,
        "chamado": "123",
        "motivo": "a",
    }
    r = cliente.post(_julgamento_url(ORFAOS[1]), json={"chamado": None, "motivo": "b"})
    assert r.status_code == HTTPStatus.OK
    assert r.json()["chamado"] is None

    julgados = [o["julgamento"] for o in cliente.get(_ORFAOS_URL).json()]
    assert [(j["chamado"], j["motivo"]) for j in julgados] == [
        ("123", "a"),
        (None, "b"),
    ]


def test_rotas_de_orfaos_rodam_com_repo_travado(
    cliente: TestClient, amb: Ambiente
) -> None:
    # Como o `reconstruir-estado`, só fazem fetch e gravam no estado (decisão 034).
    from motor.trava import travar

    with travar(REPO, CLONE):
        assert cliente.get(_ORFAOS_URL).status_code == HTTPStatus.OK
        r = cliente.post(
            _julgamento_url(ORFAOS[0]), json={"chamado": None, "motivo": "m"}
        )
        assert r.status_code == HTTPStatus.OK
    assert ORFAOS[0] in amb.julgamentos


def test_julgamento_com_erro_de_entrada_da_422(
    cliente: TestClient, amb: Ambiente
) -> None:
    amb.erro_julgar = ErroDeEntrada("o motivo do julgamento é obrigatório")
    r = cliente.post(_julgamento_url(ORFAOS[0]), json={"chamado": None, "motivo": ""})
    assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert r.json() == {
        "tipo": TipoErro.ENTRADA,
        "mensagem": "o motivo do julgamento é obrigatório",
    }


def test_rotas_de_orfaos_no_openapi(cliente: TestClient) -> None:
    caminhos = cast(FastAPI, cliente.app).openapi()["paths"]
    assert "/api/repos/{repo}/versoes/{versao}/orfaos" in caminhos
    assert "/api/repos/{repo}/versoes/{versao}/orfaos/{hash}/julgamento" in caminhos


_PLUGIN = PluginInstalado(
    GrupoPlugin.PRS,
    "github",
    "plugin-prs",
    "1.0.0",
    Origem(TipoOrigem.GIT, "https://example.com/plugin-prs", "v1.0.0", "abc"),
)
_NOVIDADE = Novidade(PACOTE_MOTOR, "0.2.0", "0.3.0", f"{PACOTE_MOTOR} atualizar-motor")


def _preparar_instalacao(
    monkeypatch: pytest.MonkeyPatch, checado_em: datetime.datetime
) -> list[int]:
    renovacoes: list[int] = []
    monkeypatch.setattr(app_daemon, "plugins_instalados", lambda: [_PLUGIN])
    monkeypatch.setattr(modulo_novidades, "ler_registro", object)
    monkeypatch.setattr(modulo_novidades, "checagem_ligada", lambda: True)
    monkeypatch.setattr(
        modulo_novidades, "ler_cache", lambda _: Cache(checado_em, (_NOVIDADE,))
    )
    monkeypatch.setattr(
        modulo_novidades, "disparar_renovacao", lambda: renovacoes.append(1)
    )
    return renovacoes


def test_api_instalacao(cliente: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    agora = datetime.datetime.now(datetime.UTC)
    renovacoes = _preparar_instalacao(monkeypatch, agora)

    corpo = cliente.get("/api/instalacao").json()

    assert corpo == {
        "plugins": [jsonable_encoder(_PLUGIN)],
        "novidades": [jsonable_encoder(_NOVIDADE)],
    }
    assert renovacoes == []


def test_api_instalacao_com_cache_vencido_dispara_renovacao(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    vencido = datetime.datetime.now(datetime.UTC) - VALIDADE * 2
    renovacoes = _preparar_instalacao(monkeypatch, vencido)

    corpo = cliente.get("/api/instalacao").json()

    assert corpo["novidades"] == [jsonable_encoder(_NOVIDADE)]
    assert renovacoes == [1]


def test_api_instalacao_com_config_invalida_vem_sem_novidades(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _preparar_instalacao(monkeypatch, datetime.datetime.now(datetime.UTC))

    def invalida() -> bool:
        raise ErroDeEntrada("checar deve ser true ou false")

    monkeypatch.setattr(modulo_novidades, "checagem_ligada", invalida)

    r = cliente.get("/api/instalacao")

    assert r.status_code == HTTPStatus.OK
    assert r.json()["novidades"] == []
