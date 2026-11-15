from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from enum import StrEnum

import httpx
import pytest
from monitor_versoes_gitlab import FonteGitlab
from monitor_versoes_gitlab.fonte import ChaveTarefas, VarGitlab

from motor.config import TABELA_AMBIENTE, Chave, Tabela
from motor.config_edicao import catalogo_campos
from motor.domain.commits import extrair_chamado
from motor.domain.referencia import Referencia
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida
from motor.montagem import GRUPO_TAREFAS
from motor.plugins import carregar_plugin
from motor.ports import TaskSource

_: type[TaskSource] = FonteGitlab


class _Plugin(StrEnum):
    GITLAB = "gitlab"


class _Cabecalho(StrEnum):
    TOKEN = "PRIVATE-TOKEN"
    AUTH = "Authorization"
    LINK = "Link"


class _Param(StrEnum):
    TITLE = "title"
    ANCESTRAIS = "include_ancestors"
    MILESTONE = "milestone"
    ESCOPO = "scope"
    STATE = "state"
    POR_PAGINA = "per_page"
    PAGINA = "page"


class _Item(StrEnum):
    ID = "id"
    IID = "iid"
    TITLE = "title"
    STATE = "state"
    GRUPO = "group_id"


VERDADE = "true"
TODOS = "all"
FECHADA = "closed"
POR_PAGINA = "100"
HTTPS = "https://"
HTTP = "http://"
HOST_PADRAO = "gitlab.com"
HOST_OUTRO = "outro.x"
HOST_PROPRIO = "git.x"
PORTA_OUTRA = 8443
BASE = f"{HTTPS}{HOST_PADRAO}"
PREFIXO_PROPRIO = "/gitlab"
URL_PROPRIA = f"{HTTPS}{HOST_PROPRIO}{PREFIXO_PROPRIO}"
API = "/api/v4"
PROJETO = "grupo/sub/projeto"
PROJETO_CODIFICADO = "grupo%2Fsub%2Fprojeto"
PROJETO_ID = "123"
CAMINHO_PROJETO = f"{API}/projects/{PROJETO}"
MILESTONES = "milestones"
ISSUES = "issues"
CAMINHO_MILESTONES = f"{CAMINHO_PROJETO}/{MILESTONES}"
CAMINHO_ISSUES = f"{CAMINHO_PROJETO}/{ISSUES}"
URL_PROJETO = f"{BASE}{API}/projects/{PROJETO_CODIFICADO}"
CAMINHO_EU = f"{API}/user"
TOKEN = "tok"
VERSAO = "v1.2.0"
GRUPO = 9970
ISSUE, REPETIDA, ULTIMA = 1, 3, 4
ID_GLOBAL = 900
PAGINA_SEGUINTE = 2
PAGINAS_MAXIMAS = 3
PAGINA_2_ISSUES = (
    f"{API}/projects/{PROJETO_ID}/{ISSUES}?{_Param.PAGINA}={PAGINA_SEGUINTE}"
)
ARQUIVO = "c.toml"
BRANCO = "  "
LIMITE = "limite"
AUTENTICACAO = "autenticação"
A_CONTA = "à conta"
HTML = "<html>"
FORMATO_REF = "#{id}"
ALFABETO = "0-9"
CHAMADO = "123"
MENSAGEM_COM_CHAMADO = f"#{CHAMADO}-fix corrige x"
ENV: dict[str, str] = {VarGitlab.TOKEN: TOKEN}
TAREFAS: dict[str, str] = {ChaveTarefas.PROJETO: PROJETO}


def test_entry_point_gitlab_carrega_a_fonte() -> None:
    assert carregar_plugin(GRUPO_TAREFAS, _Plugin.GITLAB) is FonteGitlab


def test_construir_sem_config_nao_faz_io() -> None:
    def falha(request: httpx.Request) -> httpx.Response:
        pytest.fail("construir não pode fazer I/O")

    client = httpx.Client(transport=httpx.MockTransport(falha))
    FonteGitlab(tarefas={}, arquivos=(), env={}, client=client)


