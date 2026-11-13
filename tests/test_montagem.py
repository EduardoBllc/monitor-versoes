"""Camada de montagem: e ela que decide quais adapters concretos o engine usa.

Dois invariantes vivem aqui. O primeiro e a prioridade das fontes de commit. O
segundo e o mais facil de perder de vista: **montar nao faz I/O**. Se a
montagem tocar o git ou a rede, todo comando passa a pagar por ela — inclusive
`atualizar --abort` e `reconstruir-estado`, que nunca chamam essas fontes.
"""

from __future__ import annotations

import pytest

from motor import montagem
from motor.adapters.commitsource.chain import ChainCommitSource
from motor.adapters.commitsource.grep import GrepCommitSource
from motor.adapters.commitsource.pr import PrCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.sugestao.fake import FakeProvedorSugestao
from motor.atribuicoes import Exata
from motor.config import (
    ConfigProjeto,
    Escolhido,
    carregar_config_repo,
    validar_nome_repo,
)
from motor.domain.referencia import ALFABETO_PADRAO, Referencia
from motor.domain.types import RepoInfo
from motor.errors import ErroDeEntrada
from motor.esquemas.semver import Semver
from motor.montagem import (
    FonteDaConfig,
    FonteTasks,
    HostDaConfig,
    instanciar_fonte_tarefas,
    instanciar_provedor_sugestao,
    montar_commit_source,
    montar_deps,
    montar_task_source,
)
from motor.services.versionamento import Versionamento
from tests.config_repos import secao_repo
from tests.fontes_falsas import REFERENCIA_CH, FonteFixa, HostFalso


class GitQueGritaSeUsado(FakeGit):
    """Qualquer chamada de porta durante a montagem e um erro, nao um detalhe."""

    def remote_url(self, remote: str) -> str:
        raise AssertionError("montar_commit_source nao pode tocar o git")

    def fetch(self, remote: str) -> None:
        raise AssertionError("montar_commit_source nao pode tocar o git")


# -- fontes de commit ---------------------------------------------------------


HOST_FALSO = "tests.fontes_falsas:HostFalso"
HOST_SEM_VERIFICACAO = "tests.fontes_falsas:HostSemVerificacao"


def _config_com_host(valor: str = HOST_FALSO, **prs: object) -> ConfigProjeto:
    return ConfigProjeto(
        prs={"fonte": valor, **prs},
        arquivos=("/a.toml", "/b.toml"),
        fonte_prs=Escolhido(valor, "/a.toml"),
    )


def _estado() -> FakeEstado:
    return FakeEstado(repos={"r": RepoInfo(nome="r")})


def test_sem_fonte_de_pr_so_grep():
    # sem cadeia: um ChainCommitSource de um elemento so seria indireção pura.
    fonte = montar_commit_source(
        FakeGit(),
        referencia=lambda: REFERENCIA_CH,
        config=ConfigProjeto(),
        estado=_estado(),
        repo="r",
    )

    assert isinstance(fonte, GrepCommitSource)


def test_sem_estado_nao_monta_a_fonte_de_pr():
    # a fonte de PR le o indice local de PRs, que vive no estado. Sem banco ela
    # nao teria o que ler e devolveria vazio para todo chamado — pior que o grep.
    fonte = montar_commit_source(
        FakeGit(), referencia=lambda: REFERENCIA_CH, config=_config_com_host()
    )

    assert isinstance(fonte, GrepCommitSource)


def test_com_fonte_de_pr_encadeia_pr_e_grep():
    # ordem = prioridade: a PR e mais confiavel que o grep de mensagem, e o
    # grep fica de fallback para o chamado que nenhuma PR casou.
    estado = _estado()
    fonte = montar_commit_source(
        FakeGit(),
        referencia=lambda: REFERENCIA_CH,
        config=_config_com_host(),
        estado=estado,
        repo="r",
    )

    assert isinstance(fonte, ChainCommitSource)
    pr, grep = fonte.sources
    assert isinstance(grep, GrepCommitSource)
    assert isinstance(pr, PrCommitSource)
    # o nome do host e a chave do estado: troca-lo zera indice, marca e cache.
    assert (pr.nome_host, pr.estado, pr.repo_estado) == (HOST_FALSO, estado, "r")


