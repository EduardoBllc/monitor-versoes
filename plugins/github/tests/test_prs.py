from __future__ import annotations

import datetime
from collections.abc import Callable, Mapping

import httpx
import pytest
from monitor_versoes_github import GithubPrs
from monitor_versoes_github.api import VarGithub
from monitor_versoes_github.prs import ChavePrs, parse_dono_repo

from motor.config import Tabela
from motor.domain.types import SEM_DATA
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida

HOST_PADRAO = "api.github.com"
API = f"https://{HOST_PADRAO}"
HOST_GHE = "ghe.x"
API_GHE = f"https://{HOST_GHE}/api/v3"
DONO, NOME = "dono", "nome"
REPO = f"{DONO}/{NOME}"
REMOTE = f"git@github.com:{REPO}.git"
TOKEN = "tok"
BEARER = f"Bearer {TOKEN}"
ENV: dict[str, str] = {VarGithub.TOKEN: TOKEN}
ARQUIVO = "c.toml"
CAMINHO_PULLS = f"/repos/{REPO}/pulls"
TITULO = "#12 corrige x"
BRANCH = "issue-12"
ANTES = "2026-01-01T00:00:00Z"
DESDE = datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC)
DEPOIS = "2026-03-01T00:00:00Z"
MERGEADO = "2026-03-01T00:00:00Z"

Rota = Callable[[httpx.Request], httpx.Response]


def _pagina(*itens: object, proxima: str | None = None) -> httpx.Response:
    headers = {"Link": f'<{proxima}>; rel="next"'} if proxima else {}
    return httpx.Response(httpx.codes.OK, json=list(itens), headers=headers)


def _pr(
    numero: int, *, merged: bool = True, atualizado: object = DEPOIS
) -> dict[str, object]:
    return {
        "number": numero,
        "title": TITULO,
        "head": {"ref": BRANCH},
        "merged_at": MERGEADO if merged else None,
        "updated_at": atualizado,
    }


def _host(
    rota: Rota | Mapping[str, list[httpx.Response]],
    *,
    prs: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    remote: Callable[[], str] = lambda: REMOTE,
) -> tuple[GithubPrs, list[httpx.Request]]:
    """Host com client falso; um dict responde em ordem por caminho da URL."""
    pedidos: list[httpx.Request] = []
    filas = {c: iter(r) for c, r in rota.items()} if isinstance(rota, Mapping) else None

    def handler(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        if filas is None:
            assert callable(rota)
            return rota(request)
        fila = filas.get(request.url.path)
        if fila is None:
            pytest.fail(f"pedido inesperado: {request.url}")
        return next(fila)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    host = GithubPrs(
        prs={} if prs is None else prs,
        arquivos=(ARQUIVO,),
        remote_url=remote,
        env=ENV if env is None else env,
        client=client,
    )
    return host, pedidos


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:dono/nome.git",
        "git@github.com:dono/nome",
        "https://github.com/dono/nome.git",
        "https://usuario@github.com/dono/nome",
        "git@ghe.empresa.com:dono/nome.git",
        "https://ghe.empresa.com/dono/nome.git",
    ],
)
def test_parse_dono_repo_de_ssh_e_https(url: str) -> None:
    assert parse_dono_repo(url) == (DONO, NOME)


def test_parse_dono_repo_fora_de_forma_e_resposta_invalida() -> None:
    with pytest.raises(RespostaInvalida):
        parse_dono_repo("nada")


def test_construir_nao_le_token_nem_remote() -> None:
    def remote() -> str:
        pytest.fail("construir não pode ler o remote")

    def falha(request: httpx.Request) -> httpx.Response:
        pytest.fail("construir não pode fazer I/O")

    _host(falha, env={}, remote=remote)


def test_sem_token_a_primeira_busca_falha_citando_a_variavel() -> None:
    host, pedidos = _host({}, env={})
    with pytest.raises(ErroDeEntrada) as erro:
        host.prs_mergeadas(None)
    assert VarGithub.TOKEN in str(erro.value)
    assert f"[{Tabela.PRS}]" in str(erro.value)
    assert pedidos == []


def test_prs_mergeadas_descarta_fechado_sem_merge() -> None:
    host, _ = _host({CAMINHO_PULLS: [_pagina(_pr(1), _pr(2, merged=False))]})
    [pr] = host.prs_mergeadas(None)
    assert (pr.pr_id, pr.titulo, pr.branch) == (1, TITULO, BRANCH)
    assert pr.updated_on == datetime.datetime.fromisoformat(DEPOIS)


