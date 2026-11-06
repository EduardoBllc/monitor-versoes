"""API HTTP do daemon: traduz rotas para os `Runners` e roda as operações longas em `Execucoes`."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from http import HTTPStatus
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from motor import inscricoes as arquivo
from motor.daemon.erros import ErroApi, TipoErro, erro_api
from motor.daemon.execucoes import EstadoExecucao, Execucao, Execucoes, Operacao
from motor.daemon.seguranca import proteger
from motor.domain.inscricao import UltimaExecucao
from motor.domain.types import VersionStatus
from motor.engine.atualizar import AtualizarResult
from motor.engine.consultar import ChamadoConsultado
from motor.errors import NaoEncontrado, RecusaDeInvariante
from motor.montagem import validar_nome_repo
from motor.operacoes import (
    RepoOption,
    Runners,
    VersionamentoLoader,
    VersionOption,
    avaliar_numero,
    versionamento_do_repo,
)
from motor.progresso import RelatorProgresso, silencioso
from motor.services.versionamento import Versionamento

INTERVALO_EVENTOS_S = 0.1
MENSAGEM_INDISPONIVEL = "operação indisponível neste ambiente"


class EventoSse(StrEnum):
    PROGRESSO = "progresso"
    FIM = "fim"


@dataclass(frozen=True)
class NovoRepo:
    nome: str


@dataclass(frozen=True)
class NumeroVersao:
    numero: str


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
    clone: str
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
    clone: str
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
    ambiente: str
    execucoes: Execucoes = field(default_factory=Execucoes)

    def leitura(self) -> Runners:
        return self.fabrica(silencioso)

    def achar(self, nome: str) -> RepoOption:
        for repo in self.leitura().carregar_repos():
            if repo.nome == nome:
                return repo
        raise NaoEncontrado(f"repo {nome} não cadastrado")

    def versionamento(self, runners: Runners, repo: RepoOption) -> Versionamento:
        return (runners.versionamento_repo or self.versionamento_repo)(repo)

    def disparar(
        self,
        nome: str,
        versao: str,
        operacao: Operacao,
        usar: Callable[[Runners, RepoOption], VersionStatus | AtualizarResult | None],
    ) -> Execucao:
        repo = self.achar(nome)

        def alvo(relatar: RelatorProgresso) -> VersionStatus | AtualizarResult | None:
            return usar(self.fabrica(relatar), repo)

        return self.execucoes.iniciar(nome, versao, operacao, alvo)


def _rotas_repos(app: FastAPI, ctx: _Contexto) -> None:
    @app.get("/api/repos")
    def listar_repos() -> list[RepoOption]:
        return ctx.leitura().carregar_repos()

    @app.post("/api/repos", status_code=HTTPStatus.NO_CONTENT)
    def cadastrar_repo(corpo: NovoRepo) -> None:
        _exigir(ctx.leitura().registrar_repo)(validar_nome_repo(corpo.nome))

    @app.get("/api/repos/{repo}/versoes")
    def listar_versoes(repo: str) -> list[VersionOption]:
        return ctx.leitura().carregar_versoes(ctx.achar(repo))

    @app.get("/api/repos/{repo}/versoes/sugestoes")
    def sugerir(repo: str) -> list[Sugestao]:
        runners = ctx.leitura()
        opcao = ctx.achar(repo)
        esquema = ctx.versionamento(runners, opcao).esquema
        existentes = [v.numero for v in runners.carregar_versoes(opcao)]
        return [Sugestao(n, esquema.tipo(n)) for n in esquema.sugerir(existentes)]

    @app.post("/api/repos/{repo}/versoes/avaliacao")
    def avaliar(repo: str, corpo: NumeroVersao) -> Avaliacao:
        runners = ctx.leitura()
        opcao = ctx.achar(repo)
        existentes = [v.numero for v in runners.carregar_versoes(opcao)]
        previa, erro = avaliar_numero(
            ctx.versionamento(runners, opcao), existentes, corpo.numero
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


def _clone_de(opcao: RepoOption) -> str:
    if opcao.caminho is None:
        raise NaoEncontrado("checkout local não encontrado")
    return os.path.abspath(opcao.caminho)


def _rotas_inscricoes(app: FastAPI, ctx: _Contexto) -> None:
    @app.get("/api/inscricoes")
    def listar_inscricoes() -> list[InscricaoVista]:
        return [
            InscricaoVista(
                i.clone, i.versao, arquivo.formatar_intervalo(i.intervalo), i.ultima
            )
            for i in arquivo.carregar(ctx.inscricoes_em)
        ]

    @app.post("/api/inscricoes", status_code=HTTPStatus.NO_CONTENT)
    def inscrever(corpo: PedidoInscrever) -> None:
        arquivo.inscrever(
            ctx.inscricoes_em,
            arquivo.Inscricao(
                _clone_de(ctx.achar(corpo.repo)),
                corpo.versao,
                arquivo.parse_intervalo(arquivo.INTERVALO_PADRAO),
                str(Path.cwd()),
                ctx.ambiente,
            ),
        )

    @app.delete("/api/inscricoes", status_code=HTTPStatus.NO_CONTENT)
    def remover(corpo: PedidoRemover) -> None:
        arquivo.remover(ctx.inscricoes_em, corpo.clone, corpo.versao)


def criar_app(  # noqa: PLR0913
    fabrica: Callable[[RelatorProgresso], Runners],
    *,
    porta: int,
    estaticos: Path,
    inscricoes_em: Path,
    ambiente: str,
    versionamento_repo: VersionamentoLoader = versionamento_do_repo,
) -> FastAPI:
    app = FastAPI()
    app.state.estaticos = estaticos  # a Tarefa 6 monta
    ctx = _Contexto(fabrica, versionamento_repo, inscricoes_em, ambiente)
    app.state.execucoes = ctx.execucoes  # gancho dos testes
    proteger(app, porta)

    @app.exception_handler(Exception)
    async def tratar(_: Request, erro: Exception) -> Response:
        status, corpo = erro_api(erro)
        return JSONResponse(asdict(corpo), status_code=status)

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
    return app