@pytest.mark.parametrize("config", [ConfigProjeto(), _config_com_host("inexistente")])
def test_montar_nao_toca_o_git(config):
    """`atualizar --abort` monta esta fonte e nunca a usa. Ler o remote agora
    faria todo comando pagar uma chamada de git, e um clone sem `origin`
    passaria a falhar na montagem em vez de na busca.
    """
    montar_commit_source(
        GitQueGritaSeUsado(),
        referencia=lambda: REFERENCIA_CH,
        config=config,
        estado=_estado(),
        repo="r",
    )


def test_plugin_de_pr_inexistente_nao_derruba_a_montagem():
    fonte = montar_commit_source(
        FakeGit(),
        referencia=lambda: REFERENCIA_CH,
        config=_config_com_host("inexistente"),
        estado=_estado(),
        repo="r",
    )

    with pytest.raises(ErroDeEntrada, match="plugin 'inexistente' nao encontrado") as e:
        fonte.resolve(["123456"])
    # lista os instalados: o Bitbucket vem no pacote.
    assert "bitbucket" in str(e.value)


def test_construtor_do_host_que_levanta_vira_erro_de_entrada():
    host = HostDaConfig(
        _config_com_host("tests.fontes_falsas:HostConstrutorComBug"), lambda: ""
    )

    for _ in range(2):  # a carga que falhou nao fica em cache
        with pytest.raises(ErroDeEntrada, match=r"fonte de PR .* construtor falhou"):
            host.prs_mergeadas(None)


def test_host_recebe_prs_arquivos_e_remote_nomeados():
    remotes: list[int] = []

    def remote_url() -> str:
        remotes.append(1)
        return "git@host:a/b.git"

    host = HostDaConfig(_config_com_host(sistema=7), remote_url)
    host.commits_da_pr(1)
    host.commits_da_pr(2)

    recebido = HostFalso.recebidos[-1]
    assert set(recebido) == {"prs", "arquivos", "remote_url"}
    assert recebido["prs"] == {"fonte": HOST_FALSO, "sistema": 7}
    assert recebido["arquivos"] == ("/a.toml", "/b.toml")
    assert recebido["remote_url"] is remote_url
    assert remotes == [], "a URL e do host, que a le quando precisar"


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
        git,
        referencia=lambda: REFERENCIA_CH,
        config=ConfigProjeto(),
        versionamento=versionamento,
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


FONTE_FIXA = "tests.fontes_falsas:FonteFixa"


def _config_com_fonte(valor: str, **tarefas: object) -> ConfigProjeto:
    return ConfigProjeto(
        tarefas={"fonte": valor, **tarefas},
        arquivos=("/a.toml", "/b.toml"),
        fonte_tarefas=Escolhido(valor, "/a.toml"),
    )


def test_task_source_da_config_nao_carrega_o_plugin_na_montagem():
    # montar nao e usar: `reconstruir-estado` recebe esta fonte e nunca a chama.
    fonte = montar_task_source(_config_com_fonte("inexistente"))

    assert isinstance(fonte, FonteDaConfig)


def test_task_source_da_config_busca_pelo_plugin():
    fonte = montar_task_source(_config_com_fonte(FONTE_FIXA, chamados=["101"]))

    assert fonte.fetch("1.0.0") == ["101"]


