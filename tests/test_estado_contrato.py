"""Contrato de EstadoRepo: as MESMAS assercoes contra o fake e contra o Postgres.

Por que este arquivo existe. `FakeEstado` e o que a suite inteira usa no lugar do
banco. Onde ele e o `PostgresEstado` discordam, a suite fica verde num
comportamento que nao existe em producao — e este projeto pagou por isso tres
vezes: o `FakeGit` divergiu do adapter real e escondeu um bug; o fake aceitou
escrever atribuicao em versao nunca registrada onde a FK do banco recusa; e o
fake devolvia ordem de insercao onde o adapter usa ORDER BY.

Antes deste arquivo o contrato existia so como prosa num relatorio de processo, e
as duas implementacoes eram cobertas por duas suites escritas a mao em paralelo —
que e exatamente como a divergencia volta. Aqui cada assercao roda duas vezes: uma
sem banco, uma contra o Postgres de verdade. O parametro `postgres` carrega
`integracao`, entao pula junto com os outros quando nao ha banco.

Ao acrescentar comportamento em `EstadoRepo`, a assercao vem para ca. Teste que
existe so num dos lados nao e contrato, e uma opiniao.
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import text

from motor.adapters.estado.fake import FakeEstado
from motor.domain.types import Atribuicao, RepoInfo, VersaoInfo, VersionType
from motor.errors import MotorError

REPO = "vendabemweb"
ALIAS = "vbweb"
SISTEMA_ID = 7
QUANDO = datetime.datetime(2026, 1, 15, 10, 30, tzinfo=datetime.UTC)
DEPOIS = datetime.datetime(2026, 6, 1, 8, 0, tzinfo=datetime.UTC)


def _base(numero: str = "13.34.0") -> VersaoInfo:
    return VersaoInfo(
        numero=numero,
        tipo=VersionType.FECHADA,
        base_ref="13.33.0",
        base_commit="aaa111",
    )


@pytest.fixture(
    params=[
        "fake",
        pytest.param("postgres", marks=pytest.mark.integracao),
    ]
)
def estado(request):
    """Uma implementacao de EstadoRepo com o repo canonico e o alias semeados.

    Semear e a unica coisa que difere entre as duas: o fake recebe dicts, o
    Postgres recebe linhas. Tudo depois disto e identico por contrato.
    """
    if request.param == "fake":
        return FakeEstado(
            repos={REPO: RepoInfo(nome=REPO, tickio_sistema_id=SISTEMA_ID)},
            aliases={ALIAS: REPO},
        )

    from motor.adapters.estado.postgres import PostgresEstado

    sessao = request.getfixturevalue("sessao_postgres")
    sessao.execute(
        text("insert into repo (nome, tickio_sistema_id) values (:n, :s)"),
        {"n": REPO, "s": SISTEMA_ID},
    )
    sessao.execute(
        text("insert into repo_alias (nome, repo_id) select :a, id from repo"),
        {"a": ALIAS},
    )
    sessao.commit()
    return PostgresEstado(sessao=sessao)


# -- resolucao de repo --------------------------------------------------------


def test_resolver_repo_por_nome_e_por_alias(estado):
    assert estado.resolver_repo(REPO).tickio_sistema_id == SISTEMA_ID
    # o alias devolve o nome CANONICO: e ele que chaveia todo o resto do estado
    assert estado.resolver_repo(ALIAS).nome == REPO


def test_resolver_repo_desconhecido_indica_o_comando_de_cadastro(estado):
    with pytest.raises(MotorError, match="desconhecido") as e:
        estado.resolver_repo("nao-existe")
    assert "motor repo adicionar" in str(e.value)


def test_registrar_repo_o_torna_resolvivel(estado):
    estado.registrar_repo("novo-repo", 23)

    assert estado.resolver_repo("novo-repo") == RepoInfo(
        nome="novo-repo", tickio_sistema_id=23
    )


def test_registrar_repo_recusa_nome_duplicado(estado):
    with pytest.raises(MotorError, match="ja cadastrado"):
        estado.registrar_repo(REPO, 99)

    assert estado.resolver_repo(REPO).tickio_sistema_id == SISTEMA_ID


def test_registrar_repo_recusa_nome_que_ja_e_alias(estado):
    with pytest.raises(MotorError, match="ja cadastrado"):
        estado.registrar_repo(ALIAS, 99)

    assert estado.resolver_repo(ALIAS).nome == REPO


def test_listar_repos_devolve_canonicos_em_ordem_sem_alias(estado):
    estado.registrar_repo("zzz", 99)
    estado.registrar_repo("aaa", 11)

    assert estado.listar_repos() == [
        RepoInfo(nome="aaa", tickio_sistema_id=11),
        RepoInfo(nome=REPO, tickio_sistema_id=SISTEMA_ID),
        RepoInfo(nome="zzz", tickio_sistema_id=99),
    ]


@pytest.mark.parametrize(
    "chamada",
    [
        pytest.param(lambda e: e.versao("outro", "13.34.0"), id="versao"),
        pytest.param(lambda e: e.atribuicoes("outro", "13.34.0"), id="atribuicoes"),
        pytest.param(lambda e: e.exclusoes("outro"), id="exclusoes"),
        pytest.param(lambda e: e.sem_entrega("outro"), id="sem_entrega"),
        pytest.param(
            lambda e: e.registrar_versao("outro", _base()), id="registrar_versao"
        ),
        pytest.param(
            lambda e: e.marcar_liberadas("outro", {"13.34.0": QUANDO}),
            id="marcar_liberadas",
        ),
    ],
)
def test_repo_desconhecido_levanta_em_todo_metodo(estado, chamada):
    # o fake devolvia None/[]/{} ou gravava versao pendurada num repo
    # inexistente; o banco levanta por causa da FK. Silencio de um lado e erro do
    # outro e como um caminho quebrado passa por verde.
    with pytest.raises(MotorError, match="nao encontrado no estado"):
        chamada(estado)


# -- registro de versao e congelamento ----------------------------------------


def test_versao_nao_registrada_e_none(estado):
    assert estado.versao(REPO, "13.34.0") is None


def test_registrar_versao_e_no_op_total_na_segunda_chamada(estado):
    estado.registrar_versao(REPO, _base())
    estado.registrar_versao(
        REPO,
        VersaoInfo(
            numero="13.34.0",
            tipo=VersionType.CLIENTE,
            base_ref="OUTRA",
            base_commit="bbb222",
        ),
    )

    info = estado.versao(REPO, "13.34.0")
    # nenhum campo cede, nao so o base_commit: a base e o ponto onde a branch foi
    # cortada. Recomputar faria a base de uma X.0.0 seguir o tip do master e o
    # oraculo de presenca passaria a considerar presente tudo que entrou depois.
    assert (info.tipo, info.base_ref, info.base_commit) == (
        VersionType.FECHADA,
        "13.33.0",
        "aaa111",
    )


def test_marcar_liberadas_ignora_versao_que_nao_esta_no_estado(estado):
    estado.marcar_liberadas(REPO, {"99.0.0": QUANDO})  # nao levanta
    assert estado.versao(REPO, "99.0.0") is None


def test_marcar_liberadas_nao_reescreve_data_ja_gravada(estado):
    estado.registrar_versao(REPO, _base())
    estado.marcar_liberadas(REPO, {"13.34.0": QUANDO})
    estado.marcar_liberadas(REPO, {"13.34.0": DEPOIS})

    # a primeira data vence: e a data do commit apontado pela tag, nao a do run
    assert estado.versao(REPO, "13.34.0").liberada_em == QUANDO


# -- atribuicoes --------------------------------------------------------------


def test_substituir_atribuicoes_recusa_versao_nao_registrada(estado):
    # no Postgres seria violacao de FK; o fake tem de recusar igual
    with pytest.raises(MotorError, match="nao registrada no estado"):
        estado.substituir_atribuicoes(REPO, "13.34.0", [Atribuicao(chamado="1")])


def test_substituir_atribuicoes_recusa_versao_liberada(estado):
    estado.registrar_versao(REPO, _base())
    estado.substituir_atribuicoes(REPO, "13.34.0", [Atribuicao(chamado="123456")])
    estado.marcar_liberadas(REPO, {"13.34.0": QUANDO})

    with pytest.raises(MotorError, match="imutavel"):
        estado.substituir_atribuicoes(REPO, "13.34.0", [Atribuicao(chamado="999")])

    assert [a.chamado for a in estado.atribuicoes(REPO, "13.34.0")] == ["123456"]


def test_substituir_atribuicoes_recusa_liberada_mesmo_com_snapshot_vazio(estado):
    # o caso que a trigger do banco NAO pega: zero delete, zero insert, commit
    # limpo. A recusa tem de ser invariante, nao subproduto de linha tocada.
    estado.registrar_versao(REPO, _base())
    estado.marcar_liberadas(REPO, {"13.34.0": QUANDO})

    with pytest.raises(MotorError, match="imutavel"):
        estado.substituir_atribuicoes(REPO, "13.34.0", [])


def test_substituir_atribuicoes_troca_o_conjunto_nao_soma(estado):
    estado.registrar_versao(REPO, _base())
    estado.substituir_atribuicoes(REPO, "13.34.0", [Atribuicao(chamado="111")])
    estado.substituir_atribuicoes(REPO, "13.34.0", [Atribuicao(chamado="222")])

    assert [a.chamado for a in estado.atribuicoes(REPO, "13.34.0")] == ["222"]


def test_atribuicoes_ordenadas_por_chamado_e_por_hash(estado):
    estado.registrar_versao(REPO, _base())
    estado.substituir_atribuicoes(
        REPO,
        "13.34.0",
        [
            Atribuicao(chamado="222", commits=["zzz", "aaa"]),
            Atribuicao(chamado="111", commits=["mmm"]),
        ],
    )

    lidas = estado.atribuicoes(REPO, "13.34.0")
    # ordem determinista nas DUAS dimensoes. O fake era dict e devolvia ordem de
    # insercao por acidente, o que mascararia um ORDER BY faltando no adapter.
    assert [a.chamado for a in lidas] == ["111", "222"]
    assert lidas[1].commits == ["aaa", "zzz"]


def test_atribuicoes_devolve_copia_nao_referencia_viva(estado):
    estado.registrar_versao(REPO, _base())
    estado.substituir_atribuicoes(
        REPO, "13.34.0", [Atribuicao(chamado="111", commits=["aaa"])]
    )

    estado.atribuicoes(REPO, "13.34.0")[0].commits.append("INVADIDO")

    # `commits` e list mutavel dentro de dataclass frozen: sem copia, o chamador
    # corrompe o estado. O Postgres materializa linha nova a cada query.
    assert estado.atribuicoes(REPO, "13.34.0")[0].commits == ["aaa"]


def test_atribuicoes_de_versao_sem_nada_e_lista_vazia(estado):
    estado.registrar_versao(REPO, _base())
    assert estado.atribuicoes(REPO, "13.34.0") == []


# -- julgamento humano (so leitura por enquanto) -------------------------------


def test_exclusoes_e_sem_entrega_comecam_vazias(estado):
    # nada no motor escreve nestas duas ainda: entram por psql. O contrato aqui e
    # que ler um repo sem julgamento nao levanta nem inventa linha.
    assert estado.exclusoes(REPO) == []
    assert estado.sem_entrega(REPO) == {}
