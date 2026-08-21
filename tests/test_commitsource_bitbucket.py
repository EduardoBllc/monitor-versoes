"""BitbucketPRCommitSource: acha commits do chamado via PR merged do Bitbucket Cloud.

Regra: PR MERGED cujo titulo COMECA com `ch<chamado>`, OU cuja
source.branch.name CONTEM `ch<chamado>`. So conta commit que esta na master
(is_ancestor) — commit fora da master nao entra. httpx.MockTransport no
lugar de servidor real.
"""

from __future__ import annotations

import datetime
from typing import Any

import httpx
import pytest

from motor.adapters.commitsource.bitbucket import (
    BitbucketPRCommitSource,
    parse_workspace_repo,
)
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.errors import MotorError
from motor.domain.types import RepoInfo

# Corpo de JSON da API, igual ao alias do adapter.
JSON = dict[str, Any]

REPO_ESTADO = "monitor"


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


def _git_com_master(
    *hashes_na_master: str, classe: type[FakeGit] = FakeGit
) -> FakeGit:
    # encadeia os hashes numa branch master (o primeiro e a raiz).
    g = classe()
    t0 = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    anterior = ""
    for h in hashes_na_master:
        g.add_commit(h, anterior, f"commit {h}", t0)
        anterior = h
    g.set_branch("master", anterior)
    return g


def _fonte(handler, git: FakeGit, estado=None) -> BitbucketPRCommitSource:
    estado = _estado_vazio() if estado is None else estado
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://testserver")
    return BitbucketPRCommitSource(
        base_url="http://testserver",
        token="tok123",
        email="dev@x.com",
        workspace="acme",
        repo="monitor",
        git=git,
        client=client,
        estado=estado,
        repo_estado=REPO_ESTADO,
    )


def _estado_vazio() -> FakeEstado:
    return FakeEstado(
        repos={REPO_ESTADO: RepoInfo(nome=REPO_ESTADO, tickio_sistema_id=1)}
    )


