from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from enum import StrEnum

import httpx
import pytest
from monitor_versoes_github import FonteGithub
from monitor_versoes_github.fonte import ChaveTarefas, VarGithub

from motor.config import TABELA_AMBIENTE, Chave, Tabela
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
HTTPS = "https://"
HTTP = "http://"
HOST_PADRAO = "api.github.com"
HOST_OUTRO = "outro.x"
PORTA_OUTRA = 8443
API = f"{HTTPS}{HOST_PADRAO}"
HOST_GHE = "ghe.x"
CAMINHO_GHE = "/api/v3"
API_GHE = f"{HTTPS}{HOST_GHE}{CAMINHO_GHE}"
REPO = "dono/nome"
TOKEN = "tok"
BEARER = f"Bearer {TOKEN}"
VERSAO = "v1.2.0"
OUTRA_VERSAO = "v1.1.0"
MILESTONE = 7
OUTRO_MILESTONE = 1
ISSUE, PR, REPETIDA, ULTIMA = 1, 2, 3, 4
PAGINA_SEGUINTE = 2
PAGINAS_MAXIMAS = 3
CAMINHO_MILESTONES = f"/repos/{REPO}/milestones"
CAMINHO_ISSUES = f"/repos/{REPO}/issues"
PAGINA_2_ISSUES = f"{CAMINHO_ISSUES}?{_Param.PAGINA}={PAGINA_SEGUINTE}"
CAMINHO_EU = "/user"
ARQUIVO = "c.toml"
BRANCO = "  "
LIMITE = "limite"
AUTENTICACAO = "autenticação"
A_CONTA = "à conta"
RATE_ESGOTADO = "0"
RETRY_SEGUNDOS = "60"
HTML = "<html>"
SEM_NUMERO = "sem número"
FORMATO_REF = "#{id}"
ALFABETO = "0-9"
CHAMADO = "123"
MENSAGEM_COM_CHAMADO = f"#{CHAMADO}-fix corrige x"
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
    assert ref == Referencia(FORMATO_REF, ALFABETO)
    assert extrair_chamado(MENSAGEM_COM_CHAMADO, ref) == CHAMADO


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
        f"&{_Param.POR_PAGINA}={POR_PAGINA}&{_Param.PAGINA}={PAGINA_SEGUINTE}"
    )
    proxima_is = (
        f"{API}{CAMINHO_ISSUES}?{_Param.MILESTONE}={MILESTONE}&{_Param.STATE}={TODOS}"
        f"&{_Param.POR_PAGINA}={POR_PAGINA}&{_Param.PAGINA}={PAGINA_SEGUINTE}"
    )
    fonte, pedidos = _fonte(
        {
            CAMINHO_MILESTONES: [
                _pagina(_milestone(OUTRO_MILESTONE, OUTRA_VERSAO), proxima=proxima_ms),
                _pagina(_milestone(MILESTONE, VERSAO)),
            ],
            CAMINHO_ISSUES: [
                _pagina(
                    {_Item.NUMBER: ISSUE},
                    {_Item.NUMBER: PR, _Item.PULL_REQUEST: {}},
                    {_Item.NUMBER: REPETIDA},
                    proxima=proxima_is,
                ),
                _pagina({_Item.NUMBER: REPETIDA}, {_Item.NUMBER: ULTIMA}),
            ],
        }
    )
    assert fonte.fetch(VERSAO) == [str(n) for n in (ISSUE, REPETIDA, ULTIMA)]
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
        ({VarGithub.TOKEN: BRANCO}, None),
        ({VarGithub.TOKEN: f" {TOKEN}\n"}, BEARER),
    ],
)
def test_fetch_token_opcional(env: dict[str, str], auth: str | None) -> None:
    fonte, pedidos = _fonte(_rotas_simples({_Item.NUMBER: ISSUE}), env=env)
    assert fonte.fetch(VERSAO) == [str(ISSUE)]
    for pedido in pedidos:
        assert pedido.headers.get(_Cabecalho.AUTH) == auth
        assert pedido.headers[_Cabecalho.ACCEPT] == ACCEPT