def test_prs_mergeadas_segue_o_link() -> None:
    proxima = f"{API}{CAMINHO_PULLS}?page=2"
    host, pedidos = _host(
        {CAMINHO_PULLS: [_pagina(_pr(1), proxima=proxima), _pagina(_pr(2))]}
    )
    assert [p.pr_id for p in host.prs_mergeadas(None)] == [1, 2]
    assert pedidos[0].url.params["state"] == "closed"
    assert pedidos[0].url.params["sort"] == "updated"
    assert pedidos[0].url.params["direction"] == "desc"


def test_prs_mergeadas_para_ao_passar_de_desde() -> None:
    proxima = f"{API}{CAMINHO_PULLS}?page=2"

    def rota(request: httpx.Request) -> httpx.Response:
        if "page" in request.url.params:
            pytest.fail("não pode pedir a página depois de passar de desde")
        return _pagina(_pr(1), _pr(2, atualizado=ANTES), proxima=proxima)

    host, _ = _host(rota)
    assert [p.pr_id for p in host.prs_mergeadas(DESDE)] == [1]


@pytest.mark.parametrize("atualizado", [None, "", "ontem"])
def test_updated_at_ausente_ou_invalido_vira_sem_data(atualizado: object) -> None:
    host, _ = _host({CAMINHO_PULLS: [_pagina(_pr(1, atualizado=atualizado))]})
    [pr] = host.prs_mergeadas(None)
    assert pr.updated_on == SEM_DATA


def test_requisicoes_vao_para_a_api_url_do_ghes() -> None:
    host, pedidos = _host(lambda r: _pagina(), prs={ChavePrs.API_URL: f"{API_GHE}/"})
    host.prs_mergeadas(None)
    [pedido] = pedidos
    assert str(pedido.url).startswith(f"{API_GHE}{CAMINHO_PULLS}")
    assert pedido.headers["Authorization"] == BEARER


def test_sem_api_url_usa_api_github_com() -> None:
    host, pedidos = _host(lambda r: _pagina())
    host.prs_mergeadas(None)
    [pedido] = pedidos
    assert pedido.url.host == HOST_PADRAO
    assert pedido.headers["Authorization"] == BEARER


def test_api_url_sem_https_e_erro_de_entrada() -> None:
    host, _ = _host(lambda r: _pagina(), prs={ChavePrs.API_URL: f"http://{HOST_GHE}"})
    with pytest.raises(ErroDeEntrada):
        host.prs_mergeadas(None)


@pytest.mark.parametrize(
    "proxima",
    [f"https://outro.x{CAMINHO_PULLS}?page=2", f"{API}{CAMINHO_PULLS}"],
)
def test_pagina_fora_da_api_url_ou_repetida_e_resposta_invalida(proxima: str) -> None:
    host, _ = _host(lambda r: _pagina(_pr(1), proxima=proxima))
    with pytest.raises(RespostaInvalida):
        host.prs_mergeadas(None)


@pytest.mark.parametrize(
    ("resposta", "erro"),
    [
        (httpx.Response(httpx.codes.UNAUTHORIZED), ErroDeEntrada),
        (httpx.Response(httpx.codes.FORBIDDEN), ErroDeEntrada),
        (httpx.Response(httpx.codes.TOO_MANY_REQUESTS), BackendIndisponivel),
        (
            httpx.Response(
                httpx.codes.FORBIDDEN, headers={"x-ratelimit-remaining": "0"}
            ),
            BackendIndisponivel,
        ),
    ],
)
def test_erros_http_viram_os_da_fonte_de_tarefas(
    resposta: httpx.Response, erro: type[Exception]
) -> None:
    host, _ = _host(lambda r: resposta)
    with pytest.raises(erro):
        host.prs_mergeadas(None)


def test_falha_de_rede_e_backend_indisponivel() -> None:
    def rota(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fora", request=request)

    host, _ = _host(rota)
    with pytest.raises(BackendIndisponivel):
        host.prs_mergeadas(None)


def test_404_do_repo_cita_o_origin_e_nao_o_tarefas() -> None:
    host, _ = _host(lambda r: httpx.Response(httpx.codes.NOT_FOUND))
    with pytest.raises(ErroDeEntrada) as erro:
        host.prs_mergeadas(None)
    mensagem = str(erro.value)
    assert REPO in mensagem
    assert "origin" in mensagem
    assert f"[{Tabela.TAREFAS}]" not in mensagem
