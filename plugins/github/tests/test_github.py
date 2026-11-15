from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from enum import StrEnum

import httpx
import pytest
from monitor_versoes_github import FonteGithub
from monitor_versoes_github.fonte import ChaveTarefas, VarGithub

from motor.config import Chave, Tabela
from motor.config_edicao import catalogo_campos
from motor.domain.commits import extrair_chamado
from motor.domain.referencia import Referencia
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida
from motor.montagem import GRUPO_TAREFAS
from motor.plugins import carregar_plugin
from motor.ports import TaskSource

_: type[TaskSource] = FonteGithub


class _Plugin(StrEnum):
    GITHUB = "github"


class _Cabecalho(StrEnum):
    ACCEPT = "Accept"
    VERSAO_API = "X-GitHub-Api-Version"
    AUTH = "Authorization"
    LINK = "Link"
    RESTANTE = "x-ratelimit-remaining"
    RETRY_AFTER = "retry-after"


class _Param(StrEnum):
    STATE = "state"
    MILESTONE = "milestone"
    POR_PAGINA = "per_page"
    PAGINA = "page"


class _Item(StrEnum):
    NUMBER = "number"
    TITLE = "title"
    STATE = "state"
    PULL_REQUEST = "pull_request"


ACCEPT = "application/vnd.github+json"
VERSAO_API = "2022-11-28"
TODOS = "all"
FECHADA = "closed"
POR_PAGINA = "100"
HOST_PADRAO = "api.github.com"
API = f"https://{HOST_PADRAO}"
REPO = "dono/nome"
TOKEN = "tok"
BEARER = f"Bearer {TOKEN}"
VERSAO = "v1.2.0"
MILESTONE = 7
CAMINHO_MILESTONES = f"/repos/{REPO}/milestones"
CAMINHO_ISSUES = f"/repos/{REPO}/issues"
CAMINHO_EU = "/user"
ARQUIVO = "c.toml"
LIMITE = "limite"
ENV: dict[str, str] = {VarGithub.TOKEN: TOKEN}
TAREFAS: dict[str, str] = {ChaveTarefas.REPO: REPO}


def test_entry_point_github_carrega_a_fonte() -> None:
    assert carregar_plugin(GRUPO_TAREFAS, _Plugin.GITHUB) is FonteGithub


def test_construir_sem_config_nao_faz_io() -> None:
    def falha(request: httpx.Request) -> httpx.Response:
        pytest.fail("construir não pode fazer I/O")

    client = httpx.Client(transport=httpx.MockTransport(falha))
    FonteGithub(tarefas={}, arquivos=(), env={}, client=client)


def test_referencia_e_o_numero_da_issue() -> None:
    ref = FonteGithub(tarefas={}, arquivos=()).referencia
    assert ref == Referencia("#{id}", "0-9")
    assert extrair_chamado("#123-fix corrige x", ref) == "123"


def test_campos_aparecem_no_catalogo() -> None:
    campos = {
        c.chave: c
        for c in catalogo_campos({Tabela.TAREFAS: {Chave.FONTE: _Plugin.GITHUB}})
        if c.origem == _Plugin.GITHUB
    }
    assert set(campos) == {*ChaveTarefas, *VarGithub}
    assert campos[VarGithub.TOKEN].segredo
    assert campos[VarGithub.TOKEN].aviso_vazio


def _pagina(*itens: Mapping[str, object], proxima: str | None = None) -> httpx.Response:
    headers: dict[str, str] = (
        {_Cabecalho.LINK: f'<{proxima}>; rel="next"'} if proxima else {}
    )
    return httpx.Response(httpx.codes.OK, json=list(itens), headers=headers)


def _milestone(numero: int, titulo: str) -> dict[str, object]:
    return {_Item.NUMBER: numero, _Item.TITLE: titulo, _Item.STATE: FECHADA}


