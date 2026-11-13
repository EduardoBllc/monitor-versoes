"""PrCommitSource: acha commits do chamado pelas PRs mergeadas no host.

Regra: PR mergeada cujo título COMEÇA com a referência do chamado, OU cuja
branch de origem a CONTÉM — sem olhar caixa. Só conta commit que está em
`origin/<principal>` (is_ancestor). O host é o `FakeHostPr`; o HTTP de cada
host real se testa no arquivo dele.
"""

from __future__ import annotations

import datetime

import pytest

from motor.adapters.commitsource.fake import FakeHostPr
from motor.adapters.commitsource.pr import PrCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.domain.referencia import Referencia
from motor.domain.types import CommitRef, PrIndex, RepoInfo
from motor.errors import BackendIndisponivel
from tests.fontes_falsas import REFERENCIA_CH

REPO_ESTADO = "monitor"
HOST = "fake"


def _git_com_master(*hashes_na_master: str) -> FakeGit:
    # encadeia os hashes numa branch master (o primeiro é a raiz). As duas refs
    # no mesmo tip: é o que um clone recém-fetchado tem, e a fonte lê a de
    # rastreamento.
    g = FakeGit()
    t0 = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
    anterior = ""
    for h in hashes_na_master:
        g.add_commit(h, anterior, f"commit {h}", t0)
        anterior = h
    g.set_branch("origin/master", anterior)
    g.set_branch("master", anterior)
    return g


def _estado_vazio() -> FakeEstado:
    return FakeEstado(repos={REPO_ESTADO: RepoInfo(nome=REPO_ESTADO)})


def _pr(
    pr_id: int,
    chamado: str = "255514",
    branch: str = "feature/x",
    titulo: str | None = None,
) -> PrIndex:
    return PrIndex(
        pr_id=pr_id,
        titulo=f"ch{chamado} corrige logs" if titulo is None else titulo,
        branch=branch,
        updated_on=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
    )


def _commit(hash_: str, dia: int = 2) -> CommitRef:
    return CommitRef(
        hash_origem=hash_,
        parent="p1",
        commit_date=datetime.datetime(2024, 1, dia, tzinfo=datetime.UTC),
        msg=f"fix {hash_}",
    )


def _fonte(
    host: FakeHostPr,
    git: FakeGit,
    estado: FakeEstado | None = None,
    *,
    referencia: Referencia = REFERENCIA_CH,
    nome_host: str = HOST,
) -> PrCommitSource:
    return PrCommitSource(
        host,
        nome_host,
        git,
        estado=_estado_vazio() if estado is None else estado,
        repo_estado=REPO_ESTADO,
        referencia=lambda: referencia,
        ref_principal=lambda: "origin/master",
    )


def _hashes(
    resultado: dict[str, list[CommitRef]], chamado: str = "255514"
) -> list[str]:
    return [c.hash_origem for c in resultado.get(chamado, [])]


def test_pr_titulo_prefixo_so_commits_na_master():
    host = FakeHostPr([_pr(1)], {1: [_commit("c1"), _commit("c2", dia=3)]})

    resultado = _fonte(host, _git_com_master("c1")).resolve(["255514"])

    assert _hashes(resultado) == ["c1"], "só c1 está na master"
    assert resultado["255514"][0].chamado == "255514", "faltou carimbar"


def test_pr_conta_commit_que_so_chegou_no_origin_master():
    """Regressão (chamado 257270, PR 1174): `git fetch` avança origin/master e
    nunca o head local, então filtrar por `master` escondia entrega mergeada
    depois do último checkout+pull da máquina. O chamado tinha uma entrega
    antiga, essa sim no head local, e com ela a fonte de PR devolvia commits —
    a cadeia (ChainCommitSource) dava o chamado por resolvido e nem o grep, que
    lê origin/master, via a segunda.
    """
    g = _git_com_master("c1")
    g.add_commit(
        "c2", "c1", "commit c2", datetime.datetime(2024, 1, 2, tzinfo=datetime.UTC)
    )
    g.set_branch("origin/master", "c2")  # local `master` fica em c1
    host = FakeHostPr([_pr(1174, chamado="257270")], {1174: [_commit("c2")]})

    resultado = _fonte(host, g).resolve(["257270"])

    assert _hashes(resultado, "257270") == ["c2"]


