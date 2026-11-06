import contextlib
import io
from functools import partial
from pathlib import Path
from typing import cast

import pytest
from rich.console import Console

import motor.montagem as montagem
import motor.operacoes as operacoes
from motor.adapters.estado.fake import FakeEstado
from motor.domain.types import RepoInfo, VersionStatus
from motor.engine.atualizar import AtualizarResult, AtualizarStatus
from motor.errors import NaoEncontrado
from motor.operacoes import (
    RepoOption,
    VersionOption,
    descobrir_repos,
    descobrir_versoes,
)
from motor.ports import GitRepo
from motor.progresso import Progresso, SlotProgresso
from motor.services.versionamento import versionamento_padrao
from motor.tui import renderizar_status
from tests.fontes_falsas import FonteFixa


def _texto(renderable) -> str:
    console = Console(file=io.StringIO(), record=True, width=120, color_system=None)
    console.print(renderable)
    return console.export_text()


def _checkout(raiz: Path, nome: str) -> Path:
    caminho = raiz / nome
    caminho.mkdir()
    (caminho / ".git").touch()
    return caminho


def _estado() -> FakeEstado:
    return FakeEstado(
        repos={
            "alpha": RepoInfo(nome="alpha"),
            "beta": RepoInfo(nome="beta"),
            "gamma": RepoInfo(nome="gamma"),
        },
        aliases={"beta-local": "beta"},
    )


def test_descobrir_repos_prefere_canonico_depois_alias_e_mantem_ausente(tmp_path):
    alpha = _checkout(tmp_path, "alpha")
    _checkout(tmp_path, "beta-local")
    beta = _checkout(tmp_path, "beta")
    _checkout(tmp_path, "nao-cadastrado")

    assert descobrir_repos(_estado(), str(tmp_path)) == [
        RepoOption(nome="alpha", caminho=str(alpha)),
        RepoOption(nome="beta", caminho=str(beta)),
        RepoOption(nome="gamma", caminho=None),
    ]


def test_descobrir_repos_usa_alias_quando_canonico_nao_existe(tmp_path):
    alias = _checkout(tmp_path, "beta-local")

    opcoes = descobrir_repos(_estado(), str(tmp_path))

    assert opcoes[1] == RepoOption(nome="beta", caminho=str(alias))


def test_descobrir_repos_sem_projects_dir_desabilita_todos(tmp_path):
    opcoes = descobrir_repos(_estado(), str(tmp_path / "ausente"))

    assert [opcao.caminho for opcao in opcoes] == [None, None, None]


def test_descobrir_repos_ignora_naoencontrado_mesmo_sem_a_palavra_desconhecido(
    tmp_path,
):
    """Ramifica por TIPO (NaoEncontrado), nao por substring 'desconhecido' na
    mensagem: um adapter de terceiro correto, que levanta NaoEncontrado num
    idioma diferente, nao pode reprovar aqui.
    """

    class EstadoQueFalaIngles(FakeEstado):
        def resolver_repo(self, basename: str, /) -> RepoInfo:
            raise NaoEncontrado("unknown repo")

    _checkout(tmp_path, "nao-cadastrado")
    estado = EstadoQueFalaIngles(repos={"alpha": RepoInfo(nome="alpha")})

    opcoes = descobrir_repos(estado, str(tmp_path))

    assert opcoes == [RepoOption(nome="alpha", caminho=None)]


def test_descobrir_repos_relata_o_banco_e_a_varredura(tmp_path):
    """Era o unico worker sem fase nenhuma: a tela ficava parada enquanto o
    banco abria e o PROJECTS_DIR era varrido (um resolver_repo por diretorio
    desconhecido).
    """
    _checkout(tmp_path, "alpha")
    _checkout(tmp_path, "nao-cadastrado")
    relatos: list[Progresso] = []

    descobrir_repos(_estado(), str(tmp_path), progresso=relatos.append)

    assert relatos[0] == Progresso("lendo os repos cadastrados")
    assert relatos[1:] == [
        Progresso("procurando os checkouts", 1, 2),
        Progresso("procurando os checkouts", 2, 2),
    ]


