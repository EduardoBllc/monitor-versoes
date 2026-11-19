from __future__ import annotations

import datetime
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from monitor_versoes_gitlab import GitlabPrs
from monitor_versoes_gitlab.api import VarGitlab
from monitor_versoes_gitlab.prs import ChavePrs, _Campo, _Estado, _Param

from motor.config import Chave, Tabela
from motor.config_edicao import GrupoPlugin, catalogo_campos
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida
from motor.montagem import GRUPO_PRS
from motor.plugins import carregar_plugin

PLUGIN = "gitlab"
PARAM_PAGINA = "page"
CABECALHO_LINK = "Link"
CAMPO_SQUASH_LIGADO = "squash"
SUBCAMINHO_NO_PROJETO = "gitlab%2Fgrupo%2Fnome"
HOST_PADRAO = "https://gitlab.com"
HOST_PROPRIO = "https://git.x/gitlab"
PROJETO = "grupo%2Fnome"
REMOTE = "git@gitlab.com:grupo/nome.git"
TOKEN = "tok"
CABECALHO_TOKEN = "PRIVATE-TOKEN"
ENV: dict[str, str] = {VarGitlab.TOKEN: TOKEN}
ARQUIVO = "c.toml"
CAMINHO_MRS = f"/api/v4/projects/{PROJETO}/merge_requests"
DESDE = datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC)
ATUALIZADO = "2026-03-01T00:00:00.000Z"
TITULO = "#12 corrige x"
BRANCH = "issue-12"

Rota = Callable[[httpx.Request], httpx.Response]


def _pagina(*itens: object, proxima: str | None = None) -> httpx.Response:
    headers = {CABECALHO_LINK: f'<{proxima}>; rel="next"'} if proxima else {}
    return httpx.Response(httpx.codes.OK, json=list(itens), headers=headers)


def _mr(iid: object) -> dict[str, object]:
    return {
        _Campo.IID: iid,
        _Campo.TITLE: TITULO,
        _Campo.SOURCE_BRANCH: BRANCH,
        _Campo.UPDATED_AT: ATUALIZADO,
    }


