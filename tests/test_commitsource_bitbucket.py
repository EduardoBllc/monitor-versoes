"""BitbucketPrs: o plugin `HostPr` do Bitbucket Cloud, só a parte de HTTP.

Casamento, cache, marca e filtro pela principal são do núcleo e são testados em
`test_commitsource_pr.py`. Aqui: forma do JSON, URL, paginação, credencial e
filtro de merge commit. httpx.MockTransport no lugar de servidor real.
"""

from __future__ import annotations

import datetime
from typing import Any

import httpx
import pytest

from motor.adapters.commitsource.bitbucket import BitbucketPrs, parse_workspace_repo
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida

# Corpo de JSON da API, igual ao alias do adapter.
JSON = dict[str, Any]

TOKEN, EMAIL = "tok123", "dev@x.com"
REMOTE = "git@bitbucket.org:acme/monitor.git"


@pytest.fixture(autouse=True)
def credenciais(monkeypatch):
    monkeypatch.setenv("BITBUCKET_TOKEN", TOKEN)
    monkeypatch.setenv("BITBUCKET_EMAIL", EMAIL)


@pytest.mark.parametrize(
    "url,esperado",
    [
        ("git@bitbucket.org:acme/monitor.git", ("acme", "monitor")),
        ("https://user@bitbucket.org/acme/monitor.git", ("acme", "monitor")),
        ("https://bitbucket.org/acme/monitor", ("acme", "monitor")),
    ],
)
def test_parse_workspace_repo(url, esperado):
    assert parse_workspace_repo(url) == esperado


def _host(handler, remote_url=lambda: REMOTE, base_url="http://testserver"):
    return BitbucketPrs(
        prs={"fonte": "bitbucket"},
        arquivos=("/cfg/config.toml",),
        remote_url=remote_url,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url=base_url,
    )


def _handler_pr(
    prs: list[JSON],
    commits_por_pr: dict[int, list[JSON]] | None = None,
    buscas: list[httpx.Request] | None = None,
):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Basic ZGV2QHguY29tOnRvazEyMw=="
        if buscas is not None:
            buscas.append(request)
        path = request.url.path
        if path.endswith("/pullrequests"):
            return httpx.Response(200, json={"values": prs})
        pr_id = int(path.split("/pullrequests/")[1].split("/")[0])
        return httpx.Response(
            200, json={"values": (commits_por_pr or {}).get(pr_id, [])}
        )

    return handler


def _pr(pr_id: int) -> JSON:
    return {
        "id": pr_id,
        "title": "ch255514 corrige logs",
        "source": {"branch": {"name": "feature/x"}},
        "updated_on": "2026-08-01T10:00:00+00:00",
    }


def _commit_bruto(hash_: str, parents: list[str] | None = None) -> JSON:
    return {
        "hash": hash_,
        "date": "2024-01-02T10:00:00+00:00",
        "message": f"fix {hash_}",
        "parents": [{"hash": p} for p in (parents or ["p1"])],
    }


def test_prs_mergeadas_converte_o_json():
    [pr] = _host(_handler_pr([_pr(7)])).prs_mergeadas(None)

    assert (pr.pr_id, pr.titulo, pr.branch) == (7, "ch255514 corrige logs", "feature/x")
    assert pr.updated_on == datetime.datetime(2026, 8, 1, 10, tzinfo=datetime.UTC)


def test_pr_sem_id_e_descartada():
    sem_id = {**_pr(7), "id": None}
    prs = _host(_handler_pr([sem_id, _pr(8)])).prs_mergeadas(None)
    assert [p.pr_id for p in prs] == [8]


def test_desde_vira_filtro_updated_on():
    buscas: list[httpx.Request] = []
    host = _host(_handler_pr([], buscas=buscas))
    desde = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)

    host.prs_mergeadas(None)
    host.prs_mergeadas(desde)

    # sem marca, o histórico inteiro: filtrar por data deixaria de fora toda PR
    # anterior, e o chamado com PR antiga apareceria como sem entrega.
    assert "q" not in buscas[0].url.params
    assert buscas[1].url.params["q"] == f'updated_on >= "{desde.isoformat()}"'
    assert buscas[1].url.params["state"] == "MERGED"


def test_paginacao_segue_next():
    paginas = {
        "/repositories/acme/monitor/pullrequests": {
            "values": [_pr(1)],
            "next": "http://testserver/pagina2",
        },
        "/pagina2": {"values": [_pr(2)]},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=paginas[request.url.path])

    assert [p.pr_id for p in _host(handler).prs_mergeadas(None)] == [1, 2]


def test_commits_da_pr_descarta_merge_commit():
    # merge commit: cherry-pick -x sem -m falha, e o núcleo cacheia o que vier.
    commits = {7: [_commit_bruto("merge1", ["a", "b"]), _commit_bruto("c1")]}

    [c] = _host(_handler_pr([], commits)).commits_da_pr(7)

    assert (c.hash_origem, c.parent, c.msg, c.chamado) == ("c1", "p1", "fix c1", "")