def test_pr_casa_por_nome_da_branch():
    host = FakeHostPr(
        [_pr(7, titulo="corrige logs", branch="bugfix/ch255514-logs")],
        {7: [_commit("c1")]},
    )

    assert _hashes(_fonte(host, _git_com_master("c1")).resolve(["255514"])) == ["c1"]


def test_pr_titulo_que_nao_comeca_com_o_termo_e_ignorado():
    # título CONTÉM ch255514 mas não COMEÇA com ele, e a branch não bate.
    host = FakeHostPr(
        [_pr(3, titulo="fix relacionado a ch255514")], {3: [_commit("c1")]}
    )

    assert _fonte(host, _git_com_master("c1")).resolve(["255514"]) == {}


def test_chamado_sem_pr_correspondente_e_omitido():
    assert _fonte(FakeHostPr(), _git_com_master("c1")).resolve(["255514"]) == {}


def test_pr_com_prefixo_em_maiuscula_casa():
    """A 2a PR de um chamado com o título em caixa alta ("CH255514 - ...") não
    casava, e o buraco era silencioso: a 1a PR casava, a cadeia dava o chamado
    por resolvido e o grep — que teria achado o commit — nunca rodava. A versão
    ficava verde sem a segunda entrega.
    """
    host = FakeHostPr(
        [_pr(7), _pr(9, titulo="CH255514 - Ajuste para adicionar mais horarios")],
        {7: [_commit("c1")], 9: [_commit("c2", dia=5)]},
    )

    resultado = _fonte(host, _git_com_master("c1", "c2")).resolve(["255514"])

    assert _hashes(resultado) == ["c1", "c2"]


def test_chamado_com_prefixo_maior_nao_casa_no_titulo():
    # ch255514 NÃO pode casar com a PR do chamado 2555145: `startswith` e `in`
    # não viam a fronteira do número, então o chamado curto roubava a PR do longo.
    host = FakeHostPr([_pr(7, chamado="2555145")], {7: [_commit("c1")]})

    assert _fonte(host, _git_com_master("c1")).resolve(["255514"]) == {}


def test_chamado_com_prefixo_maior_nao_casa_na_branch():
    host = FakeHostPr(
        [_pr(7, chamado="000", branch="bugfix/ch2555145-logs")], {7: [_commit("c1")]}
    )

    assert _fonte(host, _git_com_master("c1")).resolve(["255514"]) == {}


# -- cache de commits por PR ---------------------------------------------------
#
# O cache guarda só `PR -> commits`, que é imutável porque PR mergeada não ganha
# nem perde commit. A varredura continua indo ao host a cada run: é ela que
# descobre PR de correção aberta depois.


def test_pr_nova_e_gravada_no_cache():
    estado = _estado_vazio()
    host = FakeHostPr([_pr(7)], {7: [_commit("c1")]})

    _fonte(host, _git_com_master("c1"), estado).resolve(["255514"])

    assert [c.hash_origem for c in estado.commits_de_pr(REPO_ESTADO, [7])[7]] == ["c1"]


def test_chamado_fica_fora_do_cache():
    # o chamado vem da BUSCA, não da PR: duas tarefas podem apontar para a mesma
    # PR, e carimbar o chamado na linha faria a segunda ler o chamado da primeira.
    estado = _estado_vazio()
    host = FakeHostPr([_pr(7)], {7: [_commit("c1")]})

    _fonte(host, _git_com_master("c1"), estado).resolve(["255514"])

    assert estado.commits_de_pr(REPO_ESTADO, [7])[7][0].chamado == ""


