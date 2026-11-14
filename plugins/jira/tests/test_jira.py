from __future__ import annotations

import base64
import re
from collections.abc import Callable

import httpx
import pytest
from monitor_versoes_jira import FonteJira
from monitor_versoes_jira.fonte import ChaveTarefas, VarJira

from motor.config_edicao import catalogo_campos
from motor.domain.commits import extrair_chamado
from motor.domain.referencia import Referencia
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida
from motor.montagem import GRUPO_TAREFAS
from motor.plugins import carregar_plugin
from motor.ports import TaskSource

_: type[TaskSource] = FonteJira


def test_entry_point_jira_carrega_a_fonte() -> None:
    assert carregar_plugin(GRUPO_TAREFAS, "jira") is FonteJira


def test_construir_sem_config_nao_faz_io() -> None:
    def falha(request: httpx.Request) -> httpx.Response:
        pytest.fail("construir não pode fazer I/O")

    client = httpx.Client(transport=httpx.MockTransport(falha))
    FonteJira(tarefas={}, arquivos=(), env={}, client=client)


def test_referencia_usa_o_projeto() -> None:
    fonte = FonteJira(tarefas={ChaveTarefas.PROJETO: "ABC"}, arquivos=())
    ref = fonte.referencia
    assert ref == Referencia("ABC-{id}", "0-9")
    assert extrair_chamado("ABC-123 corrige x", ref) == "123"
    assert extrair_chamado("ABC-12 corrige x", ref) == "12"


def test_referencia_sem_projeto_pede_a_chave() -> None:
    with pytest.raises(ErroDeEntrada, match=re.escape("[tarefas] projeto")):
        _ = FonteJira(tarefas={}, arquivos=("a.toml",)).referencia


def test_campos_aparecem_no_catalogo() -> None:
    campos = {
        c.chave: c
        for c in catalogo_campos({"tarefas": {"fonte": "jira"}})
        if c.origem == "jira"
    }
    assert set(campos) == {*ChaveTarefas, *VarJira}
    assert campos[VarJira.TOKEN].segredo


URL = "https://x.atlassian.net"
ENV: dict[str, str] = {VarJira.EMAIL: "e@x", VarJira.TOKEN: "tok"}
TAREFAS: dict[str, str] = {ChaveTarefas.URL: URL, ChaveTarefas.PROJETO: "ABC"}
BASIC = "Basic " + base64.b64encode(b"e@x:tok").decode()