def test_resposta_de_pullrequests_fora_de_forma_vira_respostainvalida():
    def handler(request: httpx.Request) -> httpx.Response:
        # lista crua em vez do envelope {"values": [...]}
        return httpx.Response(200, json=["nao", "e", "um", "objeto"])

    with pytest.raises(RespostaInvalida):
        _host(handler).prs_mergeadas(None)


@pytest.mark.parametrize(
    "pr", ["nao-e-um-dict", {"id": 1, "title": 12345, "source": {}}]
)
def test_pr_fora_de_forma_vira_respostainvalida(pr):
    with pytest.raises(RespostaInvalida):
        _host(_handler_pr([pr])).prs_mergeadas(None)


def test_parent_de_commit_fora_de_forma_vira_respostainvalida():
    commits = {7: [{**_commit_bruto("c1"), "parents": ["nao-e-um-dict"]}]}

    with pytest.raises(RespostaInvalida):
        _host(_handler_pr([], commits)).commits_da_pr(7)


def test_resposta_nao_ok_vira_backendindisponivel():
    with pytest.raises(BackendIndisponivel):
        _host(lambda r: httpx.Response(500)).prs_mergeadas(None)


def test_base_url_malformada_vira_errodeentrada_nao_invalidurl():
    """httpx.InvalidURL não herda de httpx.HTTPError (verificado em 0.28.1) — sem
    a captura extra isto escapava do `except httpx.HTTPError` como traceback.
    """
    host = BitbucketPrs(
        prs={}, arquivos=(), remote_url=lambda: REMOTE, base_url="http://h:porta"
    )

    with pytest.raises(ErroDeEntrada):
        host.prs_mergeadas(None)


def test_construir_nao_le_remote_nem_credencial(monkeypatch):
    """Montar não é usar: `atualizar --abort` e `reconstruir-estado` constroem a
    fonte e nunca a chamam."""
    monkeypatch.delenv("BITBUCKET_TOKEN")
    remotes: list[int] = []

    def remote_url() -> str:
        remotes.append(1)
        return REMOTE

    _host(_handler_pr([]), remote_url=remote_url)

    assert remotes == []


def test_workspace_e_repo_saem_do_remote_uma_vez():
    remotes: list[int] = []
    caminhos: list[str] = []

    def remote_url() -> str:
        remotes.append(1)
        return REMOTE

    def handler(request: httpx.Request) -> httpx.Response:
        caminhos.append(request.url.path)
        return httpx.Response(200, json={"values": []})

    host = _host(handler, remote_url=remote_url)
    host.prs_mergeadas(None)
    host.commits_da_pr(7)

    assert remotes == [1]
    assert caminhos == [
        "/repositories/acme/monitor/pullrequests",
        "/repositories/acme/monitor/pullrequests/7/commits",
    ]


@pytest.mark.parametrize("falta", ["BITBUCKET_TOKEN", "BITBUCKET_EMAIL"])
def test_sem_credencial_falha_na_primeira_busca_nao_no_construtor(monkeypatch, falta):
    monkeypatch.delenv(falta)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("não deveria chamar a rede")

    host = _host(handler)

    with pytest.raises(ErroDeEntrada) as e:
        host.prs_mergeadas(None)
    assert falta in str(e.value)
    assert "/cfg/config.toml" in str(e.value)


def test_repr_nao_vaza_credencial():
    host = _host(_handler_pr([]))
    host.prs_mergeadas(None)  # a credencial já foi lida

    assert TOKEN not in repr(host)
    assert EMAIL not in repr(host)


# -- verificar_credenciais (monitor-versoes diagnostico) ----------------------


def test_verificar_credenciais_aceita_e_manda_basic():
    vistos: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistos.append(request)
        return httpx.Response(200, json={"uuid": "x"})

    _host(handler, base_url="http://bb/2.0").verificar_credenciais()

    assert len(vistos) == 1
    assert str(vistos[0].url) == "http://bb/2.0/user"
    assert vistos[0].headers["Authorization"] == "Basic ZGV2QHguY29tOnRvazEyMw=="


def test_verificar_credenciais_recusada():
    with pytest.raises(BackendIndisponivel):
        _host(lambda r: httpx.Response(401)).verificar_credenciais()


def test_verificar_credenciais_sem_email_nao_faz_requisicao(monkeypatch):
    monkeypatch.delenv("BITBUCKET_EMAIL")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("não deveria chamar a rede")

    with pytest.raises(ErroDeEntrada):
        _host(handler).verificar_credenciais()


def test_verificar_credenciais_nao_precisa_de_repo():
    def sem_repo() -> str:
        raise ErroDeEntrada("sem repo")

    host = _host(lambda r: httpx.Response(200, json={}), remote_url=sem_repo)

    host.verificar_credenciais()