def _handler_pr(
    prs: list[JSON],
    commits_por_pr: dict[int, list[JSON]],
    pedidos: list[int] | None = None,
    buscas: list[str] | None = None,
):
    """`pedidos` acumula o id de cada PR cujos commits foram pedidos — e assim
    que os testes de cache veem a request que deveria ter sido evitada.
    `buscas` acumula o `q` de cada varredura, que e como se ve o filtro por
    marca d'agua."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Basic ZGV2QHguY29tOnRvazEyMw=="
        path = request.url.path
        if path.endswith("/pullrequests"):
            if buscas is not None:
                buscas.append(request.url.params.get("q", ""))
            return httpx.Response(200, json={"values": prs})
        # .../pullrequests/{id}/commits
        pr_id = int(path.split("/pullrequests/")[1].split("/")[0])
        if pedidos is not None:
            pedidos.append(pr_id)
        return httpx.Response(200, json={"values": commits_por_pr.get(pr_id, [])})

    return handler


def test_pr_titulo_prefixo_so_commits_na_master():
    g = _git_com_master("c1")  # c1 na master, c2 nao
    prs = [{"id": 1, "title": "ch255514 corrige logs", "source": {"branch": {"name": "feature/x"}}}]
    commits = {
        1: [
            {"hash": "c1", "date": "2024-01-02T10:00:00+00:00", "message": "fix logs", "parents": [{"hash": "p1"}]},
            {"hash": "c2", "date": "2024-01-03T10:00:00+00:00", "message": "wip", "parents": [{"hash": "c1"}]},
        ]
    }
    fonte = _fonte(_handler_pr(prs, commits), g)

    resultado = fonte.resolve(["255514"])

    commits_achados = resultado.get("255514")
    assert commits_achados is not None, f"esperava o chamado: {resultado!r}"
    hashes = [c.hash_origem for c in commits_achados]
    assert hashes == ["c1"], f"so c1 esta na master, veio {hashes}"
    assert commits_achados[0].chamado == "255514", "faltou carimbar"


def test_pr_casa_por_nome_da_branch():
    g = _git_com_master("c1")
    prs = [{"id": 7, "title": "corrige logs", "source": {"branch": {"name": "bugfix/ch255514-logs"}}}]
    commits = {7: [{"hash": "c1", "date": "2024-01-02T10:00:00+00:00", "message": "fix", "parents": []}]}
    fonte = _fonte(_handler_pr(prs, commits), g)

    resultado = fonte.resolve(["255514"])

    assert "255514" in resultado and resultado["255514"][0].hash_origem == "c1"


def test_pr_titulo_que_nao_comeca_com_o_termo_e_ignorado():
    # titulo CONTEM ch255514 mas nao COMECA com ele, e branch nao bate: ignora.
    g = _git_com_master("c1")
    prs = [{"id": 3, "title": "fix relacionado a ch255514", "source": {"branch": {"name": "feature/x"}}}]
    commits = {3: [{"hash": "c1", "date": "2024-01-02T10:00:00+00:00", "message": "fix", "parents": []}]}
    fonte = _fonte(_handler_pr(prs, commits), g)

    resultado = fonte.resolve(["255514"])

    assert resultado == {}, f"PR sem prefixo/branch batendo nao deveria contar: {resultado!r}"


def test_pr_ignora_merge_commit():
    # commit com 2 pais e merge: cherry-pick -x sem -m falha, entao nao entra na lista.
    g = _git_com_master("c1")
    prs = [{"id": 1, "title": "ch255514 corrige logs", "source": {"branch": {"name": "feature/x"}}}]
    commits = {
        1: [
            {"hash": "merge1", "date": "2024-01-02T10:00:00+00:00", "message": "merge", "parents": [{"hash": "a"}, {"hash": "b"}]},
            {"hash": "c1", "date": "2024-01-03T10:00:00+00:00", "message": "fix", "parents": [{"hash": "p1"}]},
        ]
    }
    fonte = _fonte(_handler_pr(prs, commits), g)

    resultado = fonte.resolve(["255514"])

    hashes = [c.hash_origem for c in resultado["255514"]]
    assert hashes == ["c1"], f"merge commit nao deveria entrar: {hashes}"


def test_chamado_sem_pr_correspondente_e_omitido():
    fonte = _fonte(_handler_pr([], {}), _git_com_master("c1"))

    resultado = fonte.resolve(["255514"])

    assert resultado == {}, "chamado sem PR correspondente nao deveria aparecer no resultado"


# -- workspace/repo derivados do remote ---------------------------------------


def test_workspace_e_repo_saem_do_remote_na_primeira_busca():
    """Construir nao resolve: quem monta a fonte (motor.montagem) nao tem de
    pagar uma chamada de git, e `atualizar --abort` num clone sem `origin`
    continua rodando.
    """
    urls_pedidas: list[str] = []

    class GitQueContaOsRemotes(FakeGit):
        def remote_url(self, remote: str) -> str:
            urls_pedidas.append(remote)
            return super().remote_url(remote)

    git = _git_com_master("c1", classe=GitQueContaOsRemotes)
    git.remote_urls["origin"] = "git@bitbucket.org:acme/monitor.git"
    caminhos: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        caminhos.append(request.url.path)
        return httpx.Response(200, json={"values": [], "next": ""})

    fonte = BitbucketPRCommitSource(
        base_url="http://testserver",
        token="tok",
        email="dev@x.com",
        git=git,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        estado=_estado_vazio(),
        repo_estado=REPO_ESTADO,
    )
    assert urls_pedidas == [], "construir nao pode tocar o git"

    fonte.resolve(["255514", "255515"])

    assert urls_pedidas == ["origin"], "resolvido uma vez por instancia"
    # UMA varredura atende os dois chamados. Antes era uma busca por chamado.
    assert caminhos == ["/repositories/acme/monitor/pullrequests"]


def test_workspace_explicito_ganha_do_remote():
    # o teste (e um repo cujo remote nao e o Bitbucket) passa o par direto.
    git = _git_com_master("c1")
    git.remote_urls["origin"] = "git@bitbucket.org:outro/outro.git"
    fonte = _fonte(_handler_pr([], {}), git)

    assert fonte._workspace_repo() == ("acme", "monitor")


def test_repr_nao_vaza_credencial():
    """token e email formam o Basic auth: um repr desta dataclass (com --debug,
    ou no repr de uma excecao) vazaria a credencial inteira."""
    fonte = _fonte(_handler_pr([], {}), _git_com_master("c1"))

    # os valores estao no objeto — sem isto o teste passaria por vazio
    assert (fonte.token, fonte.email) == ("tok123", "dev@x.com")
    assert "tok123" not in repr(fonte)
    assert "dev@x.com" not in repr(fonte)


# -- cache de commits por PR ---------------------------------------------------
#
# O cache guarda so `PR -> commits`, que e imutavel porque PR mergeada nao ganha
# nem perde commit. A BUSCA das PRs do chamado continua batendo na API a cada
# run: e ela que descobre PR de correcao aberta depois, e cachea-la esconderia
# esse commit — falso-verde, o modo de falha que o motor existe para evitar.


def _pr(
    pr_id: int, chamado: str = "255514", branch: str = "feature/x", dia: int = 1
) -> JSON:
    return {
        "id": pr_id,
        "title": f"ch{chamado} corrige logs",
        "source": {"branch": {"name": branch}},
        # updated_on alimenta o indice e a marca d'agua da varredura.
        "updated_on": f"2026-08-{dia:02d}T10:00:00+00:00",
    }


def _commit_bruto(
    hash_: str, dia: int = 2, parents: list[str] | None = None
) -> JSON:
    return {
        "hash": hash_,
        "date": f"2024-01-{dia:02d}T10:00:00+00:00",
        "message": f"fix {hash_}",
        "parents": [{"hash": p} for p in (parents or ["p1"])],
    }


def test_pr_nova_e_gravada_no_cache():
    estado = _estado_vazio()
    fonte = _fonte(
        _handler_pr([_pr(7)], {7: [_commit_bruto("c1")]}), _git_com_master("c1"), estado
    )

    fonte.resolve(["255514"])

    guardados = estado.commits_de_pr(REPO_ESTADO, [7])
    assert [c.hash_origem for c in guardados.get(7, [])] == ["c1"]


def test_chamado_fica_fora_do_cache():
    # o chamado vem da BUSCA, nao da PR: duas tarefas podem apontar para a mesma
    # PR, e carimbar o chamado na linha faria a segunda ler o chamado da primeira.
    estado = _estado_vazio()
    fonte = _fonte(
        _handler_pr([_pr(7)], {7: [_commit_bruto("c1")]}), _git_com_master("c1"), estado
    )

    fonte.resolve(["255514"])

    assert estado.commits_de_pr(REPO_ESTADO, [7])[7][0].chamado == ""


def test_pr_em_cache_nao_pede_os_commits_de_novo():
    estado = _estado_vazio()
    g = _git_com_master("c1")
    pedidos: list[int] = []
    handler = _handler_pr([_pr(7)], {7: [_commit_bruto("c1")]}, pedidos)

    _fonte(handler, g, estado).resolve(["255514"])
    assert pedidos == [7], "primeira passada tem que ir na API"

    pedidos.clear()
    resultado = _fonte(handler, g, estado).resolve(["255514"])

    assert pedidos == [], "PR ja em cache nao deveria gerar request de commits"
    assert [c.hash_origem for c in resultado["255514"]] == ["c1"]
    assert resultado["255514"][0].chamado == "255514", "faltou carimbar na leitura"


def test_pr_nova_no_mesmo_chamado_ainda_e_buscada():
    # o buraco que este desenho evita: cache por PR, nao por chamado.
    estado = _estado_vazio()
    g = _git_com_master("c1", "c2")
    commits = {7: [_commit_bruto("c1")], 9: [_commit_bruto("c2", dia=5, parents=["c1"])]}

    _fonte(_handler_pr([_pr(7)], commits), g, estado).resolve(["255514"])
    # PR 9 mergeada depois, no MESMO chamado
    resultado = _fonte(_handler_pr([_pr(7), _pr(9)], commits), g, estado).resolve(
        ["255514"]
    )

    assert [c.hash_origem for c in resultado["255514"]] == ["c1", "c2"]


def test_commit_do_cache_ainda_passa_pelo_is_ancestor():
    # is_ancestor fica FORA do cache porque e volatil: PR mergeada numa branch
    # que ainda nao chegou na master viraria commit escondido para sempre.
    estado = _estado_vazio()
    handler = _handler_pr([_pr(7)], {7: [_commit_bruto("c1")]})

    fora = _fonte(handler, _git_com_master("outro"), estado).resolve(["255514"])
    assert fora == {}, "c1 nao esta na master ainda"
    assert 7 in estado.commits_de_pr(REPO_ESTADO, [7]), "mas foi cacheado"

    dentro = _fonte(handler, _git_com_master("c1"), estado).resolve(["255514"])

    assert [c.hash_origem for c in dentro["255514"]] == ["c1"]


def test_merge_commit_nao_entra_no_cache():
    # numero de pais e propriedade do commit, nunca muda: filtra antes de gravar.
    estado = _estado_vazio()
    fonte = _fonte(
        _handler_pr(
            [_pr(7)],
            {7: [_commit_bruto("m1", parents=["a", "b"]), _commit_bruto("c1", dia=3)]},
        ),
        _git_com_master("c1"),
        estado,
    )

    fonte.resolve(["255514"])

    assert [c.hash_origem for c in estado.commits_de_pr(REPO_ESTADO, [7])[7]] == ["c1"]


def _removido_sem_estado_a_fonte_funciona_igual():
    # `estado=None` e o caminho de quem monta a fonte sem banco: sem cache,
    # mesmo resultado.
    fonte = _fonte(_handler_pr([_pr(7)], {7: [_commit_bruto("c1")]}), _git_com_master("c1"))

    assert [c.hash_origem for c in fonte.resolve(["255514"])["255514"]] == ["c1"]


# -- varredura incremental -----------------------------------------------------
#
# Em vez de uma busca por chamado (27 requests numa versao real), uma varredura
# que pergunta "o que mergeou desde a ultima vez" e responde os chamados a partir
# de um indice local.


def test_primeira_varredura_nao_filtra_por_data():
    # sem marca d'agua o indice esta vazio: filtrar por data deixaria de fora
    # toda PR anterior, e o chamado com PR antiga apareceria como sem entrega.
    estado = _estado_vazio()
    buscas: list[str] = []
    fonte = _fonte(
        _handler_pr([_pr(7)], {7: [_commit_bruto("c1")]}, buscas=buscas),
        _git_com_master("c1"),
        estado,
    )

    fonte.resolve(["255514"])

    assert len(buscas) == 1, f"esperava uma varredura so, veio {buscas}"
    assert "updated_on" not in buscas[0], f"backfill nao pode filtrar: {buscas[0]}"


def test_varredura_seguinte_filtra_pela_marca():
    estado = _estado_vazio()
    g = _git_com_master("c1")
    prs, commits = [_pr(7)], {7: [_commit_bruto("c1")]}

    _fonte(_handler_pr(prs, commits), g, estado).resolve(["255514"])
    marca = estado.marca_varredura(REPO_ESTADO)
    assert marca is not None, "primeira varredura tem que gravar a marca"

    buscas: list[str] = []
    _fonte(_handler_pr(prs, commits, buscas=buscas), g, estado).resolve(["255514"])

    assert "updated_on" in buscas[0], f"segunda varredura tem que filtrar: {buscas[0]}"
    assert marca.isoformat() in buscas[0]


def test_uma_varredura_atende_todos_os_chamados():
    # o ganho inteiro: 3 chamados, 1 request de varredura — nao 3 buscas.
    estado = _estado_vazio()
    buscas: list[str] = []
    fonte = _fonte(
        _handler_pr([_pr(7)], {7: [_commit_bruto("c1")]}, buscas=buscas),
        _git_com_master("c1"),
        estado,
    )

    fonte.resolve(["255514", "999888", "777666"])

    assert len(buscas) == 1, f"uma varredura por resolve, veio {len(buscas)}"


def test_chamado_com_prefixo_maior_nao_casa_no_titulo():
    # ch255514 NAO pode casar com a PR do chamado 2555145: `startswith` e `in`
    # nao viam a fronteira do numero, entao o chamado curto roubava a PR do longo.
    estado = _estado_vazio()
    fonte = _fonte(
        _handler_pr([_pr(7, chamado="2555145")], {7: [_commit_bruto("c1")]}),
        _git_com_master("c1"),
        estado,
    )

    assert fonte.resolve(["255514"]) == {}


def test_chamado_com_prefixo_maior_nao_casa_na_branch():
    estado = _estado_vazio()
    fonte = _fonte(
        _handler_pr(
            [_pr(7, chamado="000", branch="bugfix/ch2555145-logs")],
            {7: [_commit_bruto("c1")]},
        ),
        _git_com_master("c1"),
        estado,
    )

    assert fonte.resolve(["255514"]) == {}


def test_pr_nova_aparece_na_varredura_seguinte():
    estado = _estado_vazio()
    g = _git_com_master("c1", "c2")
    commits = {7: [_commit_bruto("c1")], 9: [_commit_bruto("c2", dia=5, parents=["c1"])]}

    _fonte(_handler_pr([_pr(7)], commits), g, estado).resolve(["255514"])
    resultado = _fonte(_handler_pr([_pr(9, dia=20)], commits), g, estado).resolve(
        ["255514"]
    )

    # a PR 7 vem do indice, a 9 chega nesta varredura
    assert [c.hash_origem for c in resultado["255514"]] == ["c1", "c2"]


def test_commits_so_das_prs_que_casam_com_algum_chamado():
    # o indice tem 1118 PRs num repo real; buscar os commits de todas encostaria
    # no limite de taxa da API para responder perguntas que ninguem fez.
    estado = _estado_vazio()
    pedidos: list[int] = []
    fonte = _fonte(
        _handler_pr(
            [_pr(7), _pr(8, chamado="999999")],
            {7: [_commit_bruto("c1")], 8: [_commit_bruto("c9")]},
            pedidos=pedidos,
        ),
        _git_com_master("c1", "c9"),
        estado,
    )

    fonte.resolve(["255514"])

    assert pedidos == [7], f"so a PR do chamado pedido, veio {pedidos}"
    assert [p.pr_id for p in estado.prs_indexadas(REPO_ESTADO)] == [7, 8], (
        "mas as duas entram no indice"
    )


def test_marca_nao_avanca_se_a_varredura_falhar_no_meio():
    # marca avancada com indice incompleto e perda permanente: as PRs que
    # faltaram ficam fora de toda janela futura.
    estado = _estado_vazio()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pullrequests"):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"values": []})

    with pytest.raises(MotorError):
        _fonte(handler, _git_com_master("c1"), estado).resolve(["255514"])

    assert estado.marca_varredura(REPO_ESTADO) is None
