"""Camada de montagem: e ela que decide quais adapters concretos o engine usa.

Dois invariantes vivem aqui. O primeiro e a prioridade das fontes de commit. O
segundo e o mais facil de perder de vista: **montar nao faz I/O**. Se a
montagem tocar o git ou a rede, todo comando passa a pagar por ela — inclusive
`atualizar --abort` e `reconstruir-estado`, que nunca chamam essas fontes.
"""

from __future__ import annotations

import pytest

from motor import montagem
from motor.adapters.commitsource.bitbucket import BitbucketPRCommitSource
from motor.adapters.commitsource.chain import ChainCommitSource
from motor.adapters.commitsource.grep import GrepCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.atribuicoes import Exata
from motor.config import ConfigProjeto, Escolhido, validar_nome_repo
from motor.domain.referencia import ALFABETO_PADRAO, Referencia
from motor.domain.types import RepoInfo
from motor.errors import ErroDeEntrada
from motor.esquemas.semver import Semver
from motor.montagem import (
    CredenciaisBitbucket,
    FonteDaConfig,
    FonteTasks,
    montar_commit_source,
    montar_deps,
    montar_task_source,
)
from motor.services.versionamento import Versionamento
from tests.fontes_falsas import REFERENCIA_CH, FonteFixa


class GitQueGritaSeUsado(FakeGit):
    """Qualquer chamada de porta durante a montagem e um erro, nao um detalhe."""

    def remote_url(self, remote: str) -> str:
        raise AssertionError("montar_commit_source nao pode tocar o git")

    def fetch(self, remote: str) -> None:
        raise AssertionError("montar_commit_source nao pode tocar o git")


# -- fontes de commit ---------------------------------------------------------


def test_sem_token_a_fonte_e_so_o_grep():
    # sem cadeia: um ChainCommitSource de um elemento so seria indireção pura.
    fonte = montar_commit_source(FakeGit(), referencia=lambda: REFERENCIA_CH)

    assert isinstance(fonte, GrepCommitSource)


def test_sem_estado_nao_monta_a_fonte_de_pr():
    # a fonte de PR le o indice local de PRs, que vive no estado. Sem banco ela
    # nao teria o que ler e devolveria vazio para todo chamado — pior que o grep.
    fonte = montar_commit_source(
        FakeGit(),
        referencia=lambda: REFERENCIA_CH,
        bitbucket=CredenciaisBitbucket("tok", "dev@x.com"),
    )

    assert isinstance(fonte, GrepCommitSource)