def _host(
    rota: Rota,
    *,
    prs: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    remote: Callable[[], str] = lambda: REMOTE,
) -> tuple[GitlabPrs, list[httpx.Request]]:
    pedidos: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return rota(request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    host = GitlabPrs(
        prs={} if prs is None else prs,
        arquivos=(ARQUIVO,),
        remote_url=remote,
        env=ENV if env is None else env,
        client=client,
    )
    return host, pedidos


def _vazio(request: httpx.Request) -> httpx.Response:
    return _pagina()


def test_carregar_plugin_prs_gitlab_devolve_a_classe() -> None:
    assert carregar_plugin(GRUPO_PRS, PLUGIN) is GitlabPrs


def test_construir_nao_le_token_nem_remote() -> None:
    def remote() -> str:
        pytest.fail("construir não pode ler o remote")

    def falha(request: httpx.Request) -> httpx.Response:
        pytest.fail("construir não pode fazer I/O")

    _host(falha, env={}, remote=remote)


def test_sem_token_a_primeira_busca_falha_citando_a_variavel() -> None:
    host, pedidos = _host(_vazio, env={}, remote=lambda: pytest.fail("sem remote"))
    with pytest.raises(ErroDeEntrada) as erro:
        host.prs_mergeadas(None)
    assert VarGitlab.TOKEN in str(erro.value)
    assert f"[{Tabela.PRS}]" in str(erro.value)
    assert pedidos == []


@pytest.mark.parametrize(
    ("remote", "url", "esperado"),
    [
        ("git@gitlab.com:grupo/nome.git", None, f"/api/v4/projects/{PROJETO}"),
        ("git@gitlab.com:grupo/sub/nome", None, "/api/v4/projects/grupo%2Fsub%2Fnome"),
        (
            "ssh://git@git.x:2222/grupo/sub/nome.git",
            None,
            "/api/v4/projects/grupo%2Fsub%2Fnome",
        ),
        ("https://gitlab.com/grupo/nome.git", None, f"/api/v4/projects/{PROJETO}"),
        (
            "https://usuario@git.x:8443/grupo/sub/nome",
            None,
            "/api/v4/projects/grupo%2Fsub%2Fnome",
        ),
        (
            "https://git.x/gitlab/grupo/nome.git",
            HOST_PROPRIO,
            f"/gitlab/api/v4/projects/{PROJETO}/merge_requests",
        ),
        *[
            (remote, HOST_PROPRIO, f"/gitlab/api/v4/projects/{SUBCAMINHO_NO_PROJETO}")
            for remote in (
                "https://outro.x/gitlab/grupo/nome.git",
                "https://git.x:8443/gitlab/grupo/nome.git",
                "git@git.x:gitlab/grupo/nome.git",
            )
        ],
    ],
)
def test_projeto_derivado_do_remote(
    remote: str, url: str | None, esperado: str
) -> None:
    prs: dict[str, object] = {} if url is None else {ChavePrs.URL: url}
    host, pedidos = _host(_vazio, prs=prs, remote=lambda: remote)
    host.prs_mergeadas(None)
    assert pedidos[0].url.raw_path.decode().startswith(esperado)


@pytest.mark.parametrize(
    "remote", ["nada", "git@gitlab.com:nome.git", "http://gitlab.com/grupo/nome"]
)
def test_remote_fora_de_forma_e_resposta_invalida(remote: str) -> None:
    host, _ = _host(_vazio, remote=lambda: remote)
    with pytest.raises(RespostaInvalida):
        host.prs_mergeadas(None)


def test_prs_mergeadas_segue_o_link_e_descarta_sem_iid() -> None:
    proxima = f"{HOST_PADRAO}{CAMINHO_MRS}?page=2"

    def rota(request: httpx.Request) -> httpx.Response:
        if request.url.params.get(PARAM_PAGINA) == "2":
            return _pagina(_mr(2))
        return _pagina(_mr(1), {_Campo.TITLE: "sem iid"}, _mr(True), proxima=proxima)

    host, pedidos = _host(rota)
    indices = host.prs_mergeadas(None)
    assert [p.pr_id for p in indices] == [1, 2]
    assert (indices[0].titulo, indices[0].branch) == (TITULO, BRANCH)
    assert indices[0].updated_on == datetime.datetime.fromisoformat(ATUALIZADO)
    assert pedidos[0].url.params[_Param.STATE] == _Estado.MERGED
    assert _Param.UPDATED_AFTER not in pedidos[0].url.params


def test_prs_mergeadas_manda_updated_after() -> None:
    host, pedidos = _host(_vazio)
    host.prs_mergeadas(DESDE)
    assert pedidos[0].url.params[_Param.UPDATED_AFTER] == DESDE.isoformat()


def test_requisicoes_vao_para_a_url_self_managed() -> None:
    host, pedidos = _host(_vazio, prs={ChavePrs.URL: f"{HOST_PROPRIO}/"})
    host.prs_mergeadas(None)
    [pedido] = pedidos
    assert str(pedido.url).startswith(f"{HOST_PROPRIO}/api/v4/projects/")
    assert pedido.headers[CABECALHO_TOKEN] == TOKEN


def test_sem_url_usa_gitlab_com() -> None:
    host, pedidos = _host(_vazio)
    host.prs_mergeadas(None)
    assert str(pedidos[0].url).startswith(f"{HOST_PADRAO}/api/v4/")


def test_url_sem_https_levanta_citando_a_chave() -> None:
    host, pedidos = _host(_vazio, prs={ChavePrs.URL: "http://git.x"})
    with pytest.raises(ErroDeEntrada, match=r"\[prs\] url"):
        host.prs_mergeadas(None)
    assert pedidos == []


@pytest.mark.parametrize(
    "proxima",
    [
        "https://outro.com/api/v4/x?page=2",
        f"{HOST_PADRAO}{CAMINHO_MRS}?per_page=100&state=merged",
        "http://[::1",
    ],
)
def test_pagina_seguinte_invalida_levanta(proxima: str) -> None:
    host, _ = _host(lambda r: _pagina(_mr(1), proxima=proxima))
    with pytest.raises(RespostaInvalida):
        host.prs_mergeadas(None)


@pytest.mark.parametrize(
    "resp",
    [
        httpx.Response(httpx.codes.OK, content=b"nao e json"),
        httpx.Response(httpx.codes.OK, json={}),
        _pagina(1),
    ],
)
def test_corpo_malformado_levanta(resp: httpx.Response) -> None:
    host, _ = _host(lambda r: resp)
    with pytest.raises(RespostaInvalida):
        host.prs_mergeadas(None)


@pytest.mark.parametrize(
    ("status", "erro"),
    [
        (httpx.codes.UNAUTHORIZED, ErroDeEntrada),
        (httpx.codes.FORBIDDEN, ErroDeEntrada),
        (httpx.codes.NOT_FOUND, ErroDeEntrada),
        (httpx.codes.TOO_MANY_REQUESTS, BackendIndisponivel),
        (httpx.codes.INTERNAL_SERVER_ERROR, BackendIndisponivel),
    ],
)
def test_status_de_erro_vira_erro_do_motor(status: int, erro: type[Exception]) -> None:
    host, _ = _host(lambda r: httpx.Response(status))
    with pytest.raises(erro):
        host.prs_mergeadas(None)


def test_falha_de_rede_e_backend_indisponivel() -> None:
    def rota(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rede")

    host, _ = _host(rota)
    with pytest.raises(BackendIndisponivel):
        host.prs_mergeadas(None)


def test_404_da_lista_cita_o_caminho_derivado_e_o_origin() -> None:
    host, _ = _host(lambda r: httpx.Response(httpx.codes.NOT_FOUND))
    with pytest.raises(ErroDeEntrada) as erro:
        host.prs_mergeadas(None)
    texto = str(erro.value)
    assert "grupo/nome" in texto
    assert "origin" in texto
    assert f"[{Tabela.TAREFAS}]" not in texto


def test_verificar_credenciais_404_cita_a_url_do_prs() -> None:
    host, _ = _host(lambda r: httpx.Response(httpx.codes.NOT_FOUND))
    with pytest.raises(ErroDeEntrada) as erro:
        host.verificar_credenciais()
    assert f"[{Tabela.PRS}] url" in str(erro.value)
    assert f"[{Tabela.TAREFAS}]" not in str(erro.value)


def test_verificar_credenciais_manda_o_token_para_user() -> None:
    host, pedidos = _host(
        lambda r: httpx.Response(httpx.codes.OK, json={}),
        prs={ChavePrs.URL: HOST_PROPRIO},
        remote=lambda: pytest.fail("o diagnóstico não pode ler o remote"),
    )
    assert host.verificar_credenciais() is None
    [pedido] = pedidos
    assert str(pedido.url) == f"{HOST_PROPRIO}/api/v4/user"
    assert pedido.headers[CABECALHO_TOKEN] == TOKEN


def test_verificar_credenciais_sem_token_levanta() -> None:
    host, pedidos = _host(_vazio, env={})
    with pytest.raises(ErroDeEntrada):
        host.verificar_credenciais()
    assert pedidos == []


def test_campos_aparecem_no_catalogo() -> None:
    config: dict[str, object] = {
        Tabela.TAREFAS: {Chave.FONTE: PLUGIN},
        Tabela.PRS: {Chave.FONTE: PLUGIN},
    }
    campos = [c for c in catalogo_campos(config) if c.origem == PLUGIN]
    assert any(c.tabela == Tabela.PRS and c.chave == ChavePrs.URL for c in campos)
    tokens = [c for c in campos if c.chave == VarGitlab.TOKEN]
    assert {c.grupo for c in tokens} == {GrupoPlugin.TAREFAS, GrupoPlugin.PRS}
    assert len(tokens) == len({c.grupo for c in tokens})
    for token in tokens:
        assert token.segredo
        assert "Obrigatório para a fonte de PR" in token.aviso_vazio


PR_ID = 12
# `url.path` já vem decodificado.
CAMINHO = "/api/v4/projects/grupo/nome"
BASE_MR = f"{CAMINHO}/merge_requests/{PR_ID}"
BASE_COMMITS = f"{CAMINHO}/repository/commits"
DATA_COMMIT = "2026-03-02T10:00:00.000+00:00"


def _commit(sha: str, *pais: str, msg: str = "msg", **extra: object) -> object:
    return {
        _Campo.ID: sha,
        _Campo.PARENT_IDS: list(pais),
        _Campo.COMMITTED_DATE: DATA_COMMIT,
        _Campo.MESSAGE: msg,
        **extra,
    }


def _gitlab(
    *,
    mr: object = None,
    squash: str | None = None,
    lista: object = None,
    commits: Mapping[str, object] | None = None,
) -> Rota:
    """Rota por caminho; o que não está no mapa responde 404."""
    corpo_mr = (
        {_Campo.IID: PR_ID, _Campo.SQUASH_COMMIT_SHA: squash} if mr is None else mr
    )
    por_caminho: dict[str, object] = {BASE_MR: corpo_mr}
    if lista is not None:
        por_caminho[f"{BASE_MR}/commits"] = lista
    for sha, commit in (commits or {}).items():
        por_caminho[f"{BASE_COMMITS}/{sha}"] = commit

    def rota(request: httpx.Request) -> httpx.Response:
        if request.url.path not in por_caminho:
            return httpx.Response(httpx.codes.NOT_FOUND)
        return httpx.Response(httpx.codes.OK, json=por_caminho[request.url.path])

    return rota


def _hashes(rota: Rota) -> list[str]:
    host, _ = _host(rota)
    return [c.hash_origem for c in host.commits_da_pr(PR_ID)]


def test_squash_devolve_so_o_commit_de_squash() -> None:
    rota = _gitlab(squash="s", commits={"s": _commit("s", "base")})
    host, pedidos = _host(rota)
    assert [c.hash_origem for c in host.commits_da_pr(PR_ID)] == ["s"]
    assert not any(p.url.path.endswith("/commits") for p in pedidos)


@pytest.mark.parametrize("squash", [None, ""])
def test_sem_squash_tira_o_merge_commit_mesmo_sem_parent_ids_na_lista(
    squash: str | None,
) -> None:
    rota = _gitlab(
        squash=squash,
        lista=[{_Campo.ID: "c1"}, {_Campo.ID: "m"}, {_Campo.ID: "c2"}],
        commits={
            "c1": _commit("c1", "base"),
            "m": _commit("m", "c1", "outro"),
            "c2": _commit("c2", "m"),
        },
    )
    assert _hashes(rota) == ["c1", "c2"]


def test_mr_com_squash_ligado_e_sem_sha_cai_na_lista() -> None:
    mr = {_Campo.IID: PR_ID, CAMPO_SQUASH_LIGADO: True}
    rota = _gitlab(mr=mr, lista=[{_Campo.ID: "c1"}], commits={"c1": _commit("c1", "b")})
    assert _hashes(rota) == ["c1"]


@pytest.mark.parametrize(
    "rota",
    [
        pytest.param(_gitlab(squash="s"), id="squash"),
        pytest.param(lambda r: httpx.Response(httpx.codes.NOT_FOUND), id="mr"),
        pytest.param(_gitlab(lista=None), id="lista"),
        pytest.param(
            _gitlab(
                lista=[{_Campo.ID: "c1"}, {_Campo.ID: "c2"}],
                commits={"c1": _commit("c1")},
            ),
            id="commit-da-lista",
        ),
    ],
)
def test_404_devolve_vazio_sem_erro(rota: Rota) -> None:
    assert _hashes(rota) == []


@pytest.mark.parametrize(
    "rota",
    [
        pytest.param(_gitlab(mr=[]), id="mr-lista"),
        pytest.param(_gitlab(squash="s", commits={"s": []}), id="commit-lista"),
        pytest.param(_gitlab(lista={}), id="commits-objeto"),
        pytest.param(_gitlab(lista=[1]), id="item-nao-objeto"),
        pytest.param(_gitlab(lista=[{"outro": 1}]), id="item-sem-id"),
        pytest.param(
            _gitlab(
                squash="s", commits={"s": {_Campo.ID: "s", _Campo.PARENT_IDS: ["a", 1]}}
            ),
            id="pais-invalidos",
        ),
        pytest.param(
            _gitlab(
                squash="s", commits={"s": {_Campo.ID: "s", _Campo.PARENT_IDS: "a"}}
            ),
            id="pais-texto",
        ),
    ],
)
def test_forma_inesperada_levanta(rota: Rota) -> None:
    host, _ = _host(rota)
    with pytest.raises(RespostaInvalida):
        host.commits_da_pr(PR_ID)


def test_commit_ref_usa_data_pai_e_mensagem_do_commit() -> None:
    rota = _gitlab(
        squash="s", commits={"s": _commit("s", "base", "x", msg="#12 tudo\n\ncorpo")}
    )
    host, _ = _host(rota)
    [ref] = host.commits_da_pr(PR_ID)
    assert ref.commit_date == datetime.datetime.fromisoformat(DATA_COMMIT)
    assert (ref.parent, ref.msg, ref.chamado) == ("base", "#12 tudo\n\ncorpo", "")


def _fabrica(rota: Rota, criados: list[httpx.Client]) -> Callable[[], httpx.Client]:
    original = httpx.Client

    def fabrica() -> httpx.Client:
        client = original(transport=httpx.MockTransport(rota))
        criados.append(client)
        return client

    return fabrica


def test_commits_da_pr_concorrente_usa_um_cliente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rota = _gitlab(squash="s", commits={"s": _commit("s", "b")})
    criados: list[httpx.Client] = []
    monkeypatch.setattr(
        "monitor_versoes_gitlab.api.httpx.Client", _fabrica(rota, criados)
    )
    host = GitlabPrs(prs={}, arquivos=(), remote_url=lambda: REMOTE, env=ENV)
    with ThreadPoolExecutor(max_workers=4) as pool:
        resultados = list(pool.map(host.commits_da_pr, [PR_ID] * 4))
    assert all([c.hash_origem for c in r] == ["s"] for r in resultados)
    assert len(criados) == 1


def test_fechar_fecha_o_proprio_e_nao_o_injetado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rota = _gitlab(squash="s", commits={"s": _commit("s", "b")})
    criados: list[httpx.Client] = []
    original = httpx.Client
    monkeypatch.setattr(
        "monitor_versoes_gitlab.api.httpx.Client", _fabrica(rota, criados)
    )
    proprio = GitlabPrs(prs={}, arquivos=(), remote_url=lambda: REMOTE, env=ENV)
    proprio.commits_da_pr(PR_ID)
    proprio.fechar()
    assert [c.is_closed for c in criados] == [True]

    injetado = original(transport=httpx.MockTransport(rota))
    host = GitlabPrs(
        prs={}, arquivos=(), remote_url=lambda: REMOTE, env=ENV, client=injetado
    )
    host.commits_da_pr(PR_ID)
    host.fechar()
    assert not injetado.is_closed