def test_pr_em_cache_nao_pede_os_commits_de_novo():
    estado = _estado_vazio()
    g = _git_com_master("c1")
    host = FakeHostPr([_pr(7)], {7: [_commit("c1")]})

    _fonte(host, g, estado).resolve(["255514"])
    assert host.commits_pedidos == [7], "primeira passada tem que ir ao host"

    host.commits_pedidos.clear()
    resultado = _fonte(host, g, estado).resolve(["255514"])

    assert host.commits_pedidos == [], "PR já em cache não pede os commits"
    assert _hashes(resultado) == ["c1"]
    assert resultado["255514"][0].chamado == "255514", "faltou carimbar na leitura"


def test_pr_nova_no_mesmo_chamado_ainda_e_buscada():
    # o buraco que este desenho evita: cache por PR, não por chamado.
    estado = _estado_vazio()
    g = _git_com_master("c1", "c2")
    commits = {7: [_commit("c1")], 9: [_commit("c2", dia=5)]}

    _fonte(FakeHostPr([_pr(7)], commits), g, estado).resolve(["255514"])
    # PR 9 mergeada depois, no MESMO chamado
    resultado = _fonte(FakeHostPr([_pr(9)], commits), g, estado).resolve(["255514"])

    # a PR 7 vem do índice, a 9 chega nesta varredura
    assert _hashes(resultado) == ["c1", "c2"]


def test_commit_do_cache_ainda_passa_pelo_is_ancestor():
    # is_ancestor fica FORA do cache porque é volátil: PR mergeada numa branch
    # que ainda não chegou na master viraria commit escondido para sempre.
    estado = _estado_vazio()
    host = FakeHostPr([_pr(7)], {7: [_commit("c1")]})

    fora = _fonte(host, _git_com_master("outro"), estado).resolve(["255514"])
    assert fora == {}, "c1 não está na master ainda"
    assert 7 in estado.commits_de_pr(REPO_ESTADO, [7]), "mas foi cacheado"

    dentro = _fonte(host, _git_com_master("c1"), estado).resolve(["255514"])

    assert _hashes(dentro) == ["c1"]


# -- varredura incremental -----------------------------------------------------


def test_primeira_varredura_pede_o_historico_inteiro():
    # sem marca o índice está vazio: filtrar por data deixaria de fora toda PR
    # anterior, e o chamado com PR antiga apareceria como sem entrega.
    host = FakeHostPr([_pr(7)], {7: [_commit("c1")]})

    _fonte(host, _git_com_master("c1")).resolve(["255514"])

    assert host.desde_pedidos == [None]


def test_varredura_seguinte_pede_desde_a_marca():
    estado = _estado_vazio()
    g = _git_com_master("c1")
    host = FakeHostPr([_pr(7)], {7: [_commit("c1")]})

    _fonte(host, g, estado).resolve(["255514"])
    marca = estado.marca_varredura(REPO_ESTADO, HOST)
    assert marca is not None, "primeira varredura tem que gravar a marca"

    _fonte(host, g, estado).resolve(["255514"])

    assert host.desde_pedidos == [None, marca]


def test_uma_varredura_atende_todos_os_chamados():
    # o ganho inteiro: 3 chamados, 1 varredura — não 3 buscas.
    host = FakeHostPr([_pr(7)], {7: [_commit("c1")]})

    _fonte(host, _git_com_master("c1")).resolve(["255514", "999888", "777666"])

    assert len(host.desde_pedidos) == 1


def test_commits_so_das_prs_que_casam_com_algum_chamado():
    # o índice tem 1118 PRs num repo real; buscar os commits de todas encostaria
    # no limite de taxa do host para responder perguntas que ninguém fez.
    estado = _estado_vazio()
    host = FakeHostPr(
        [_pr(7), _pr(8, chamado="999999")],
        {7: [_commit("c1")], 8: [_commit("c9")]},
    )

    _fonte(host, _git_com_master("c1", "c9"), estado).resolve(["255514"])

    assert host.commits_pedidos == [7]
    assert [p.pr_id for p in estado.prs_indexadas(REPO_ESTADO)] == [7, 8], (
        "mas as duas entram no índice"
    )