def test_referencia_e_o_iid_da_issue() -> None:
    ref = FonteGitlab(tarefas={}, arquivos=()).referencia
    assert ref == Referencia(FORMATO_REF, ALFABETO)
    assert extrair_chamado(MENSAGEM_COM_CHAMADO, ref) == CHAMADO


def test_campos_aparecem_no_catalogo() -> None:
    campos = {
        c.chave: c
        for c in catalogo_campos({Tabela.TAREFAS: {Chave.FONTE: _Plugin.GITLAB}})
        if c.origem == _Plugin.GITLAB
    }
    assert set(campos) == {*ChaveTarefas, *VarGitlab}
    assert campos[VarGitlab.TOKEN].segredo
    assert campos[VarGitlab.TOKEN].aviso_vazio
    assert campos[ChaveTarefas.URL].padrao == BASE


def _pagina(*itens: Mapping[str, object], proxima: str | None = None) -> httpx.Response:
    headers: dict[str, str] = (
        {_Cabecalho.LINK: f'<{proxima}>; rel="next"'} if proxima else {}
    )
    return httpx.Response(httpx.codes.OK, json=list(itens), headers=headers)


def _milestone(titulo: str) -> dict[str, object]:
    return {_Item.TITLE: titulo, _Item.STATE: FECHADA, _Item.GRUPO: GRUPO}