def test_com_token_a_pr_vem_antes_do_grep():
    # ordem = prioridade: a PR e mais confiavel que o grep de mensagem, e o
    # grep fica de fallback para o chamado que nenhuma PR casou.
    fonte = montar_commit_source(
        FakeGit(),
        referencia=lambda: REFERENCIA_CH,
        bitbucket=CredenciaisBitbucket("tok", "dev@x.com"),
        estado=FakeEstado(repos={"r": RepoInfo(nome="r")}),
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
    estado = FakeEstado(repos={"vbweb": RepoInfo(nome="vbweb")})

    fonte = montar_commit_source(
        FakeGit(),
        referencia=lambda: REFERENCIA_CH,
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
        GitQueGritaSeUsado(),
        referencia=lambda: REFERENCIA_CH,
        bitbucket=CredenciaisBitbucket(token, "dev@x.com"),
    )


def test_o_grep_varre_a_principal_do_versionamento():
    """A ref varrida e `origin/<principal>` da config, nao `master` fixo."""
    import datetime

    git = FakeGit()
    d = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    git.add_commit("c0", "", "ch123456 alfa", d)
    git.set_branch("origin/dev", "c0")
    chamadas: list[str] = []

    def versionamento() -> Versionamento:
        chamadas.append("x")
        return Versionamento(esquema=Semver(), politica=Exata(), principal="dev")

    fonte = montar_commit_source(
        git, referencia=lambda: REFERENCIA_CH, versionamento=versionamento
    )
    assert chamadas == []

    achados = fonte.resolve(["123456"])

    assert [c.hash_origem for c in achados["123456"]] == ["c0"]


# -- fonte de tasks -----------------------------------------------------------


def test_task_source_manual_le_a_lista(tmp_path):
    lista = tmp_path / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")

    fonte = montar_task_source(ConfigProjeto(), fonte="manual", lista_manual=str(lista))

    assert fonte.fetch("13.34.0") == ["123456"]


def _config_com_fonte(valor: str, **tarefas: object) -> ConfigProjeto:
    return ConfigProjeto(
        tarefas={"fonte": valor, **tarefas},
        arquivos=("/a.toml", "/b.toml"),
        fonte_tarefas=Escolhido(valor, "/a.toml", "central"),
    )


def test_task_source_da_config_nao_carrega_o_plugin_na_montagem():
    # montar nao e usar: `reconstruir-estado` recebe esta fonte e nunca a chama.
    fonte = montar_task_source(_config_com_fonte("inexistente"))

    assert isinstance(fonte, FonteDaConfig)


def test_task_source_da_config_busca_pelo_plugin():
    fonte = montar_task_source(
        _config_com_fonte("tests.fontes_falsas:FonteFixa", chamados=["101"])
    )

    assert fonte.fetch("1.0.0") == ["101"]


def test_plugin_recebe_tarefas_e_arquivos_nomeados():
    fonte = montar_task_source(
        _config_com_fonte("tests.fontes_falsas:FonteFixa", sistema=7)
    )
    fonte.fetch("1.0.0")

    recebido = FonteFixa.recebidos[-1]
    assert set(recebido) == {"tarefas", "arquivos"}
    assert recebido["arquivos"] == ("/a.toml", "/b.toml")
    tarefas = recebido["tarefas"]
    assert isinstance(tarefas, dict)
    assert tarefas["fonte"] == "tests.fontes_falsas:FonteFixa"
    assert tarefas["sistema"] == 7


def test_plugin_carregado_uma_vez_por_invocacao():
    fonte = FonteDaConfig(_config_com_fonte("tests.fontes_falsas:FonteFixa"))
    antes = len(FonteFixa.recebidos)

    fonte.fetch("1.0.0")
    fonte.fetch("1.0.0")
    fonte.proposta()

    assert len(FonteFixa.recebidos) == antes + 1


def test_falha_ao_carregar_nao_fica_em_cache():
    fonte = FonteDaConfig(
        _config_com_fonte("tests.fontes_falsas:FonteConstrutorQuebra")
    )

    for _ in range(2):
        with pytest.raises(ErroDeEntrada, match="construtor quebrou"):
            fonte.fetch("1.0.0")


def test_construtor_com_bug_vira_erro_de_entrada():
    fonte = montar_task_source(
        _config_com_fonte("tests.fontes_falsas:FonteConstrutorComBug")
    )

    with pytest.raises(ErroDeEntrada, match="construtor falhou"):
        fonte.fetch("1.0.0")


# -- referencia de tarefa ----------------------------------------------------


@pytest.fixture
def repo_montavel(monkeypatch, tmp_path):
    """Raiz de repo com git e estado fakes e config global isolada."""
    raiz = tmp_path / "repo"
    raiz.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    estado = FakeEstado(repos={"repo": RepoInfo(nome="repo")})
    monkeypatch.setattr(montagem, "new_git_subprocess", lambda *_, **__: FakeGit())
    monkeypatch.setattr(montagem, "PostgresEstado", lambda sessao: estado)
    return raiz


def _lista(raiz):
    lista = raiz.parent / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")
    return FonteTasks(fonte="manual", lista_manual=str(lista))


def _fonte_central(raiz, valor: str) -> None:
    central = raiz.parent / "xdg" / "monitor-versoes"
    central.mkdir(parents=True, exist_ok=True)
    (central / "config.toml").write_text(f'[tarefas]\nfonte = "{valor}"\n')


def test_fonte_da_config_sem_padrao_propoe_a_referencia_dela(repo_montavel):
    _fonte_central(repo_montavel, "tests.fontes_falsas:FonteFixa")

    deps = montar_deps(str(repo_montavel), None)  # type: ignore[arg-type]

    assert deps.referencia() == REFERENCIA_CH


def test_montar_deps_nao_carrega_o_plugin(repo_montavel):
    _fonte_central(repo_montavel, "inexistente")

    deps = montar_deps(str(repo_montavel), None)  # type: ignore[arg-type]

    with pytest.raises(ErroDeEntrada, match="plugin 'inexistente' nao encontrado"):
        deps.referencia()


def test_lista_manual_sem_padrao_monta_e_so_cobra_no_uso(repo_montavel):
    # montar nao pode falhar: `atualizar --abort` nao usa a referencia.
    deps = montar_deps(str(repo_montavel), None, tasks=_lista(repo_montavel))  # type: ignore[arg-type]

    with pytest.raises(ErroDeEntrada) as e:
        deps.referencia()
    # O texto é requisito: diz a chave que falta.
    assert "[referencia] padrao" in str(e.value)


def test_lista_manual_com_padrao_usa_o_alfabeto_default(repo_montavel):
    (repo_montavel / ".monitor-versoes.toml").write_text(
        '[referencia]\npadrao = "ch{id}"\n'
    )

    deps = montar_deps(str(repo_montavel), None, tasks=_lista(repo_montavel))  # type: ignore[arg-type]

    assert deps.referencia() == Referencia("ch{id}", ALFABETO_PADRAO)


@pytest.fixture
def sem_bitbucket_no_ambiente(monkeypatch):
    monkeypatch.setenv("BITBUCKET_TOKEN", "")
    monkeypatch.setenv("BITBUCKET_EMAIL", "")


def _entradas(raiz, **kwargs) -> str:
    return montar_deps(str(raiz), None, **kwargs).identidade_das_entradas()  # type: ignore[arg-type]


def test_identidade_muda_com_a_fonte(repo_montavel, sem_bitbucket_no_ambiente):
    _fonte_central(repo_montavel, "tests.fontes_falsas:FonteFixa")
    antes = _entradas(repo_montavel)
    _fonte_central(repo_montavel, "tests.fontes_falsas:FonteComCredencial")

    assert _entradas(repo_montavel) != antes


def test_entradas_mudam_com_a_fonte_de_tasks(repo_montavel, sem_bitbucket_no_ambiente):
    assert _entradas(repo_montavel) != _entradas(
        repo_montavel, tasks=_lista(repo_montavel)
    )


def test_entradas_mudam_com_o_conteudo_da_lista(
    repo_montavel, sem_bitbucket_no_ambiente
):
    fonte = _lista(repo_montavel)
    antes = _entradas(repo_montavel, tasks=fonte)
    with open(fonte.lista_manual, "a", encoding="utf-8") as f:
        f.write("654321\n")

    assert _entradas(repo_montavel, tasks=fonte) != antes


def test_entradas_mudam_com_a_fonte_de_commits(
    repo_montavel, sem_bitbucket_no_ambiente
):
    com_pr = CredenciaisBitbucket(token="t", email="e")
    assert _entradas(repo_montavel) != _entradas(repo_montavel, bitbucket=com_pr)


def test_entradas_mudam_com_a_config_de_referencia_e_piso(
    repo_montavel, sem_bitbucket_no_ambiente
):
    antes = _entradas(repo_montavel)
    (repo_montavel / ".monitor-versoes.toml").write_text(
        '[referencia]\npadrao = "ch{id}"\n'
    )

    assert _entradas(repo_montavel) != antes


def test_entradas_mudam_com_o_sistema_de_tarefas(
    repo_montavel, sem_bitbucket_no_ambiente
):
    (repo_montavel / ".monitor-versoes.toml").write_text("[tarefas]\nsistema = 7\n")
    antes = _entradas(repo_montavel)
    (repo_montavel / ".monitor-versoes.toml").write_text("[tarefas]\nsistema = 8\n")

    assert _entradas(repo_montavel) != antes


def test_entradas_iguais_para_a_mesma_invocacao(
    repo_montavel, sem_bitbucket_no_ambiente
):
    assert _entradas(repo_montavel) == _entradas(repo_montavel)


# -- validadores --------------------------------------------------------------


def test_nome_repo_aceita_basename():
    assert validar_nome_repo("backend") == "backend"


@pytest.mark.parametrize("valor", ["pasta/backend", " backend", "backend ", "", "  "])
def test_nome_repo_recusa_o_que_fragmentaria_o_estado(valor):
    # o nome e a chave do estado: aceitar caminho ou espaco em volta criaria
    # duas linhas paralelas para o mesmo repo, sem erro nenhum aparecer.
    with pytest.raises(ErroDeEntrada, match="nome simples"):
        validar_nome_repo(valor)


def test_validadores_levantam_erro_de_entrada():
    """O formulario da TUI captura isto. Com MotorError generico ele capturaria
    tambem erro de banco vindo do mesmo bloco, e mostraria falha de conexao
    dentro do campo de texto.
    """
    with pytest.raises(ErroDeEntrada, match="nome simples"):
        validar_nome_repo("pasta/backend")


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