@pytest.mark.parametrize(
    ("api_url", "host", "prefixo"),
    [
        (None, HOST_PADRAO, ""),
        (f"{API_GHE}/", HOST_GHE, CAMINHO_GHE),
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
            {ChaveTarefas.REPO: BRANCO},
            [f"[{Tabela.TAREFAS}] {ChaveTarefas.REPO}", ARQUIVO],
        ),
        (
            {**TAREFAS, ChaveTarefas.API_URL: f"{HTTP}{HOST_GHE}"},
            [ChaveTarefas.API_URL, HTTPS],
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
    raise httpx.ConnectError(HOST_OUTRO, request=request)


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
    repetida = f"{API}{CAMINHO_MILESTONES}?{_Param.PAGINA}={PAGINA_SEGUINTE}"
    paginas = iter(
        [_pagina(_milestone(MILESTONE, OUTRA_VERSAO), proxima=repetida)]
        * PAGINAS_MAXIMAS
    )
    return lambda _r: next(paginas)


@pytest.mark.parametrize(
    ("resposta", "env", "erro", "termos"),
    [
        (_status(httpx.codes.UNAUTHORIZED), ENV, ErroDeEntrada, [VarGithub.TOKEN]),
        (
            _status(httpx.codes.UNAUTHORIZED),
            {},
            ErroDeEntrada,
            [REPO, AUTENTICACAO, VarGithub.TOKEN],
        ),
        (_status(httpx.codes.FORBIDDEN), ENV, ErroDeEntrada, [REPO, VarGithub.TOKEN]),
        (
            _status(httpx.codes.FORBIDDEN, {_Cabecalho.RESTANTE: RATE_ESGOTADO}),
            ENV,
            BackendIndisponivel,
            [LIMITE],
        ),
        (
            _status(httpx.codes.FORBIDDEN, {_Cabecalho.RETRY_AFTER: RETRY_SEGUNDOS}),
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
        (
            _status(httpx.codes.NOT_FOUND),
            {},
            ErroDeEntrada,
            [REPO, f"[{TABELA_AMBIENTE}] {VarGithub.TOKEN}"],
        ),
        (_status(httpx.codes.INTERNAL_SERVER_ERROR), ENV, BackendIndisponivel, []),
        (_conexao_recusada, ENV, BackendIndisponivel, []),
        (
            lambda _r: httpx.Response(httpx.codes.OK, text=HTML),
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
        (_issues({_Item.TITLE: SEM_NUMERO}), ENV, RespostaInvalida, []),
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


def test_fetch_proxima_igual_a_pedida_em_outra_grafia() -> None:
    restantes = iter(range(PAGINA_SEGUINTE))

    def rota(request: httpx.Request) -> httpx.Response:
        next(restantes)
        # Mesma URL do pedido, com o host em caixa alta: só é igual normalizada.
        grafia = str(request.url).replace(HOST_PADRAO, HOST_PADRAO.upper())
        return _pagina(_milestone(OUTRO_MILESTONE, OUTRA_VERSAO), proxima=grafia)

    fonte, pedidos = _fonte(rota)
    with pytest.raises(RespostaInvalida):
        fonte.fetch(VERSAO)
    assert len(pedidos) == 1


@pytest.mark.parametrize(
    ("api_url", "proxima"),
    [
        (None, f"{HTTPS}{HOST_OUTRO}{PAGINA_2_ISSUES}"),
        (None, f"{HTTPS}{HOST_PADRAO}.{HOST_OUTRO}{PAGINA_2_ISSUES}"),
        (None, f"{HTTP}{HOST_PADRAO}{PAGINA_2_ISSUES}"),
        (None, f"{HTTPS}{HOST_PADRAO}:{PORTA_OUTRA}{PAGINA_2_ISSUES}"),
        (API_GHE, f"{HTTPS}{HOST_GHE}/{HOST_OUTRO}{PAGINA_2_ISSUES}"),
    ],
)
def test_fetch_nao_segue_proxima_fora_da_base(
    api_url: str | None, proxima: str
) -> None:
    tarefas = dict(TAREFAS)
    if api_url is not None:
        tarefas[ChaveTarefas.API_URL] = api_url
    fonte, pedidos = _fonte(
        lambda _r: _pagina(_milestone(OUTRO_MILESTONE, OUTRA_VERSAO), proxima=proxima),
        tarefas=tarefas,
    )
    with pytest.raises(RespostaInvalida):
        fonte.fetch(VERSAO)
    assert len(pedidos) == 1


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


@pytest.mark.parametrize(
    ("status", "termos", "ausente"),
    [
        (httpx.codes.UNAUTHORIZED, [VarGithub.TOKEN], None),
        (httpx.codes.FORBIDDEN, [A_CONTA, VarGithub.TOKEN], None),
        (
            httpx.codes.NOT_FOUND,
            [f"[{Tabela.TAREFAS}] {ChaveTarefas.API_URL}"],
            f"[{Tabela.TAREFAS}] {ChaveTarefas.REPO}",
        ),
    ],
)
def test_verificar_credenciais_recusada(
    status: int, termos: list[str], ausente: str | None
) -> None:
    fonte, _ = _fonte(_status(status), tarefas={})
    with pytest.raises(ErroDeEntrada, match=_todos(termos)) as erro:
        fonte.verificar_credenciais()
    if ausente is not None:
        assert ausente not in str(erro.value)