def _fonte(
    rotas: Mapping[str, list[httpx.Response]]
    | Callable[[httpx.Request], httpx.Response],
    *,
    tarefas: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[FonteGithub, list[httpx.Request]]:
    """Fonte com client falso; `rotas` responde em ordem por caminho da URL."""
    pedidos: list[httpx.Request] = []
    filas = (
        {caminho: iter(r) for caminho, r in rotas.items()}
        if isinstance(rotas, Mapping)
        else None
    )

    def handler(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        if filas is None:
            assert callable(rotas)
            return rotas(request)
        return next(filas[request.url.path])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fonte = FonteGithub(
        tarefas=TAREFAS if tarefas is None else tarefas,
        arquivos=(ARQUIVO,),
        env=ENV if env is None else env,
        client=client,
    )
    return fonte, pedidos


def _rotas_simples(
    *issues: Mapping[str, object],
) -> dict[str, list[httpx.Response]]:
    return {
        CAMINHO_MILESTONES: [_pagina(_milestone(MILESTONE, VERSAO))],
        CAMINHO_ISSUES: [_pagina(*issues)],
    }


def test_fetch_junta_paginas_e_descarta_prs() -> None:
    proxima_ms = (
        f"{API}{CAMINHO_MILESTONES}?{_Param.STATE}={TODOS}"
        f"&{_Param.POR_PAGINA}={POR_PAGINA}&{_Param.PAGINA}=2"
    )
    proxima_is = (
        f"{API}{CAMINHO_ISSUES}?{_Param.MILESTONE}={MILESTONE}&{_Param.STATE}={TODOS}"
        f"&{_Param.POR_PAGINA}={POR_PAGINA}&{_Param.PAGINA}=2"
    )
    fonte, pedidos = _fonte(
        {
            CAMINHO_MILESTONES: [
                _pagina(_milestone(1, "v1.1.0"), proxima=proxima_ms),
                _pagina(_milestone(MILESTONE, VERSAO)),
            ],
            CAMINHO_ISSUES: [
                _pagina(
                    {_Item.NUMBER: 1},
                    {_Item.NUMBER: 2, _Item.PULL_REQUEST: {}},
                    {_Item.NUMBER: 3},
                    proxima=proxima_is,
                ),
                _pagina({_Item.NUMBER: 3}, {_Item.NUMBER: 4}),
            ],
        }
    )
    assert fonte.fetch(VERSAO) == ["1", "3", "4"]
    ms1, ms2, is1, is2 = pedidos
    assert ms1.url.params[_Param.STATE] == TODOS
    assert is1.url.params[_Param.STATE] == TODOS
    assert is1.url.params[_Param.MILESTONE] == str(MILESTONE)
    assert str(ms2.url) == proxima_ms
    assert str(is2.url) == proxima_is
    for pedido in pedidos:
        assert pedido.url.params.get_list(_Param.POR_PAGINA) == [POR_PAGINA]
        assert pedido.headers[_Cabecalho.ACCEPT] == ACCEPT
        assert pedido.headers[_Cabecalho.VERSAO_API] == VERSAO_API
        assert pedido.headers[_Cabecalho.AUTH] == BEARER


@pytest.mark.parametrize(
    ("env", "auth"),
    [
        ({}, None),
        ({VarGithub.TOKEN: "  "}, None),
        ({VarGithub.TOKEN: f" {TOKEN}\n"}, BEARER),
    ],
)
def test_fetch_token_opcional(env: dict[str, str], auth: str | None) -> None:
    fonte, pedidos = _fonte(_rotas_simples({_Item.NUMBER: 1}), env=env)
    assert fonte.fetch(VERSAO) == ["1"]
    for pedido in pedidos:
        assert pedido.headers.get(_Cabecalho.AUTH) == auth
        assert pedido.headers[_Cabecalho.ACCEPT] == ACCEPT


@pytest.mark.parametrize(
    ("api_url", "host", "prefixo"),
    [
        (None, HOST_PADRAO, ""),
        ("https://ghe.x/api/v3/", "ghe.x", "/api/v3"),
    ],
)
def test_fetch_api_url(api_url: str | None, host: str, prefixo: str) -> None:
    tarefas = dict(TAREFAS)
    if api_url is not None:
        tarefas[ChaveTarefas.API_URL] = api_url

    def rota(request: httpx.Request) -> httpx.Response:
        sem_prefixo = request.url.path.removeprefix(prefixo)
        return next(filas[sem_prefixo])

    filas = {c: iter(r) for c, r in _rotas_simples().items()}
    fonte, pedidos = _fonte(rota, tarefas=tarefas)
    fonte.fetch(VERSAO)
    assert pedidos[0].url.host == host
    assert pedidos[0].url.path == prefixo + CAMINHO_MILESTONES


def test_fetch_milestone_sem_issues_devolve_vazio() -> None:
    fonte, _ = _fonte(_rotas_simples())
    assert fonte.fetch(VERSAO) == []


@pytest.mark.parametrize(
    ("tarefas", "termos"),
    [
        ({}, [f"[{Tabela.TAREFAS}] {ChaveTarefas.REPO}", ARQUIVO]),
        (
            {ChaveTarefas.REPO: "  "},
            [f"[{Tabela.TAREFAS}] {ChaveTarefas.REPO}", ARQUIVO],
        ),
        (
            {**TAREFAS, ChaveTarefas.API_URL: "http://ghe.x"},
            [ChaveTarefas.API_URL, "https://"],
        ),
    ],
)
def test_fetch_config_invalida_nao_faz_pedido(
    tarefas: dict[str, str], termos: list[str]
) -> None:
    fonte, pedidos = _fonte({}, tarefas=tarefas)
    with pytest.raises(ErroDeEntrada, match=_todos(termos)):
        fonte.fetch(VERSAO)
    assert pedidos == []


def _todos(termos: list[str]) -> str:
    return "(?s)" + "".join(f"(?=.*{re.escape(t)})" for t in termos)


def _conexao_recusada(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("recusou", request=request)


def _status(
    codigo: int, headers: Mapping[str, str] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _r: httpx.Response(codigo, headers=headers)


def _issues(
    *issues: Mapping[str, object],
) -> Callable[[httpx.Request], httpx.Response]:
    filas = {c: iter(r) for c, r in _rotas_simples(*issues).items()}
    return lambda r: next(filas[r.url.path])


def _proxima_repetida() -> Callable[[httpx.Request], httpx.Response]:
    repetida = f"{API}{CAMINHO_MILESTONES}?{_Param.PAGINA}=2"
    paginas = iter([_pagina(_milestone(1, "x"), proxima=repetida)] * 2)
    return lambda _r: next(paginas)


@pytest.mark.parametrize(
    ("resposta", "env", "erro", "termos"),
    [
        (_status(httpx.codes.UNAUTHORIZED), ENV, ErroDeEntrada, [VarGithub.TOKEN]),
        (
            _status(httpx.codes.UNAUTHORIZED),
            {},
            ErroDeEntrada,
            [REPO, "autenticação", VarGithub.TOKEN],
        ),
        (_status(httpx.codes.FORBIDDEN), ENV, ErroDeEntrada, [REPO, VarGithub.TOKEN]),
        (
            _status(httpx.codes.FORBIDDEN, {_Cabecalho.RESTANTE: "0"}),
            ENV,
            BackendIndisponivel,
            [LIMITE],
        ),
        (
            _status(httpx.codes.FORBIDDEN, {_Cabecalho.RETRY_AFTER: "60"}),
            ENV,
            BackendIndisponivel,
            [LIMITE],
        ),
        (_status(httpx.codes.TOO_MANY_REQUESTS), ENV, BackendIndisponivel, [LIMITE]),
        (
            _status(httpx.codes.NOT_FOUND),
            ENV,
            ErroDeEntrada,
            [REPO, f"[{Tabela.TAREFAS}] {ChaveTarefas.REPO}"],
        ),
        (_status(httpx.codes.INTERNAL_SERVER_ERROR), ENV, BackendIndisponivel, []),
        (_conexao_recusada, ENV, BackendIndisponivel, []),
        (
            lambda _r: httpx.Response(httpx.codes.OK, text="<html>"),
            ENV,
            RespostaInvalida,
            [],
        ),
        (
            lambda _r: httpx.Response(httpx.codes.OK, json={}),
            ENV,
            RespostaInvalida,
            [],
        ),
        (
            lambda _r: _pagina(_milestone(MILESTONE, VERSAO.upper())),
            ENV,
            ErroDeEntrada,
            [VERSAO, REPO],
        ),
        (_issues({_Item.TITLE: "sem número"}), ENV, RespostaInvalida, []),
        (_issues({_Item.NUMBER: True}), ENV, RespostaInvalida, []),
        (_proxima_repetida(), ENV, RespostaInvalida, []),
    ],
)
def test_fetch_traduz_respostas(
    resposta: Callable[[httpx.Request], httpx.Response],
    env: dict[str, str],
    erro: type[Exception],
    termos: list[str],
) -> None:
    fonte, _ = _fonte(resposta, env=env)
    with pytest.raises(erro, match=_todos(termos)):
        fonte.fetch(VERSAO)


def test_verificar_credenciais_sem_token_nao_verifica() -> None:
    fonte, pedidos = _fonte({}, env={})
    motivo = fonte.verificar_credenciais()
    assert motivo is not None
    assert VarGithub.TOKEN in motivo
    assert pedidos == []


def test_verificar_credenciais_ok_sem_repo() -> None:
    fonte, pedidos = _fonte(
        {CAMINHO_EU: [httpx.Response(httpx.codes.OK, json={})]}, tarefas={}
    )
    assert fonte.verificar_credenciais() is None
    assert pedidos[0].url.path == CAMINHO_EU
    assert pedidos[0].headers[_Cabecalho.AUTH] == BEARER


def test_verificar_credenciais_recusada() -> None:
    fonte, _ = _fonte(_status(httpx.codes.UNAUTHORIZED), tarefas={})
    with pytest.raises(ErroDeEntrada, match=_todos([VarGithub.TOKEN])):
        fonte.verificar_credenciais()