def test_repos_do_ambiente_usa_estado_e_projects_dir(tmp_path, monkeypatch):
    estado = FakeEstado(repos={"alpha": RepoInfo(nome="alpha")})
    checkout = _checkout(tmp_path, "alpha")
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setattr(operacoes, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(operacoes, "PostgresEstado", lambda sessao: estado)

    assert operacoes.repos_do_ambiente() == [
        RepoOption(nome="alpha", caminho=str(checkout))
    ]


def test_repos_do_ambiente_sem_projects_dir_nao_varre_cwd(tmp_path, monkeypatch):
    estado = FakeEstado(repos={"alpha": RepoInfo(nome="alpha")})
    _checkout(tmp_path, "alpha")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROJECTS_DIR", raising=False)
    monkeypatch.setattr(operacoes, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(operacoes, "PostgresEstado", lambda sessao: estado)

    assert operacoes.repos_do_ambiente() == [RepoOption(nome="alpha", caminho=None)]


class GitCatalogoFake:
    def __init__(self):
        self.fetched: list[str] = []

    def fetch(self, remote: str) -> None:
        self.fetched.append(remote)

    def listar_branches(self) -> list[str]:
        return ["13.10.0", "13.9.0", "14.0.0", "main"]

    def listar_tags(self) -> list[str]:
        return ["13.8.0", "13.9.0", "v1"]


def test_descobrir_versoes_faz_fetch_deduplica_ordena_e_marca_liberada():
    git = GitCatalogoFake()

    assert descobrir_versoes(cast(GitRepo, git), versionamento_padrao()) == [
        VersionOption(numero="14.0.0", liberada=False),
        VersionOption(numero="13.10.0", liberada=False),
        VersionOption(numero="13.9.0", liberada=True),
        VersionOption(numero="13.8.0", liberada=True),
    ]
    assert git.fetched == ["origin"]


def test_versoes_do_repo_abre_git_no_checkout(monkeypatch):
    git = GitCatalogoFake()
    caminhos: list[str] = []

    def abrir_git(caminho: str, **_: object) -> GitCatalogoFake:
        caminhos.append(caminho)
        return git

    monkeypatch.setattr(operacoes, "new_git_subprocess", abrir_git)

    resultado = operacoes.versoes_do_repo(
        RepoOption(nome="alpha", caminho="/projetos/alpha")
    )

    assert caminhos == ["/projetos/alpha"]
    assert resultado[0] == VersionOption(numero="14.0.0", liberada=False)


_FIXA = "tests.fontes_falsas:FonteFixa"


def _sistema_recebido(deps) -> object:
    """O `[tarefas] sistema` que a fonte da config recebeu ao ser carregada."""
    deps.tasks.carregar()
    return FonteFixa.recebidos[-1]["tarefas"]["sistema"]  # type: ignore[index]


def test_verificar_repo_monta_deps_canonica_e_propaga_auditoria(
    tmp_path, monkeypatch, xdg_isolado
):
    checkout = _checkout(tmp_path, "alpha")
    (checkout / ".monitor-versoes.toml").write_text("[tarefas]\nsistema = 7\n")
    estado = FakeEstado(repos={"alpha": RepoInfo(nome="alpha")})
    capturado: dict[str, object] = {}
    xdg_isolado.write_text(f'[tarefas]\nfonte = "{_FIXA}"\n')
    monkeypatch.setattr(FonteFixa, "recebidos", [])

    def verificar_spy(deps, versao, auditar=False):
        # a TUI nao tem flag de credencial: token e email chegam do ambiente,
        # dentro da fonte de PR que o montar_commit_source encadeia.
        pr = deps.commit_source.sources[0]
        capturado.update(
            repo=deps.repo,
            versao=versao,
            auditar=auditar,
            sistema=_sistema_recebido(deps),
            bitbucket_token=pr.token,
            bitbucket_email=pr.email,
        )
        return VersionStatus(verde=True, estado_integro=True)

    monkeypatch.setenv("BITBUCKET_TOKEN", "tok-secreto")
    monkeypatch.setenv("BITBUCKET_EMAIL", "dev@example.com")
    monkeypatch.setattr(operacoes, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(montagem, "PostgresEstado", lambda sessao: estado)
    monkeypatch.setattr(montagem, "new_git_subprocess", lambda caminho, **_: object())
    monkeypatch.setattr(operacoes, "verificar", verificar_spy)

    status = operacoes.verificar_repo(
        RepoOption(nome="alpha", caminho=str(checkout)), "14.0.0", True
    )

    assert capturado == {
        "repo": "alpha",
        "versao": "14.0.0",
        "auditar": True,
        "sistema": 7,
        "bitbucket_token": "tok-secreto",
        "bitbucket_email": "dev@example.com",
    }
    texto = _texto(renderizar_status(status))
    assert "tok-secreto" not in texto
    assert "dev@example.com" not in texto


def test_atualizar_repo_reutiliza_as_bordas_do_repo(tmp_path, monkeypatch, xdg_isolado):
    checkout = _checkout(tmp_path, "alpha")
    (checkout / ".monitor-versoes.toml").write_text("[tarefas]\nsistema = 7\n")
    estado = FakeEstado(repos={"alpha": RepoInfo(nome="alpha")})
    capturado: dict[str, object] = {}
    esperado = AtualizarResult(status=AtualizarStatus.DONE)
    xdg_isolado.write_text(f'[tarefas]\nfonte = "{_FIXA}"\n')
    monkeypatch.setattr(FonteFixa, "recebidos", [])

    def atualizar_spy(deps, versao):
        capturado.update(
            repo=deps.repo,
            versao=versao,
            sistema=_sistema_recebido(deps),
        )
        return esperado

    monkeypatch.setattr(operacoes, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(montagem, "PostgresEstado", lambda sessao: estado)
    monkeypatch.setattr(montagem, "new_git_subprocess", lambda caminho, **_: object())
    monkeypatch.setattr(operacoes, "atualizar", atualizar_spy)

    resultado = operacoes.atualizar_repo(
        RepoOption(nome="alpha", caminho=str(checkout)), "14.0.0"
    )

    assert resultado is esperado
    assert capturado == {
        "repo": "alpha",
        "versao": "14.0.0",
        "sistema": 7,
    }


def test_continuar_repo_chama_o_atualizar_continue(tmp_path, monkeypatch, xdg_isolado):
    checkout = _checkout(tmp_path, "alpha")
    estado = FakeEstado(repos={"alpha": RepoInfo(nome="alpha")})
    capturado: dict[str, object] = {}
    esperado = AtualizarResult(status=AtualizarStatus.DONE)

    def continue_spy(deps, versao, *, allow_empty=False):
        capturado.update(repo=deps.repo, versao=versao, allow_empty=allow_empty)
        return esperado

    monkeypatch.setattr(operacoes, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(montagem, "PostgresEstado", lambda sessao: estado)
    monkeypatch.setattr(montagem, "new_git_subprocess", lambda caminho, **_: object())
    xdg_isolado.write_text(f'[tarefas]\nfonte = "{_FIXA}"\n')
    monkeypatch.setattr(operacoes, "atualizar_continue", continue_spy)

    resultado = operacoes.continuar_repo(
        RepoOption(nome="alpha", caminho=str(checkout)), "14.0.0", allow_empty=True
    )

    assert resultado is esperado
    assert capturado == {"repo": "alpha", "versao": "14.0.0", "allow_empty": True}, (
        "o allow_empty do botao 'Registrar vazio' tem de chegar ao engine"
    )


def test_abortar_repo_chama_o_atualizar_abort(tmp_path, monkeypatch, xdg_isolado):
    checkout = _checkout(tmp_path, "alpha")
    estado = FakeEstado(repos={"alpha": RepoInfo(nome="alpha")})
    capturado: dict[str, object] = {}

    def abort_spy(deps, versao):
        capturado.update(repo=deps.repo, versao=versao)

    monkeypatch.setattr(operacoes, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(montagem, "PostgresEstado", lambda sessao: estado)
    monkeypatch.setattr(montagem, "new_git_subprocess", lambda caminho, **_: object())
    xdg_isolado.write_text(f'[tarefas]\nfonte = "{_FIXA}"\n')
    monkeypatch.setattr(operacoes, "atualizar_abort", abort_spy)

    operacoes.abortar_repo(RepoOption(nome="alpha", caminho=str(checkout)), "14.0.0")

    assert capturado == {"repo": "alpha", "versao": "14.0.0"}


def test_descobrir_versoes_relata_o_fetch():
    """O `fetch` da lista de versoes e a primeira espera longa da TUI: sem
    relato, trocar de repo parece travamento.
    """
    relatos: list[Progresso] = []

    descobrir_versoes(
        cast(GitRepo, GitCatalogoFake()),
        versionamento_padrao(),
        progresso=relatos.append,
    )

    assert [p.fase for p in relatos] == ["buscando refs do origin"]


@pytest.fixture
def xdg_isolado(tmp_path, monkeypatch):
    """Config global isolada; devolve o caminho do config.toml central."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    caminho = tmp_path / "xdg" / "monitor-versoes" / "config.toml"
    caminho.parent.mkdir(parents=True)
    return caminho


def test_descobrir_repos_le_o_piso_do_toml_do_checkout(tmp_path, xdg_isolado):
    checkout = tmp_path / "projetos" / "alpha"
    (checkout / ".git").mkdir(parents=True)
    (checkout / ".monitor-versoes.toml").write_text('[versao]\npiso = "14.0.0"\n')
    estado = FakeEstado(repos={"alpha": RepoInfo(nome="alpha")})

    opcoes = descobrir_repos(estado, str(tmp_path / "projetos"))

    assert [o.piso_versao for o in opcoes] == ["14.0.0"]


def test_descobrir_repos_sem_checkout_usa_so_o_piso_global(tmp_path, xdg_isolado):
    xdg_isolado.write_text('[versao]\npiso = "12.0.0"\n')
    estado = FakeEstado(repos={"alpha": RepoInfo(nome="alpha")})

    assert [o.piso_versao for o in descobrir_repos(estado, "")] == ["12.0.0"]
    assert [o.piso_versao for o in descobrir_repos(estado, str(tmp_path / "x"))] == [
        "12.0.0"
    ]


def test_descobrir_repos_toml_invalido_deixa_o_piso_none_sem_derrubar(
    tmp_path, xdg_isolado
):
    for nome, conteudo in (
        ("alpha", "isto = = nao\n"),
        ("beta", '[versao]\npiso = "1.0.0"\n'),
    ):
        checkout = tmp_path / "projetos" / nome
        (checkout / ".git").mkdir(parents=True)
        (checkout / ".monitor-versoes.toml").write_text(conteudo)
    estado = FakeEstado(
        repos={"alpha": RepoInfo(nome="alpha"), "beta": RepoInfo(nome="beta")}
    )

    opcoes = descobrir_repos(estado, str(tmp_path / "projetos"))

    assert {o.nome: o.piso_versao for o in opcoes} == {"alpha": None, "beta": "1.0.0"}


def test_runners_com_progresso_liga_cada_runner_ao_relator():
    relatar = SlotProgresso().relatar

    r = operacoes.runners_com_progresso(relatar)

    assert r.registrar_repo is operacoes.registrar_no_banco
    ligados = [
        (r.carregar_repos, operacoes.repos_do_ambiente),
        (r.carregar_versoes, operacoes.versoes_do_repo),
        (r.executar, operacoes.verificar_repo),
        (r.atualizar_repo, operacoes.atualizar_repo),
        (r.continuar_repo, operacoes.continuar_repo),
        (r.abortar_repo, operacoes.abortar_repo),
        (r.consultar_versao, operacoes.consultar_repo),
        (r.criar_repo, operacoes.criar_repo),
        (r.previa_atualizacao, operacoes.previa_repo),
    ]
    for runner, alvo in ligados:
        assert isinstance(runner, partial) and runner.func is alvo
        assert runner.keywords == {"progresso": relatar}