def test_pr_sem_id_fica_fora_do_indice():
    estado = _estado_vazio()
    host = FakeHostPr([_pr(0), _pr(7)], {7: [_commit("c1")]})

    _fonte(host, _git_com_master("c1"), estado).resolve(["255514"])

    assert [p.pr_id for p in estado.prs_indexadas(REPO_ESTADO)] == [7]


def test_marca_nao_avanca_se_a_varredura_falhar():
    # marca avançada com índice incompleto é perda permanente: as PRs que
    # faltaram ficam fora de toda janela futura.
    estado = _estado_vazio()
    host = FakeHostPr(err=BackendIndisponivel("boom"))

    with pytest.raises(BackendIndisponivel):
        _fonte(host, _git_com_master("c1"), estado).resolve(["255514"])

    assert estado.marca_varredura(REPO_ESTADO, HOST) is None


def test_troca_de_host_varre_historico_inteiro():
    """A marca e o cache do host antigo não atravessam: `pr_id` igual no host
    novo é outra PR, e a marca antiga faria o novo pular o histórico."""
    estado = _estado_vazio()
    g = _git_com_master("c1", "c2")
    _fonte(
        FakeHostPr([_pr(7)], {7: [_commit("c1")]}), g, estado, nome_host="a"
    ).resolve(["255514"])

    novo = FakeHostPr([_pr(7)], {7: [_commit("c2")]})
    resultado = _fonte(novo, g, estado, nome_host="b").resolve(["255514"])

    assert novo.desde_pedidos == [None]
    assert novo.commits_pedidos == [7], "o cache do host antigo não vale"
    assert _hashes(resultado) == ["c2"]


def test_sem_chamado_nao_cobra_a_referencia():
    def sem_padrao() -> Referencia:
        raise AssertionError("não deveria resolver a referência")

    fonte = PrCommitSource(
        FakeHostPr(),
        HOST,
        _git_com_master("c1"),
        estado=_estado_vazio(),
        repo_estado=REPO_ESTADO,
        referencia=sem_padrao,
        ref_principal=lambda: "origin/master",
    )

    assert fonte.resolve([""]) == {}


# -- referência configurável ---------------------------------------------------


def _casadas(prs: list[PrIndex], referencia: Referencia, chamado: str) -> list[str]:
    """Hashes achados para `chamado`; a PR `n` entrega o commit `c<n+1>`."""
    g = _git_com_master("c1", *(f"c{pr.pr_id + 1}" for pr in prs))
    host = FakeHostPr(prs, {pr.pr_id: [_commit(f"c{pr.pr_id + 1}")] for pr in prs})
    fonte = _fonte(host, g, referencia=referencia)
    return _hashes(fonte.resolve([chamado]), chamado)


def test_pr_com_padrao_id_casa_pelo_titulo_e_protege_os_dois_lados_da_branch():
    ref = Referencia("{id}")
    assert _casadas(
        [_pr(1, titulo="PAY-123 corrige", branch="feature/x")], ref, "PAY-123"
    ) == ["c2"]
    # Fronteira nos dois lados pelo alfabeto: nem prefixo nem sufixo do ID.
    prs = [
        _pr(1, titulo="outra", branch="x-PAY-12"),
        _pr(2, titulo="outra", branch="XPAY-1"),
    ]
    assert _casadas(prs, ref, "PAY-1") == []


def test_pr_com_padrao_entre_colchetes_casa_na_branch_colada():
    # A ponta `]` não é do alfabeto: o lado direito fica livre.
    prs = [_pr(1, titulo="outra", branch="[PAY-12]x")]
    assert _casadas(prs, Referencia("[{id}]"), "PAY-12") == ["c2"]