def test_plugin_declarado_na_secao_do_repo_carrega(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    central = tmp_path / "xdg" / "monitor-versoes" / "config.toml"
    central.parent.mkdir(parents=True)
    central.write_text(
        secao_repo(
            "x",
            tmp_path,
            f'[tarefas]\nfonte = "{FONTE_FIXA}"\nchamados = ["101"]\n',
        )
    )

    fonte = instanciar_fonte_tarefas(carregar_config_repo("x"))

    assert isinstance(fonte, FonteFixa)
    assert fonte.fetch("1.0.0") == ["101"]


def test_plugin_recebe_tarefas_e_arquivos_nomeados():
    fonte = montar_task_source(_config_com_fonte(FONTE_FIXA, sistema=7))
    fonte.fetch("1.0.0")

    recebido = FonteFixa.recebidos[-1]
    assert set(recebido) == {"tarefas", "arquivos"}
    assert recebido["arquivos"] == ("/a.toml", "/b.toml")
    tarefas = recebido["tarefas"]
    assert isinstance(tarefas, dict)
    assert tarefas["fonte"] == FONTE_FIXA
    assert tarefas["sistema"] == 7


def test_plugin_carregado_uma_vez_por_invocacao():
    fonte = FonteDaConfig(_config_com_fonte(FONTE_FIXA))
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


NOME_REPO = "repo"


def _escrever_central(raiz, topo: str = "", do_repo: str = "") -> None:
    central = raiz.parent / "xdg" / "monitor-versoes"
    central.mkdir(parents=True, exist_ok=True)
    (central / "config.toml").write_text(topo + secao_repo(NOME_REPO, raiz, do_repo))


@pytest.fixture
def repo_montavel(monkeypatch, tmp_path):
    """Raiz de repo registrada na config global, com git e estado fakes."""
    raiz = tmp_path / "repo"
    raiz.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _escrever_central(raiz)
    estado = FakeEstado(repos={NOME_REPO: RepoInfo(nome=NOME_REPO)})
    monkeypatch.setattr(montagem, "new_git_subprocess", lambda *_, **__: FakeGit())
    monkeypatch.setattr(montagem, "Estado", lambda sessao: estado)
    return raiz


def _lista(raiz):
    lista = raiz.parent / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")
    return FonteTasks(fonte="manual", lista_manual=str(lista))


def _fonte_central(raiz, valor: str) -> None:
    _escrever_central(raiz, topo=f'[tarefas]\nfonte = "{valor}"\n')


def test_montar_deps_usa_o_caminho_da_secao(repo_montavel, monkeypatch):
    abertos: list[str] = []

    def abrir_git(caminho: str, **_: object) -> FakeGit:
        abertos.append(caminho)
        return FakeGit()

    monkeypatch.setattr(montagem, "new_git_subprocess", abrir_git)
    estado = FakeEstado()
    monkeypatch.setattr(montagem, "Estado", lambda sessao: estado)

    deps = montar_deps(NOME_REPO, None)  # type: ignore[arg-type]

    assert abertos == [str(repo_montavel)]
    assert deps.repo == NOME_REPO
    assert NOME_REPO in [r.nome for r in estado.listar_repos()]


def test_fonte_da_config_sem_padrao_propoe_a_referencia_dela(repo_montavel):
    _fonte_central(repo_montavel, FONTE_FIXA)

    deps = montar_deps(NOME_REPO, None)  # type: ignore[arg-type]

    assert deps.referencia() == REFERENCIA_CH


def test_montar_deps_nao_carrega_o_plugin(repo_montavel):
    _fonte_central(repo_montavel, "inexistente")

    deps = montar_deps(NOME_REPO, None)  # type: ignore[arg-type]

    with pytest.raises(ErroDeEntrada, match="plugin 'inexistente' nao encontrado"):
        deps.referencia()


def test_lista_manual_sem_padrao_monta_e_so_cobra_no_uso(repo_montavel):
    # montar nao pode falhar: `atualizar --abort` nao usa a referencia.
    deps = montar_deps(NOME_REPO, None, tasks=_lista(repo_montavel))  # type: ignore[arg-type]

    with pytest.raises(ErroDeEntrada) as e:
        deps.referencia()
    # O texto é requisito: diz a chave que falta.
    assert "[referencia] padrao" in str(e.value)


def test_lista_manual_com_padrao_usa_o_alfabeto_default(repo_montavel):
    _escrever_central(repo_montavel, do_repo='[referencia]\npadrao = "ch{id}"\n')

    deps = montar_deps(NOME_REPO, None, tasks=_lista(repo_montavel))  # type: ignore[arg-type]

    assert deps.referencia() == Referencia("ch{id}", ALFABETO_PADRAO)


def _entradas(raiz, **kwargs) -> str:
    return montar_deps(NOME_REPO, None, **kwargs).identidade_das_entradas()  # type: ignore[arg-type]


def test_identidade_muda_com_a_fonte(repo_montavel):
    _fonte_central(repo_montavel, FONTE_FIXA)
    antes = _entradas(repo_montavel)
    _fonte_central(repo_montavel, "tests.fontes_falsas:FonteComCredencial")

    assert _entradas(repo_montavel) != antes


def test_entradas_mudam_com_a_fonte_de_tasks(repo_montavel):
    assert _entradas(repo_montavel) != _entradas(
        repo_montavel, tasks=_lista(repo_montavel)
    )


def test_entradas_mudam_com_o_conteudo_da_lista(repo_montavel):
    fonte = _lista(repo_montavel)
    antes = _entradas(repo_montavel, tasks=fonte)
    with open(fonte.lista_manual, "a", encoding="utf-8") as f:
        f.write("654321\n")

    assert _entradas(repo_montavel, tasks=fonte) != antes


def test_trocar_fonte_de_pr_invalida_o_carimbo(repo_montavel):
    antes = _entradas(repo_montavel)
    _escrever_central(repo_montavel, topo=f'[prs]\nfonte = "{HOST_FALSO}"\n')
    com_pr = _entradas(repo_montavel)
    _escrever_central(repo_montavel, topo=f'[prs]\nfonte = "{HOST_SEM_VERIFICACAO}"\n')

    assert len({antes, com_pr, _entradas(repo_montavel)}) == 3


def test_entradas_mudam_com_o_resto_de_prs(repo_montavel):
    _escrever_central(repo_montavel, topo=f'[prs]\nfonte = "{HOST_FALSO}"\nx = 1\n')
    antes = _entradas(repo_montavel)
    _escrever_central(repo_montavel, topo=f'[prs]\nfonte = "{HOST_FALSO}"\nx = 2\n')

    assert _entradas(repo_montavel) != antes


def test_fonte_definida_sem_credencial_so_falha_na_busca(repo_montavel, monkeypatch):
    """Montar nao e usar: `atualizar --abort` e `reconstruir-estado` montam o
    Deps com `[prs] fonte` definida e nunca buscam commit."""
    monkeypatch.delenv("BITBUCKET_TOKEN", raising=False)
    monkeypatch.delenv("BITBUCKET_EMAIL", raising=False)
    _escrever_central(
        repo_montavel,
        topo=f'[tarefas]\nfonte = "{FONTE_FIXA}"\n[prs]\nfonte = "bitbucket"\n',
    )

    deps = montar_deps(NOME_REPO, None)  # type: ignore[arg-type]

    assert deps.commit_source is not None
    with pytest.raises(ErroDeEntrada, match="sem BITBUCKET_"):
        deps.commit_source.resolve(["123456"])


def test_entradas_mudam_com_a_config_de_referencia_e_piso(repo_montavel):
    antes = _entradas(repo_montavel)
    _escrever_central(repo_montavel, do_repo='[referencia]\npadrao = "ch{id}"\n')

    assert _entradas(repo_montavel) != antes


def test_entradas_mudam_com_o_sistema_de_tarefas(repo_montavel):
    _escrever_central(repo_montavel, do_repo="[tarefas]\nsistema = 7\n")
    antes = _entradas(repo_montavel)
    _escrever_central(repo_montavel, do_repo="[tarefas]\nsistema = 8\n")

    assert _entradas(repo_montavel) != antes


def test_entradas_iguais_para_a_mesma_invocacao(repo_montavel):
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
    from motor.adapters.estado.sqlite import Estado
    from motor.montagem import abrir_sessao

    monkeypatch.delenv("DATABASE_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_SQLITE_PATH", str(tmp_path / "estado.db"))

    with abrir_sessao(garantir=False) as sessao:
        assert Estado(sessao=sessao).revisao_migracao() is None


def test_sem_provedor_de_sugestao_nao_ha_provedor():
    assert instanciar_provedor_sugestao(ConfigProjeto()) is None


def test_provedor_de_sugestao_inexistente_nao_derruba_a_montagem(repo_montavel):
    _escrever_central(repo_montavel, topo='[sugestao]\nprovedor = "inexistente"\n')
    deps = montar_deps(NOME_REPO, None)  # type: ignore[arg-type]
    with pytest.raises(ErroDeEntrada):
        deps.sugestao()


def test_provedor_recebe_sugestao_e_arquivos_nomeados(repo_montavel):
    provedor = "motor.adapters.sugestao.fake:FakeProvedorSugestao"
    _escrever_central(
        repo_montavel, topo=f'[sugestao]\nprovedor = "{provedor}"\nmodelo = "m"\n'
    )
    deps = montar_deps(NOME_REPO, None)  # type: ignore[arg-type]
    instancia = deps.sugestao()
    assert isinstance(instancia, FakeProvedorSugestao)
    assert instancia.sugestao == {"provedor": provedor, "modelo": "m"}
    assert instancia.arquivos == (carregar_config_repo(NOME_REPO).arquivos)