def _fonte(
    resposta: Callable[[httpx.Request], httpx.Response] | list[httpx.Response],
    *,
    tarefas: dict[str, str] | None = None,
    env: dict[str, str] | None = None,
) -> tuple[FonteJira, list[httpx.Request]]:
    pedidos: list[httpx.Request] = []
    respostas = iter(resposta) if isinstance(resposta, list) else None

    def handler(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        if respostas is not None:
            return next(respostas)
        assert callable(resposta)
        return resposta(request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fonte = FonteJira(
        tarefas=TAREFAS if tarefas is None else tarefas,
        arquivos=("c.toml",),
        env=ENV if env is None else env,
        client=client,
    )
    return fonte, pedidos


def _pagina(*chaves: str, proxima: str | None = None) -> httpx.Response:
    corpo: dict[str, object] = {
        "issues": [{"key": k} for k in chaves],
        "isLast": proxima is None,
    }
    if proxima:
        corpo["nextPageToken"] = proxima
    return httpx.Response(httpx.codes.OK, json=corpo)


def test_fetch_junta_todas_as_paginas() -> None:
    fonte, pedidos = _fonte([_pagina("ABC-1", "ABC-2", proxima="t"), _pagina("ABC-3")])
    assert sorted(fonte.fetch("1.2.0")) == ["1", "2", "3"]
    primeiro, segundo = pedidos
    assert primeiro.url.params["jql"] == 'project = "ABC" AND fixVersion = "1.2.0"'
    assert "nextPageToken" not in primeiro.url.params
    assert segundo.url.params["nextPageToken"] == "t"
    assert primeiro.headers["Authorization"] == BASIC
    assert primeiro.url.host == "x.atlassian.net"


def test_fetch_versao_sem_tarefas_devolve_vazio() -> None:
    fonte, pedidos = _fonte([_pagina()])
    assert fonte.fetch("1.2.0") == []
    assert len(pedidos) == 1


def test_fetch_sem_proximo_token_encerra() -> None:
    corpo = {"issues": [{"key": "ABC-1"}], "isLast": False}
    fonte, pedidos = _fonte([httpx.Response(httpx.codes.OK, json=corpo)])
    assert fonte.fetch("1") == ["1"]
    assert len(pedidos) == 1


def test_fetch_escapa_a_versao() -> None:
    fonte, pedidos = _fonte([_pagina()])
    fonte.fetch('a"b\\c')
    assert 'fixVersion = "a\\"b\\\\c"' in pedidos[0].url.params["jql"]


def test_fetch_url_com_barra_final_e_projeto_minusculo() -> None:
    fonte, pedidos = _fonte(
        [_pagina("ABC-7")],
        tarefas={ChaveTarefas.URL: URL + "/", ChaveTarefas.PROJETO: "abc"},
    )
    assert fonte.fetch("1") == ["7"]
    assert pedidos[0].url.path == "/rest/api/3/search/jql"


def test_fetch_credencial_com_espacos_nas_pontas() -> None:
    fonte, pedidos = _fonte(
        [_pagina()], env={VarJira.EMAIL: "e@x", VarJira.TOKEN: " tok\n"}
    )
    fonte.fetch("1")
    assert pedidos[0].headers["Authorization"] == BASIC


@pytest.mark.parametrize("valor", [None, ""])
@pytest.mark.parametrize(
    ("tabela", "chave"),
    [
        ("tarefas", ChaveTarefas.URL),
        ("tarefas", ChaveTarefas.PROJETO),
        ("ambiente", VarJira.EMAIL),
        ("ambiente", VarJira.TOKEN),
    ],
)
def test_fetch_falta_chave(tabela: str, chave: str, valor: str | None) -> None:
    tarefas = dict(TAREFAS)
    env = dict(ENV)
    alvo = tarefas if tabela == "tarefas" else env
    if valor is None:
        del alvo[chave]
    else:
        alvo[chave] = valor
    fonte, pedidos = _fonte([], tarefas=tarefas, env=env)
    with pytest.raises(ErroDeEntrada, match=re.escape(f"[{tabela}] {chave}")):
        fonte.fetch("1")
    assert pedidos == []


def _conexao_recusada(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("recusou", request=request)


@pytest.mark.parametrize(
    ("resposta", "erro"),
    [
        (httpx.Response(httpx.codes.UNAUTHORIZED), ErroDeEntrada),
        (httpx.Response(httpx.codes.FORBIDDEN), ErroDeEntrada),
        (
            httpx.Response(
                httpx.codes.BAD_REQUEST, json={"errorMessages": ["versão inexistente"]}
            ),
            ErroDeEntrada,
        ),
        (httpx.Response(httpx.codes.INTERNAL_SERVER_ERROR), BackendIndisponivel),
        (_conexao_recusada, BackendIndisponivel),
        (httpx.Response(httpx.codes.OK, text="<html>"), RespostaInvalida),
        (_pagina("XYZ-1"), RespostaInvalida),
        (_pagina("ABC-x"), RespostaInvalida),
    ],
)
def test_fetch_traduz_respostas(
    resposta: httpx.Response | Callable[[httpx.Request], httpx.Response],
    erro: type[Exception],
) -> None:
    fonte, _ = _fonte(resposta if callable(resposta) else lambda _r: resposta)
    with pytest.raises(erro):
        fonte.fetch("1.2.0")


def test_fetch_400_cita_versao_e_projeto() -> None:
    fonte, _ = _fonte(
        lambda _r: httpx.Response(
            httpx.codes.BAD_REQUEST, json={"errorMessages": ["x"]}
        )
    )
    with pytest.raises(ErroDeEntrada, match=r"(?s)(?=.*9\.9)(?=.*ABC)"):
        fonte.fetch("9.9")