def _fonte(
    rotas: Mapping[str, list[httpx.Response]]
    | Callable[[httpx.Request], httpx.Response],
    *,
    tarefas: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[FonteGitlab, list[httpx.Request]]:
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
    fonte = FonteGitlab(
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
        CAMINHO_MILESTONES: [_pagina(_milestone(VERSAO))],
        CAMINHO_ISSUES: [_pagina(*issues)],
    }


def test_fetch_junta_paginas_pelo_iid() -> None:
    proxima = (
        f"{URL_PROJETO}/{ISSUES}?{_Param.MILESTONE}={VERSAO}&{_Param.ESCOPO}={TODOS}"
        f"&{_Param.POR_PAGINA}={POR_PAGINA}&{_Param.PAGINA}={PAGINA_SEGUINTE}"
    )
    fonte, pedidos = _fonte(
        {
            CAMINHO_MILESTONES: [_pagina(_milestone(VERSAO))],
            CAMINHO_ISSUES: [
                _pagina(
                    {_Item.ID: ID_GLOBAL + ISSUE, _Item.IID: ISSUE},
                    {_Item.ID: ID_GLOBAL + REPETIDA, _Item.IID: REPETIDA},
                    proxima=proxima,
                ),
                _pagina(
                    {_Item.ID: ID_GLOBAL + REPETIDA, _Item.IID: REPETIDA},
                    {_Item.ID: ID_GLOBAL + ULTIMA, _Item.IID: ULTIMA},
                ),
            ],
        }
    )
    assert fonte.fetch(VERSAO) == [str(n) for n in (ISSUE, REPETIDA, ULTIMA)]
    ms, is1, is2 = pedidos
    assert ms.url.params[_Param.TITLE] == VERSAO
    assert ms.url.params[_Param.ANCESTRAIS] == VERDADE
    assert is1.url.params[_Param.MILESTONE] == VERSAO
    assert is1.url.params[_Param.ESCOPO] == TODOS
    assert _Param.STATE not in is1.url.params
    assert str(is2.url) == proxima
    for pedido in pedidos:
        assert pedido.url.params.get_list(_Param.POR_PAGINA) == [POR_PAGINA]
        assert pedido.headers[_Cabecalho.TOKEN] == TOKEN
        assert _Cabecalho.AUTH not in pedido.headers


@pytest.mark.parametrize(
    ("projeto", "segmento"),
    [(PROJETO, PROJETO_CODIFICADO), (PROJETO_ID, PROJETO_ID)],
)
def test_fetch_projeto_vira_um_segmento(projeto: str, segmento: str) -> None:
    fonte, pedidos = _fonte(
        lambda r: (
            _pagina(_milestone(VERSAO))
            if r.url.path.endswith(MILESTONES)
            else _pagina()
        ),
        tarefas={ChaveTarefas.PROJETO: projeto},
    )
    fonte.fetch(VERSAO)
    assert pedidos[0].url.raw_path.startswith(
        f"{API}/projects/{segmento}/{MILESTONES}?".encode()
    )


@pytest.mark.parametrize(
    ("env", "token", "caminhos"),
    [
        ({}, None, [CAMINHO_ISSUES]),
        ({VarGitlab.TOKEN: BRANCO}, None, [CAMINHO_ISSUES]),
        ({VarGitlab.TOKEN: f" {TOKEN}\n"}, TOKEN, [CAMINHO_MILESTONES, CAMINHO_ISSUES]),
    ],
)
def test_fetch_token_opcional(
    env: dict[str, str], token: str | None, caminhos: list[str]
) -> None:
    fonte, pedidos = _fonte(_rotas_simples({_Item.IID: ISSUE}), env=env)
    assert fonte.fetch(VERSAO) == [str(ISSUE)]
    assert [p.url.path for p in pedidos] == caminhos
    for pedido in pedidos:
        assert pedido.headers.get(_Cabecalho.TOKEN) == token
        assert _Cabecalho.AUTH not in pedido.headers


@pytest.mark.parametrize(
    ("url", "host", "prefixo"),
    [
        (None, HOST_PADRAO, ""),
        (f"{URL_PROPRIA}/", HOST_PROPRIO, PREFIXO_PROPRIO),
    ],
)
def test_fetch_url(url: str | None, host: str, prefixo: str) -> None:
    tarefas = dict(TAREFAS)
    if url is not None:
        tarefas[ChaveTarefas.URL] = url

    def rota(request: httpx.Request) -> httpx.Response:
        return next(filas[request.url.path.removeprefix(prefixo)])

    filas = {c: iter(r) for c, r in _rotas_simples().items()}
    fonte, pedidos = _fonte(rota, tarefas=tarefas)
    fonte.fetch(VERSAO)
    assert pedidos[0].url.host == host
    assert pedidos[0].url.path == prefixo + CAMINHO_MILESTONES


def test_fetch_milestone_sem_issues_devolve_vazio() -> None:
    fonte, _ = _fonte(_rotas_simples())
    assert fonte.fetch(VERSAO) == []


def test_fetch_sem_token_milestone_inexistente_devolve_vazio() -> None:
    fonte, _ = _fonte({CAMINHO_ISSUES: [_pagina()]}, env={})
    assert fonte.fetch(VERSAO) == []


def test_fetch_milestone_inexistente_nao_pede_issues() -> None:
    fonte, pedidos = _fonte({CAMINHO_MILESTONES: [_pagina()]})
    with pytest.raises(ErroDeEntrada, match=_todos([VERSAO, PROJETO])):
        fonte.fetch(VERSAO)
    assert [p.url.path for p in pedidos] == [CAMINHO_MILESTONES]


@pytest.mark.parametrize(
    ("tarefas", "termos"),
    [
        ({}, [f"[{Tabela.TAREFAS}] {ChaveTarefas.PROJETO}", ARQUIVO]),
        (
            {ChaveTarefas.PROJETO: BRANCO},
            [f"[{Tabela.TAREFAS}] {ChaveTarefas.PROJETO}", ARQUIVO],
        ),
        (
            {**TAREFAS, ChaveTarefas.URL: f"{HTTP}{HOST_PROPRIO}"},
            [ChaveTarefas.URL, HTTPS],
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


def _status(codigo: int) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _r: httpx.Response(codigo)


def _issues(
    *issues: Mapping[str, object],
) -> Callable[[httpx.Request], httpx.Response]:
    filas = {c: iter(r) for c, r in _rotas_simples(*issues).items()}
    return lambda r: next(filas[r.url.path])


def _proxima_sempre(proxima: str) -> Callable[[httpx.Request], httpx.Response]:
    """Milestones e issues cuja página sempre aponta `proxima`; no máximo três."""
    paginas = iter([_pagina(_milestone(VERSAO), proxima=proxima)] * PAGINAS_MAXIMAS)
    return lambda _r: next(paginas)


@pytest.mark.parametrize(
    ("resposta", "env", "erro", "termos"),
    [
        (_status(httpx.codes.UNAUTHORIZED), ENV, ErroDeEntrada, [VarGitlab.TOKEN]),
        (
            _status(httpx.codes.UNAUTHORIZED),
            {},
            ErroDeEntrada,
            [PROJETO, AUTENTICACAO, VarGitlab.TOKEN],
        ),
        (
            _status(httpx.codes.FORBIDDEN),
            ENV,
            ErroDeEntrada,
            [PROJETO, VarGitlab.TOKEN],
        ),
        (_status(httpx.codes.TOO_MANY_REQUESTS), ENV, BackendIndisponivel, [LIMITE]),
        (
            _status(httpx.codes.NOT_FOUND),
            ENV,
            ErroDeEntrada,
            [PROJETO, f"[{Tabela.TAREFAS}] {ChaveTarefas.PROJETO}"],
        ),
        (
            _status(httpx.codes.NOT_FOUND),
            {},
            ErroDeEntrada,
            [PROJETO, f"[{TABELA_AMBIENTE}] {VarGitlab.TOKEN}"],
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
        (_issues({_Item.ID: ID_GLOBAL}), ENV, RespostaInvalida, []),
        (_issues({_Item.IID: True}), ENV, RespostaInvalida, []),
        (
            _proxima_sempre(
                f"{URL_PROJETO}/{MILESTONES}?{_Param.PAGINA}={PAGINA_SEGUINTE}"
            ),
            ENV,
            RespostaInvalida,
            [],
        ),
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
        return _pagina(_milestone(VERSAO), proxima=grafia)

    fonte, pedidos = _fonte(rota)
    with pytest.raises(RespostaInvalida):
        fonte.fetch(VERSAO)
    assert len(pedidos) == 1


@pytest.mark.parametrize(
    ("url", "proxima"),
    [
        (None, f"{HTTPS}{HOST_OUTRO}{PAGINA_2_ISSUES}"),
        (None, f"{HTTPS}{HOST_PADRAO}.{HOST_OUTRO}{PAGINA_2_ISSUES}"),
        (None, f"{HTTP}{HOST_PADRAO}{PAGINA_2_ISSUES}"),
        (None, f"{HTTPS}{HOST_PADRAO}:{PORTA_OUTRA}{PAGINA_2_ISSUES}"),
        (URL_PROPRIA, f"{HTTPS}{HOST_PROPRIO}/{HOST_OUTRO}{PAGINA_2_ISSUES}"),
    ],
)
def test_fetch_nao_segue_proxima_fora_da_base(url: str | None, proxima: str) -> None:
    tarefas = dict(TAREFAS)
    if url is not None:
        tarefas[ChaveTarefas.URL] = url
    fonte, pedidos = _fonte(
        lambda _r: _pagina(_milestone(VERSAO), proxima=proxima), tarefas=tarefas
    )
    with pytest.raises(RespostaInvalida):
        fonte.fetch(VERSAO)
    assert len(pedidos) == 1


def test_verificar_credenciais_sem_token_nao_verifica() -> None:
    fonte, pedidos = _fonte({}, env={})
    motivo = fonte.verificar_credenciais()
    assert motivo is not None
    assert VarGitlab.TOKEN in motivo
    assert pedidos == []


def test_verificar_credenciais_ok_sem_projeto() -> None:
    fonte, pedidos = _fonte(
        {CAMINHO_EU: [httpx.Response(httpx.codes.OK, json={})]}, tarefas={}
    )
    assert fonte.verificar_credenciais() is None
    assert pedidos[0].url.path == CAMINHO_EU
    assert pedidos[0].headers[_Cabecalho.TOKEN] == TOKEN


@pytest.mark.parametrize(
    ("status", "termos", "ausente"),
    [
        (httpx.codes.UNAUTHORIZED, [VarGitlab.TOKEN], None),
        (httpx.codes.FORBIDDEN, [A_CONTA, VarGitlab.TOKEN], None),
        (
            httpx.codes.NOT_FOUND,
            [f"[{Tabela.TAREFAS}] {ChaveTarefas.URL}"],
            f"[{Tabela.TAREFAS}] {ChaveTarefas.PROJETO}",
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
