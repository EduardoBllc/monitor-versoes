"""Camada de montagem: e ela que decide quais adapters concretos o engine usa.

Dois invariantes vivem aqui. O primeiro e a prioridade das fontes de commit. O
segundo e o mais facil de perder de vista: **montar nao faz I/O**. Se a
montagem tocar o git ou a rede, todo comando passa a pagar por ela — inclusive
`atualizar --abort` e `reconstruir-estado`, que nunca chamam essas fontes.
"""

from __future__ import annotations

import pytest

from motor.adapters.commitsource.bitbucket import BitbucketPRCommitSource
from motor.adapters.commitsource.chain import ChainCommitSource
from motor.adapters.commitsource.grep import GrepCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.tickio import TickioRest
from motor.domain.types import RepoInfo
from motor.errors import ErroDeEntrada
from motor.montagem import (
    CredenciaisBitbucket,
    montar_commit_source,
    montar_task_source,
    validar_nome_repo,
    validar_sistema_id,
    validar_versao,
)


class GitQueGritaSeUsado(FakeGit):
    """Qualquer chamada de porta durante a montagem e um erro, nao um detalhe."""

    def remote_url(self, remote: str) -> str:
        raise AssertionError("montar_commit_source nao pode tocar o git")

    def fetch(self, remote: str) -> None:
        raise AssertionError("montar_commit_source nao pode tocar o git")


# -- fontes de commit ---------------------------------------------------------


def test_sem_token_a_fonte_e_so_o_grep():
    # sem cadeia: um ChainCommitSource de um elemento so seria indireção pura.
    fonte = montar_commit_source(FakeGit())

    assert isinstance(fonte, GrepCommitSource)


def test_sem_estado_nao_monta_a_fonte_de_pr():
    # a fonte de PR le o indice local de PRs, que vive no estado. Sem banco ela
    # nao teria o que ler e devolveria vazio para todo chamado — pior que o grep.
    fonte = montar_commit_source(
        FakeGit(), bitbucket=CredenciaisBitbucket("tok", "dev@x.com")
    )

    assert isinstance(fonte, GrepCommitSource)


def test_com_token_a_pr_vem_antes_do_grep():
    # ordem = prioridade: a PR e mais confiavel que o grep de mensagem, e o
    # grep fica de fallback para o chamado que nenhuma PR casou.
    fonte = montar_commit_source(
        FakeGit(),
        bitbucket=CredenciaisBitbucket("tok", "dev@x.com"),
        estado=FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)}),
        repo="r",
    )

    assert isinstance(fonte, ChainCommitSource)
    assert [type(f) for f in fonte.sources] == [
        BitbucketPRCommitSource,
        GrepCommitSource,
    ]


def test_a_fonte_de_pr_recebe_o_cache_do_estado():
    # sem o estado e o nome canonico do repo, a fonte roda sem cache e volta a
    # pedir os commits de toda PR a cada verificar.
    estado = FakeEstado(repos={"vbweb": RepoInfo(nome="vbweb", tickio_sistema_id=1)})

    fonte = montar_commit_source(
        FakeGit(),
        bitbucket=CredenciaisBitbucket("tok", "dev@x.com"),
        estado=estado,
        repo="vbweb",
    )

    assert isinstance(fonte, ChainCommitSource)
    pr = fonte.sources[0]
    assert isinstance(pr, BitbucketPRCommitSource)
    assert (pr.estado, pr.repo_estado) == (estado, "vbweb")


@pytest.mark.parametrize("token", ["", "tok"])
def test_montar_nao_toca_o_git(token):
    """`atualizar --abort` monta esta fonte e nunca a usa. Resolver o
    workspace/repo agora faria todo comando pagar uma chamada de git, e um
    clone sem `origin` passaria a falhar na montagem em vez de na busca.
    """
    montar_commit_source(
        GitQueGritaSeUsado(), bitbucket=CredenciaisBitbucket(token, "dev@x.com")
    )


# -- fonte de tasks -----------------------------------------------------------


def test_task_source_manual_ignora_as_variaveis_do_tickio(tmp_path):
    lista = tmp_path / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")

    fonte = montar_task_source(7, fonte="manual", lista_manual=str(lista))

    assert fonte.fetch("13.34.0") == ["123456"]


def test_task_source_tickio_nao_cobra_credencial_na_montagem(monkeypatch):
    # montar nao e usar: `reconstruir-estado` recebe esta fonte e nunca a chama.
    for var in ("TICKIO_BASE_URL", "TICKIO_USER", "TICKIO_PASSWORD"):
        monkeypatch.setenv(var, "")

    fonte = montar_task_source(7)

    assert isinstance(fonte, TickioRest)
    assert fonte.sistema_id == 7


# -- validadores --------------------------------------------------------------


def test_nome_repo_aceita_basename():
    assert validar_nome_repo("backend") == "backend"


@pytest.mark.parametrize("valor", ["pasta/backend", " backend", "backend ", "", "  "])
def test_nome_repo_recusa_o_que_fragmentaria_o_estado(valor):
    # o nome e a chave do estado: aceitar caminho ou espaco em volta criaria
    # duas linhas paralelas para o mesmo repo, sem erro nenhum aparecer.
    with pytest.raises(ErroDeEntrada, match="nome simples"):
        validar_nome_repo(valor)


@pytest.mark.parametrize("valor", ["2.3.1", " 2.3.1 "])
def test_versao_devolve_o_valor_aparado(valor):
    assert validar_versao(valor) == "2.3.1"


@pytest.mark.parametrize("valor", ["abc", "  "])
def test_versao_recusa_o_que_nao_e_versao(valor):
    with pytest.raises(ErroDeEntrada):
        validar_versao(valor)


def test_sistema_id_converte_para_int():
    assert validar_sistema_id("42") == 42


@pytest.mark.parametrize("valor", ["0", "-1", "abc", "", "1.5"])
def test_sistema_id_recusa_o_que_nao_e_inteiro_positivo(valor):
    with pytest.raises(ErroDeEntrada, match="inteiro positivo"):
        validar_sistema_id(valor)


def test_validadores_levantam_erro_de_entrada():
    """O formulario da TUI captura isto. Com MotorError generico ele capturaria
    tambem erro de banco vindo do mesmo bloco, e mostraria falha de conexao
    dentro do campo de texto.
    """
    with pytest.raises(ErroDeEntrada, match="nome simples"):
        validar_nome_repo("pasta/backend")
    with pytest.raises(ErroDeEntrada, match="inteiro positivo"):
        validar_sistema_id("0")


def test_primeiro_uso_cria_arquivo_e_esquema_do_sqlite(monkeypatch, tmp_path):
    from sqlalchemy import text

    from motor.montagem import abrir_sessao

    caminho = tmp_path / "novo" / "estado.db"
    monkeypatch.delenv("DATABASE_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_SQLITE_PATH", str(caminho))

    with abrir_sessao() as sessao:
        revisao = sessao.execute(
            text("select version_num from alembic_version")
        ).scalar()

    assert caminho.is_file()
    assert revisao is not None


def test_diagnostico_nao_cria_esquema(monkeypatch, tmp_path):
    from motor.adapters.estado.postgres import PostgresEstado
    from motor.montagem import abrir_sessao

    monkeypatch.delenv("DATABASE_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_SQLITE_PATH", str(tmp_path / "estado.db"))

    with abrir_sessao(garantir=False) as sessao:
        assert PostgresEstado(sessao=sessao).revisao_migracao() is None
