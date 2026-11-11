"""API HTTP do daemon: traduz rotas para os `Runners` e roda as operações longas em `Execucoes`."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from http import HTTPStatus
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from motor import inscricoes as arquivo
from motor.config import SECAO_REPOS
from motor.daemon import PORTA_PADRAO as PORTA_PADRAO
from motor.daemon.erros import MENSAGEM_INTERNA, ErroApi, TipoErro, erro_api
from motor.daemon.execucoes import EstadoExecucao, Execucao, Execucoes, Operacao
from motor.daemon.seguranca import proteger
from motor.domain.inscricao import UltimaExecucao
from motor.domain.types import VersionStatus
from motor.engine.atualizar import AtualizarResult
from motor.engine.consultar import ChamadoConsultado
from motor.errors import ErroDeEntrada, MotorError, NaoEncontrado, RecusaDeInvariante
from motor.operacoes import (
    RepoOption,
    Runners,
    VersionamentoLoader,
    VersionOption,
    avaliar_numero,
    runners_com_progresso,
    travar_repo,
    versionamento_do_repo,
)
from motor.progresso import RelatorProgresso, silencioso
from motor.services.versionamento import Versionamento

INTERVALO_EVENTOS_S = 0.1
ATRASO_NAVEGADOR_S = 1.0
PASTA_ESTATICOS = Path(__file__).parent / "static"
MENSAGEM_INDISPONIVEL = "operação indisponível neste ambiente"


class EventoSse(StrEnum):
    PROGRESSO = "progresso"
    FIM = "fim"


@dataclass(frozen=True)
class NumeroVersao:
    numero: str


@dataclass(frozen=True)
class PedidoSugestoes:
    existentes: list[str]


@dataclass(frozen=True)
class PedidoAvaliacao:
    numero: str
    existentes: list[str]


@dataclass(frozen=True)
class PedidoVerificacao:
    auditar: bool


@dataclass(frozen=True)
class PedidoContinuar:
    allow_empty: bool


@dataclass(frozen=True)
class PedidoInscrever:
    repo: str
    versao: str


@dataclass(frozen=True)
class PedidoRemover:
    repo: str
    versao: str


@dataclass(frozen=True)
class Sugestao:
    numero: str
    tipo: str | None


@dataclass(frozen=True)
class Avaliacao:
    previa: str
    erro: str


@dataclass(frozen=True)
class InscricaoVista:
    repo: str
    versao: str
    intervalo: str
    ultima: UltimaExecucao | None


# Rotas síncronas respondem 409 aqui; nas operações longas o erro cai na Execucao
# (FALHOU), porque só nelas existe uma execução para carregá-lo.
def _exigir[T](runner: T | None) -> T:
    if runner is None:
        raise RecusaDeInvariante(MENSAGEM_INDISPONIVEL)
    return runner


def _evento(evento: EventoSse, dados: object) -> str:
    return f"event: {evento}\ndata: {json.dumps(jsonable_encoder(dados))}\n\n"


@dataclass(frozen=True)
class _Contexto:
    fabrica: Callable[[RelatorProgresso], Runners]
    versionamento_repo: VersionamentoLoader
    inscricoes_em: Path
    execucoes: Execucoes = field(default_factory=Execucoes)

    def leitura(self) -> Runners:
        return self.fabrica(silencioso)

    def achar(self, nome: str) -> RepoOption:
        for repo in self.leitura().carregar_repos():
            if repo.nome == nome:
                return repo
        raise NaoEncontrado(
            f"repo {nome} sem seção [{SECAO_REPOS}.{nome}] no config.toml"
        )

    def versionamento(self, runners: Runners, repo: RepoOption) -> Versionamento:
        return (runners.versionamento_repo or self.versionamento_repo)(repo)

    def disparar(
        self,
        nome: str,
        versao: str,
        operacao: Operacao,
        usar: Callable[[Runners, RepoOption], VersionStatus | AtualizarResult | None],
        *,
        travar: bool = True,
    ) -> Execucao:
        """Toma o lock do clone na thread do pedido e o entrega à execução.

        Travar aqui, e não na thread, é o que faz o `RepoOcupado` sair como
        `409` síncrono, sem criar execução (decisão 032).
        """
        repo = self.achar(nome)

        def alvo(relatar: RelatorProgresso) -> VersionStatus | AtualizarResult | None:
            return usar(self.fabrica(relatar), repo)

        trava = travar_repo(repo) if travar else None
        return self.execucoes.iniciar(nome, versao, operacao, alvo, trava)


def _rotas_repos(app: FastAPI, ctx: _Contexto) -> None:
    @app.get("/api/repos")
    def listar_repos() -> list[RepoOption]:
        return ctx.leitura().carregar_repos()

    @app.get("/api/repos/{repo}/versoes")
    def listar_versoes(repo: str) -> list[VersionOption]:
        return ctx.leitura().carregar_versoes(ctx.achar(repo))

    # As versões existentes vêm da lista que o cliente já tem, como na TUI:
    # carregar de novo faria um git fetch por tecla digitada.
    @app.post("/api/repos/{repo}/versoes/sugestoes")
    def sugerir(repo: str, corpo: PedidoSugestoes) -> list[Sugestao]:
        esquema = ctx.versionamento(ctx.leitura(), ctx.achar(repo)).esquema
        return [Sugestao(n, esquema.tipo(n)) for n in esquema.sugerir(corpo.existentes)]

    @app.post("/api/repos/{repo}/versoes/avaliacao")
    def avaliar(repo: str, corpo: PedidoAvaliacao) -> Avaliacao:
        previa, erro = avaliar_numero(
            ctx.versionamento(ctx.leitura(), ctx.achar(repo)),
            corpo.existentes,
            corpo.numero,
        )
        return Avaliacao(previa, erro)

    @app.get("/api/repos/{repo}/versoes/{versao}/chamados")
    def consultar(repo: str, versao: str) -> list[ChamadoConsultado]:
        return _exigir(ctx.leitura().consultar_versao)(ctx.achar(repo), versao)


def _rotas_operacoes(app: FastAPI, ctx: _Contexto) -> None:
    base = "/api/repos/{repo}/versoes/{versao}"
    aceito = HTTPStatus.ACCEPTED

    @app.post("/api/repos/{repo}/versoes", status_code=aceito)
    def criar(repo: str, corpo: NumeroVersao) -> Execucao:
        return ctx.disparar(
            repo,
            corpo.numero,
            Operacao.CRIAR,
            lambda r, o: _exigir(r.criar_repo)(o, corpo.numero),
        )

    @app.post(f"{base}/verificacao", status_code=aceito)
    def verificar(repo: str, versao: str, corpo: PedidoVerificacao) -> Execucao:
        return ctx.disparar(
            repo,
            versao,
            Operacao.VERIFICAR,
            lambda r, o: r.executar(o, versao, corpo.auditar),
            # A auditoria não toca worktree, checkpoint nem GC: roda com o repo
            # ocupado (decisão 032).
            travar=not corpo.auditar,
        )

    @app.post(f"{base}/previa", status_code=aceito)
    def previa(repo: str, versao: str) -> Execucao:
        return ctx.disparar(
            repo,
            versao,
            Operacao.PREVIA,
            lambda r, o: _exigir(r.previa_atualizacao)(o, versao),
        )

    @app.post(f"{base}/atualizacao", status_code=aceito)
    def atualizar(repo: str, versao: str) -> Execucao:
        return ctx.disparar(
            repo,
            versao,
            Operacao.ATUALIZAR,
            lambda r, o: _exigir(r.atualizar_repo)(o, versao),
        )

    @app.post(f"{base}/atualizacao/continuar", status_code=aceito)
    def continuar(repo: str, versao: str, corpo: PedidoContinuar) -> Execucao:
        return ctx.disparar(
            repo,
            versao,
            Operacao.CONTINUAR,
            lambda r, o: _exigir(r.continuar_repo)(
                o, versao, allow_empty=corpo.allow_empty
            ),
        )

    @app.post(f"{base}/atualizacao/abortar", status_code=aceito)
    def abortar(repo: str, versao: str) -> Execucao:
        return ctx.disparar(
            repo,
            versao,
            Operacao.ABORTAR,
            lambda r, o: _exigir(r.abortar_repo)(o, versao),
        )


def _rotas_execucao(app: FastAPI, ctx: _Contexto) -> None:
    @app.get("/api/repos/{repo}/execucao")
    def execucao_atual(repo: str) -> Execucao | None:
        return ctx.execucoes.atual(repo)

    @app.get("/api/repos/{repo}/pendencias")
    def pendencias(repo: str) -> list[Execucao]:
        return ctx.execucoes.pendencias(repo)

    @app.get("/api/repos/{repo}/execucao/eventos")
    async def eventos(repo: str) -> StreamingResponse:
        async def fluxo() -> AsyncIterator[str]:
            visto = None
            while True:
                execucao = ctx.execucoes.atual(repo)
                if execucao is None or execucao.estado is not EstadoExecucao.RODANDO:
                    yield _evento(EventoSse.FIM, execucao)
                    return
                if execucao.progresso != visto:
                    visto = execucao.progresso
                    yield _evento(EventoSse.PROGRESSO, visto)
                await asyncio.sleep(INTERVALO_EVENTOS_S)

        return StreamingResponse(fluxo(), media_type="text/event-stream")


def _disponivel(opcao: RepoOption) -> str:
    if not opcao.disponivel:
        raise NaoEncontrado("checkout local não encontrado")
    return opcao.nome


def _rotas_inscricoes(app: FastAPI, ctx: _Contexto) -> None:
    @app.get("/api/inscricoes")
    def listar_inscricoes() -> list[InscricaoVista]:
        return [
            InscricaoVista(
                i.repo, i.versao, arquivo.formatar_intervalo(i.intervalo), i.ultima
            )
            for i in arquivo.carregar(ctx.inscricoes_em)
        ]

    @app.post("/api/inscricoes", status_code=HTTPStatus.NO_CONTENT)
    def inscrever(corpo: PedidoInscrever) -> None:
        arquivo.inscrever(
            ctx.inscricoes_em,
            arquivo.Inscricao(
                _disponivel(ctx.achar(corpo.repo)),
                corpo.versao,
                arquivo.parse_intervalo(arquivo.INTERVALO_PADRAO),
            ),
        )

    @app.delete("/api/inscricoes", status_code=HTTPStatus.NO_CONTENT)
    def remover(corpo: PedidoRemover) -> None:
        arquivo.remover(ctx.inscricoes_em, corpo.repo, corpo.versao)


def _rotas_estaticos(app: FastAPI, estaticos: Path) -> None:
    raiz = estaticos.resolve()

    @app.get("/{caminho:path}", include_in_schema=False)
    def estatico(caminho: str) -> FileResponse:
        if caminho == "api" or caminho.startswith("api/"):
            raise NaoEncontrado(f"rota /{caminho} não existe")
        alvo = (raiz / caminho).resolve()
        # Fronteira de confiança: o caminho vem da URL e não pode sair de `raiz`.
        if alvo.is_relative_to(raiz) and alvo.is_file():
            return FileResponse(alvo)
        return FileResponse(raiz / "index.html")


def criar_app(
    fabrica: Callable[[RelatorProgresso], Runners],
    *,
    porta: int,
    estaticos: Path,
    inscricoes_em: Path,
    versionamento_repo: VersionamentoLoader = versionamento_do_repo,
) -> FastAPI:
    app = FastAPI()
    ctx = _Contexto(fabrica, versionamento_repo, inscricoes_em)
    app.state.execucoes = ctx.execucoes  # gancho dos testes
    proteger(app, porta)

    # MotorError fica no ExceptionMiddleware, que não relança: erro esperado sai limpo.
    @app.exception_handler(MotorError)
    async def tratar(_: Request, erro: MotorError) -> Response:
        status, corpo = erro_api(erro)
        return JSONResponse(asdict(corpo), status_code=status)

    # Exception fica no ServerErrorMiddleware, que relança: o uvicorn loga o traceback.
    @app.exception_handler(Exception)
    async def tratar_interno(_: Request, _erro: Exception) -> Response:
        corpo = ErroApi(TipoErro.INTERNO, MENSAGEM_INTERNA)
        return JSONResponse(asdict(corpo), status_code=HTTPStatus.INTERNAL_SERVER_ERROR)

    @app.exception_handler(RequestValidationError)
    async def tratar_validacao(_: Request, erro: RequestValidationError) -> Response:
        campos = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in erro.errors()
        )
        corpo = ErroApi(TipoErro.ENTRADA, f"requisição inválida ({campos})")
        return JSONResponse(asdict(corpo), status_code=HTTPStatus.UNPROCESSABLE_ENTITY)

    _rotas_repos(app, ctx)
    _rotas_operacoes(app, ctx)
    _rotas_execucao(app, ctx)
    _rotas_inscricoes(app, ctx)
    _rotas_estaticos(app, estaticos)
    return app


def _abrir_navegador(url: str) -> None:
    import webbrowser

    webbrowser.open(url)


def _rodar(app: FastAPI, porta: int) -> None:
    import threading

    import uvicorn

    # Atrasa a abertura para o servidor já estar de pé; sem bloquear o uvicorn.
    abrir = threading.Timer(
        ATRASO_NAVEGADOR_S, _abrir_navegador, [f"http://127.0.0.1:{porta}/"]
    )
    abrir.daemon = True
    abrir.start()
    uvicorn.run(app, host="127.0.0.1", port=porta)


def servir(porta: int) -> None:
    import socket

    with socket.socket() as sonda:
        # Sem isto, o TIME_WAIT de um daemon recém-parado parece porta ocupada;
        # um processo escutando continua recusando o bind no Linux.
        sonda.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sonda.bind(("127.0.0.1", porta))
        except OSError as erro:
            raise ErroDeEntrada(f"porta {porta} em uso; use --porta") from erro
    app = criar_app(
        runners_com_progresso,
        porta=porta,
        estaticos=PASTA_ESTATICOS,
        inscricoes_em=arquivo.caminho_arquivo(),
    )
    _rodar(app, porta)
