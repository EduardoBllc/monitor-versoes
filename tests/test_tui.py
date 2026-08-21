import asyncio
import contextlib
import datetime
from pathlib import Path
from typing import cast
from threading import Event

from rich.console import Console
from textual.widgets import Button, Checkbox, Input, OptionList, Select, Static

from motor.adapters.estado.fake import FakeEstado
from motor.ports import GitRepo
from motor.domain.types import CommitRef, RepoInfo, VersionStatus
from motor.engine.atualizar import AtualizarResult, AtualizarStatus
from motor.engine.consultar import ChamadoConsultado
from motor.errors import MotorError
from motor.progresso import Progresso, SlotProgresso
import motor.montagem as montagem
import motor.tui as tui
from motor.tui import (
    MotorTUI,
    PainelProgresso,
    RepoOption,
    VersionOption,
    descobrir_repos,
    descobrir_versoes,
    renderizar_status,
)


def _nunca_executa(repo: RepoOption, versao: str, auditar: bool) -> VersionStatus:
    """Runner de verificacao para teste que nao chega a disparar verificacao.

    Levanta em vez de devolver None: se um dia o fluxo passar por aqui, o teste
    falha dizendo isso, em vez de seguir com um status vazio.
    """
    raise AssertionError("este teste nao deveria executar verificacao")


def _texto(renderable) -> str:
    console = Console(record=True, width=120, color_system=None)
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
            "alpha": RepoInfo(nome="alpha", tickio_sistema_id=1),
            "beta": RepoInfo(nome="beta", tickio_sistema_id=2),
            "gamma": RepoInfo(nome="gamma", tickio_sistema_id=3),
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


def test_repos_do_ambiente_usa_estado_e_projects_dir(tmp_path, monkeypatch):
    estado = FakeEstado(
        repos={"alpha": RepoInfo(nome="alpha", tickio_sistema_id=7)}
    )
    checkout = _checkout(tmp_path, "alpha")
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setattr(tui, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(tui, "PostgresEstado", lambda sessao: estado)

    assert tui._repos_do_ambiente() == [
        RepoOption(nome="alpha", caminho=str(checkout))
    ]


def test_repos_do_ambiente_sem_projects_dir_nao_varre_cwd(tmp_path, monkeypatch):
    estado = FakeEstado(
        repos={"alpha": RepoInfo(nome="alpha", tickio_sistema_id=7)}
    )
    _checkout(tmp_path, "alpha")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROJECTS_DIR", raising=False)
    monkeypatch.setattr(tui, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(tui, "PostgresEstado", lambda sessao: estado)

    assert tui._repos_do_ambiente() == [RepoOption(nome="alpha", caminho=None)]


class GitCatalogoFake:
    def __init__(self):
        self.fetched: list[str] = []

    def fetch(self, remote: str) -> None:
        self.fetched.append(remote)

    def list_version_branches(self) -> list[str]:
        return ["13.9.0", "14.0.0", "13.10.0", "13.9.0"]

    def list_version_tags(self) -> list[str]:
        return ["13.9.0"]


def test_descobrir_versoes_faz_fetch_deduplica_ordena_e_marca_tag():
    git = GitCatalogoFake()

    assert descobrir_versoes(cast(GitRepo, git)) == [
        VersionOption(numero="14.0.0", liberada=False),
        VersionOption(numero="13.10.0", liberada=False),
        VersionOption(numero="13.9.0", liberada=True),
    ]
    assert git.fetched == ["origin"]


def test_versoes_do_repo_abre_git_no_checkout(monkeypatch):
    git = GitCatalogoFake()
    caminhos: list[str] = []

    def abrir_git(caminho: str) -> GitCatalogoFake:
        caminhos.append(caminho)
        return git

    monkeypatch.setattr(tui, "new_git_subprocess", abrir_git)

    resultado = tui._versoes_do_repo(
        RepoOption(nome="alpha", caminho="/projetos/alpha")
    )

    assert caminhos == ["/projetos/alpha"]
    assert resultado[0] == VersionOption(numero="14.0.0", liberada=False)


def test_verificar_repo_monta_deps_canonica_e_propaga_auditoria(
    tmp_path, monkeypatch
):
    checkout = _checkout(tmp_path, "alpha")
    estado = FakeEstado(
        repos={"alpha": RepoInfo(nome="alpha", tickio_sistema_id=7)}
    )
    capturado: dict[str, object] = {}

    class TickioSpy:
        def __init__(self, base_url, usuario, senha, sistema_id):
            self.sistema_id = sistema_id

    def verificar_spy(deps, versao, auditar=False):
        # a TUI nao tem flag de credencial: token e email chegam do ambiente,
        # dentro da fonte de PR que o montar_commit_source encadeia.
        pr = deps.commit_source.sources[0]
        capturado.update(
            repo=deps.repo,
            versao=versao,
            auditar=auditar,
            tickio_sistema_id=deps.tasks.sistema_id,
            bitbucket_token=pr.token,
            bitbucket_email=pr.email,
        )
        return VersionStatus(verde=True, estado_integro=True)

    monkeypatch.setenv("BITBUCKET_TOKEN", "tok-secreto")
    monkeypatch.setenv("BITBUCKET_EMAIL", "dev@example.com")
    monkeypatch.setattr(tui, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(montagem, "PostgresEstado", lambda sessao: estado)
    monkeypatch.setattr(montagem, "new_git_subprocess", lambda caminho: object())
    monkeypatch.setattr(montagem, "TickioRest", TickioSpy)
    monkeypatch.setattr(tui, "verificar", verificar_spy)

    status = tui._verificar_repo(
        RepoOption(nome="alpha", caminho=str(checkout)), "14.0.0", True
    )

    assert capturado == {
        "repo": "alpha",
        "versao": "14.0.0",
        "auditar": True,
        "tickio_sistema_id": 7,
        "bitbucket_token": "tok-secreto",
        "bitbucket_email": "dev@example.com",
    }
    texto = _texto(renderizar_status(status))
    assert "tok-secreto" not in texto
    assert "dev@example.com" not in texto


def test_atualizar_repo_reutiliza_as_bordas_do_repo(tmp_path, monkeypatch):
    checkout = _checkout(tmp_path, "alpha")
    estado = FakeEstado(
        repos={"alpha": RepoInfo(nome="alpha", tickio_sistema_id=7)}
    )
    capturado: dict[str, object] = {}
    esperado = AtualizarResult(status=AtualizarStatus.DONE)

    class TickioSpy:
        def __init__(self, base_url, usuario, senha, sistema_id):
            self.sistema_id = sistema_id

    def atualizar_spy(deps, versao):
        capturado.update(
            repo=deps.repo,
            versao=versao,
            tickio_sistema_id=deps.tasks.sistema_id,
        )
        return esperado

    monkeypatch.setattr(tui, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(montagem, "PostgresEstado", lambda sessao: estado)
    monkeypatch.setattr(montagem, "new_git_subprocess", lambda caminho: object())
    monkeypatch.setattr(montagem, "TickioRest", TickioSpy)
    monkeypatch.setattr(tui, "atualizar", atualizar_spy)

    resultado = tui._atualizar_repo(
        RepoOption(nome="alpha", caminho=str(checkout)), "14.0.0"
    )

    assert resultado is esperado
    assert capturado == {
        "repo": "alpha",
        "versao": "14.0.0",
        "tickio_sistema_id": 7,
    }


def test_renderizar_status_agrupa_pendencias_e_exibe_alertas():
    commit = CommitRef(
        hash_origem="deadbeefcafe",
        chamado="255514",
        msg="Ajusta pagamento\ncorpo",
    )
    outro_commit = CommitRef(
        hash_origem="c0ffee123456",
        chamado="255514",
        msg="Ajusta revisão",
    )
    status = VersionStatus(
        verde=False,
        tasks_novas=["255514"],
        tasks_removidas=["200000"],
        estado_integro=False,
        tasks_ambiguas=["300000"],
        commits_sumidos=["badc0ffee000"],
        faltantes=[commit, outro_commit],
        conflitantes=[commit],
        suspeitos_conteudo=[commit],
        tasks_sem_commits=["400000"],
    )

    texto = _texto(renderizar_status(status))

    for esperado in (
        "Pendências encontradas",
        "Escopo",
        "Git",
        "#255514",
        "deadbeef",
        "c0ffee12",
        "CONFLITANTE",
        "SUSPEITO",
        "300000",
        "400000",
        "badc0ffe",
    ):
        assert esperado in texto
    assert texto.count("#255514") == 1
    assert "REQUER ATENÇÃO" not in texto
    assert "Tasks novas" not in texto
    assert "Tasks removidas" not in texto


def test_renderizar_snapshot_liberado_explica_que_esta_congelado():
    status = VersionStatus(
        verde=True,
        estado_integro=True,
        liberada_em=datetime.datetime(2026, 8, 7, 14, 22),
        chamados=["255514", "256308"],
    )

    texto = _texto(renderizar_status(status))

    assert "SNAPSHOT CONGELADO" in texto
    assert "2026-08-07 14:22" in texto
    assert "255514" in texto and "256308" in texto


def test_renderizar_snapshot_liberado_preserva_saude_nao_verde():
    status = VersionStatus(
        verde=False,
        estado_integro=True,
        liberada_em=datetime.datetime(2026, 8, 7, 14, 22),
    )

    texto = _texto(renderizar_status(status))

    assert "Pendências encontradas" in texto
    assert "SNAPSHOT CONGELADO" in texto
    assert "Chamados:" not in texto


def test_renderizar_auditoria_nomeia_recalculo_sem_alterar_snapshot():
    texto = _texto(
        renderizar_status(VersionStatus(verde=True, estado_integro=True), auditado=True)
    )

    assert "AUDITORIA DA TAG" in texto
    assert "snapshot não alterado" in texto


def test_renderizar_atualizacao_agrupa_commits_aplicados_por_chamado():
    aplicados = [
        CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro"),
        CommitRef(hash_origem="c0ffee123456", chamado="255514", msg="Segundo"),
    ]

    texto = _texto(
        tui.renderizar_atualizacao(
            AtualizarResult(status=AtualizarStatus.DONE, aplicados=aplicados)
        )
    )

    assert "Atualização concluída" in texto
    assert texto.count("#255514") == 1
    assert "deadbeef" in texto and "c0ffee12" in texto


def test_renderizar_atualizacao_bloqueada_orienta_continuacao():
    texto = _texto(
        tui.renderizar_atualizacao(
            AtualizarResult(
                status=AtualizarStatus.BLOCKED,
                blocked_commit="deadbeefcafe",
                arquivos_conflito=["motor/tui.py", "tests/test_tui.py"],
            )
        )
    )

    assert "Atualização bloqueada" in texto
    assert "deadbeef" in texto
    assert "motor/tui.py" in texto and "tests/test_tui.py" in texto
    assert "--continue" in texto


def test_app_seleciona_repo_tag_e_executa_auditoria():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=True)
    chamadas: list[tuple[RepoOption, str, bool]] = []

    def executar(opcao: RepoOption, numero: str, auditar: bool) -> VersionStatus:
        chamadas.append((opcao, numero, auditar))
        return VersionStatus(verde=True, estado_integro=True)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            carregar_repos=lambda: [repo, RepoOption(nome="beta", caminho=None)],
            carregar_versoes=lambda opcao: [versao],
            executar=executar,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            assert app.query_one("#auditar", Checkbox).display
            assert not app.query_one("#auditar", Checkbox).value
            app.query_one("#auditar", Checkbox).value = True
            assert not app.query_one("#verificar", Button).disabled
            await pilot.click("#verificar")
            await app.workers.wait_for_complete()

            assert chamadas == [(repo, "14.0.0", True)]
            assert "VERDE" in _texto(
                app.query_one("#resultado", Static).content
            )

    asyncio.run(executar_fluxo())


def test_app_pula_placeholders_dos_selects():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            carregar_repos=lambda: [repo],
            carregar_versoes=lambda opcao: [versao],
            executar=lambda repo, versao, auditar: VersionStatus(),
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()

            repos = app.query_one("#repo", Select)
            await pilot.click("#repo")
            await pilot.press("home", "enter")
            assert repos.selection == repo

            await app.workers.wait_for_complete()
            versoes = app.query_one("#versao", Select)
            await pilot.click("#versao")
            await pilot.press("home", "enter")
            assert versoes.selection == versao

    asyncio.run(executar_fluxo())


def test_app_consulta_snapshot_ao_selecionar_versao():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    consultas: list[tuple[RepoOption, str]] = []

    def consultar_runner(opcao: RepoOption, numero: str) -> list[ChamadoConsultado]:
        consultas.append((opcao, numero))
        return [
            ChamadoConsultado(
                chamado="255514",
                estado="aplicado",
                commits=[
                    CommitRef(
                        hash_origem="deadbeefcafe",
                        chamado="255514",
                        msg="Título " + "muito longo " * 20 + "\ncorpo oculto",
                    )
                ],
            ),
            ChamadoConsultado(
                chamado="256308",
                estado="pendente",
                commits=[
                    CommitRef(
                        hash_origem="c0ffee123456",
                        chamado="256308",
                        msg="Corrige pedido",
                    )
                ],
            ),
        ]

    async def executar_fluxo() -> None:
        app = MotorTUI(
            carregar_repos=lambda: [repo],
            carregar_versoes=lambda opcao: [versao],
            executar=lambda repo, versao, auditar: VersionStatus(),
            consultar_versao=consultar_runner,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            await app.workers.wait_for_complete()

            assert consultas == [(repo, "14.0.0")]
            assert app.query_one("#consulta-painel").display
            assert not app.query_one("#resultado-scroll").display

            lista = app.query_one("#consulta-chamados", OptionList)
            detalhe = app.query_one("#consulta-detalhe", Static)
            assert lista.option_count == 2
            assert lista.highlighted == 0
            texto = _texto(detalhe.content)
            assert "255514" in texto and "APLICADO" in texto
            assert "deadbeef" in texto and "…" in texto
            assert "256308" not in texto and "corpo oculto" not in texto

            lista.highlighted = 1
            await pilot.pause()
            texto = _texto(detalhe.content)
            assert "256308" in texto and "PENDENTE" in texto
            assert "c0ffee12" in texto and "255514" not in texto

    asyncio.run(executar_fluxo())


def test_app_mantem_verificar_e_atualizar_visiveis_e_atualiza_pendencias():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    commits = [
        CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro"),
        CommitRef(hash_origem="c0ffee123456", chamado="255514", msg="Segundo"),
    ]
    atualizacoes: list[tuple[RepoOption, str]] = []

    def atualizar_runner(opcao: RepoOption, numero: str) -> AtualizarResult:
        atualizacoes.append((opcao, numero))
        return AtualizarResult(status=AtualizarStatus.DONE, aplicados=commits)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            carregar_repos=lambda: [repo],
            carregar_versoes=lambda opcao: [versao],
            executar=lambda repo, versao, auditar: VersionStatus(
                verde=False,
                estado_integro=True,
                faltantes=commits,
            ),
            atualizar_repo=atualizar_runner,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()

            verificar = app.query_one("#verificar", Button)
            atualizar_botao = app.query_one("#atualizar", Button)
            assert not verificar.disabled
            assert atualizar_botao.disabled

            await pilot.click("#verificar")
            await app.workers.wait_for_complete()

            assert not atualizar_botao.disabled
            assert "2" in _texto(atualizar_botao.label)
            assert atualizar_botao.variant == "warning"

            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()

            assert atualizacoes == [(repo, "14.0.0")]
            assert "Atualização concluída" in _texto(
                app.query_one("#resultado", Static).content
            )
            assert atualizar_botao.disabled

    asyncio.run(executar_fluxo())


def test_app_rechecagem_falha_revoga_atualizacao_anterior():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514")
    verificacoes = 0

    def verificar_runner(repo, versao, auditar):
        nonlocal verificacoes
        verificacoes += 1
        if verificacoes == 2:
            raise MotorError("rechecagem falhou")
        return VersionStatus(
            verde=False,
            estado_integro=True,
            faltantes=[commit],
        )

    async def executar_fluxo() -> None:
        app = MotorTUI(
            lambda: [repo],
            lambda opcao: [versao],
            verificar_runner,
            lambda repo, numero: AtualizarResult(status=AtualizarStatus.DONE),
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()

            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            assert not app.query_one("#atualizar", Button).disabled

            await pilot.pause()
            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            assert verificacoes == 2

            assert "rechecagem falhou" in _texto(
                app.query_one("#resultado", Static).content
            )
            assert app.query_one("#atualizar", Button).disabled

    asyncio.run(executar_fluxo())


def test_app_troca_versao_limpa_resultado_anterior():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao_a = VersionOption(numero="14.0.0", liberada=False)
    versao_b = VersionOption(numero="14.0.1", liberada=False)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            carregar_repos=lambda: [repo],
            carregar_versoes=lambda opcao: [versao_a, versao_b],
            executar=lambda repo, versao, auditar: VersionStatus(
                verde=True, estado_integro=True
            ),
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao_a
            await pilot.pause()
            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            assert "VERDE" in _texto(app.query_one("#resultado", Static).content)

            app.query_one("#versao", Select).value = versao_b
            await pilot.pause()

            texto = _texto(app.query_one("#resultado", Static).content)
            assert "VERDE" not in texto
            assert "14.0.1" in texto

    asyncio.run(executar_fluxo())


def test_app_substitui_carregamento_apos_listar_versoes():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            carregar_repos=lambda: [repo],
            carregar_versoes=lambda opcao: [versao],
            executar=lambda repo, versao, auditar: VersionStatus(
                verde=True, estado_integro=True
            ),
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()

            texto = _texto(app.query_one("#resultado", Static).content)
            assert texto.strip() == "Selecione uma versão."

    asyncio.run(executar_fluxo())


def test_app_troca_repo_limpa_erro_anterior():
    repo_a = RepoOption(nome="alpha", caminho="/projetos/alpha")
    repo_b = RepoOption(nome="beta", caminho="/projetos/beta")
    versao = VersionOption(numero="14.0.0", liberada=False)
    liberar_b = Event()

    def carregar_versoes(repo: RepoOption) -> list[VersionOption]:
        if repo == repo_b:
            liberar_b.wait(timeout=2)
        return [versao]

    def falhar(repo, numero, auditar):
        raise MotorError("falha anterior")

    async def executar_fluxo() -> None:
        app = MotorTUI(lambda: [repo_a, repo_b], carregar_versoes, falhar)
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo_a
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            assert "falha anterior" in _texto(
                app.query_one("#resultado", Static).content
            )

            app.query_one("#repo", Select).value = repo_b
            await pilot.pause()

            texto = _texto(app.query_one("#resultado", Static).content)
            assert "falha anterior" not in texto
            assert "Carregando versões de beta" in texto
            liberar_b.set()
            await app.workers.wait_for_complete()

    asyncio.run(executar_fluxo())


def test_app_exibe_motor_error_sem_traceback():
    def falhar():
        raise MotorError("banco inacessível")

    async def executar_fluxo() -> None:
        app = MotorTUI(falhar, lambda repo: [], _nunca_executa)
        async with app.run_test(size=(120, 36)):
            await app.workers.wait_for_complete()
            assert "banco inacessível" in _texto(
                app.query_one("#resultado", Static).content
            )

    asyncio.run(executar_fluxo())


def test_app_esconde_erro_interno_e_registra_traceback(caplog):
    def falhar():
        raise RuntimeError("bug secreto")

    async def executar_fluxo() -> None:
        app = MotorTUI(falhar, lambda repo: [], _nunca_executa)
        async with app.run_test(size=(120, 36)):
            await app.workers.wait_for_complete()
            texto = _texto(app.query_one("#resultado", Static).content)
            assert "Erro interno fatal" in texto
            assert "bug secreto" not in texto

    asyncio.run(executar_fluxo())
    assert "Erro interno fatal na TUI" in caplog.text
    assert "Traceback" in caplog.text


def test_app_exibe_loading_apenas_durante_verificacao():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    iniciou = Event()
    liberar = Event()

    def executar(opcao, numero, auditar):
        iniciou.set()
        liberar.wait(timeout=2)
        return VersionStatus(verde=True, estado_integro=True)

    async def executar_fluxo() -> None:
        app = MotorTUI(lambda: [repo], lambda opcao: [versao], executar)
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            await pilot.click("#verificar")
            assert await asyncio.to_thread(iniciou.wait, 1)

            resultado = app.query_one("#resultado", Static)
            assert resultado.loading
            assert "Verificando alpha 14.0.0" in _texto(resultado.content)

            liberar.set()
            await app.workers.wait_for_complete()
            assert not resultado.loading

    asyncio.run(executar_fluxo())


def test_app_nao_inicia_execucoes_concorrentes():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    iniciou = Event()
    liberar = Event()
    chamadas: list[str] = []

    def executar(opcao, numero, auditar):
        chamadas.append(numero)
        iniciou.set()
        liberar.wait(timeout=2)
        return VersionStatus(verde=True, estado_integro=True)

    async def executar_fluxo() -> None:
        app = MotorTUI(lambda: [repo], lambda opcao: [versao], executar)
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            await pilot.click("#verificar")
            assert await asyncio.to_thread(iniciou.wait, 1)
            assert app.query_one("#verificar", Button).disabled
            await pilot.click("#verificar")
            liberar.set()
            await app.workers.wait_for_complete()

    asyncio.run(executar_fluxo())
    assert chamadas == ["14.0.0"]


def test_app_descarta_versoes_obsoletas_sem_liberar_repo_atual():
    repo_a = RepoOption(nome="alpha", caminho="/projetos/alpha")
    repo_b = RepoOption(nome="beta", caminho="/projetos/beta")
    versao_anterior = VersionOption(numero="12.0.0", liberada=False)
    versao_a = VersionOption(numero="13.0.0", liberada=False)
    versao_b = VersionOption(numero="14.0.0", liberada=False)
    iniciou_a = Event()
    liberar_a = Event()
    iniciou_b = Event()
    liberar_b = Event()
    cargas_b = 0

    def carregar_versoes(repo: RepoOption) -> list[VersionOption]:
        nonlocal cargas_b
        if repo == repo_a:
            iniciou_a.set()
            liberar_a.wait(timeout=2)
            return [versao_a]
        cargas_b += 1
        if cargas_b == 1:
            return [versao_anterior]
        iniciou_b.set()
        liberar_b.wait(timeout=2)
        return [versao_b]

    async def executar_fluxo() -> None:
        app = MotorTUI(
            carregar_repos=lambda: [repo_a, repo_b],
            carregar_versoes=carregar_versoes,
            executar=_nunca_executa,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo_b
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao_anterior
            await pilot.pause()

            app.query_one("#repo", Select).value = repo_a
            await pilot.pause()
            assert await asyncio.to_thread(iniciou_a.wait, 1)
            app.query_one("#repo", Select).value = repo_b
            await pilot.pause()
            assert await asyncio.to_thread(iniciou_b.wait, 1)

            liberar_a.set()
            await pilot.pause()
            versoes = app.query_one("#versao", Select)
            assert versoes.disabled
            assert app.query_one("#repo", Select).disabled

            liberar_b.set()
            await app.workers.wait_for_complete()
            versoes.value = versao_b
            await pilot.pause()
            assert versoes.selection == versao_b

    asyncio.run(executar_fluxo())


def test_app_mantem_repo_sem_checkout_visivel_mas_inexecutavel():
    repo = RepoOption(nome="beta", caminho=None)

    def nao_deve_rodar(*args):
        raise AssertionError("repo indisponivel nao pode chamar uma borda")

    async def executar_fluxo() -> None:
        app = MotorTUI(
            carregar_repos=lambda: [repo],
            carregar_versoes=nao_deve_rodar,
            executar=nao_deve_rodar,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()

            assert app.query_one("#versao", Select).disabled
            assert app.query_one("#verificar", Button).disabled
            assert app.query_one("#atualizar", Button).disabled
            assert "checkout local não encontrado" in _texto(
                app.query_one("#resultado", Static).content
            )

    asyncio.run(executar_fluxo())


def _app_com_consulta(**extra) -> MotorTUI:
    """Base dos testes de modal: repo e versão únicos, lista de chamados visível."""
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = extra.pop("versao", VersionOption(numero="14.0.0", liberada=False))
    return MotorTUI(
        carregar_repos=lambda: [repo],
        carregar_versoes=lambda opcao: [versao],
        **extra,
    )


async def _selecionar(app: MotorTUI, pilot) -> None:
    await app.workers.wait_for_complete()
    repos = app.query_one("#repo", Select)
    repos.value = repos._options[1][1]
    await pilot.pause()
    await app.workers.wait_for_complete()
    versoes = app.query_one("#versao", Select)
    versoes.value = versoes._options[1][1]
    await pilot.pause()
    await app.workers.wait_for_complete()


def test_app_verificar_com_lista_visivel_abre_modal_e_recarrega_chamados():
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")
    consultas = 0

    def consultar_runner(opcao: RepoOption, numero: str) -> list[ChamadoConsultado]:
        nonlocal consultas
        consultas += 1
        return [
            ChamadoConsultado(
                chamado="255514",
                estado="pendente" if consultas == 1 else "aplicado",
                commits=[commit],
            )
        ]

    async def executar_fluxo() -> None:
        app = _app_com_consulta(
            executar=lambda repo, versao, auditar: VersionStatus(
                verde=False, estado_integro=True, faltantes=[commit]
            ),
            consultar_versao=consultar_runner,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar(app, pilot)
            assert consultas == 1

            base = app.screen_stack[0]
            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert isinstance(app.screen, tui.ResultadoModal)
            assert base.query_one("#consulta-painel").display
            assert not base.query_one("#resultado-scroll").display
            assert "FALTANTE" in _texto(
                app.screen.query_one("#modal-conteudo", Static).content
            )

            await pilot.press("escape")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert not isinstance(app.screen, tui.ResultadoModal)
            assert consultas == 2
            assert "APLICADO" in _texto(
                app.query_one("#consulta-detalhe", Static).content
            )

    asyncio.run(executar_fluxo())


def test_app_auditoria_nao_recarrega_lista_de_chamados():
    consultas = 0

    def consultar_runner(opcao: RepoOption, numero: str) -> list[ChamadoConsultado]:
        nonlocal consultas
        consultas += 1
        return [ChamadoConsultado(chamado="255514", estado="aplicado", commits=[])]

    async def executar_fluxo() -> None:
        app = _app_com_consulta(
            versao=VersionOption(numero="14.0.0", liberada=True),
            executar=lambda repo, versao, auditar: VersionStatus(
                verde=True, estado_integro=True
            ),
            consultar_versao=consultar_runner,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar(app, pilot)
            app.query_one("#auditar", Checkbox).value = True
            await pilot.pause()

            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "AUDITORIA DA TAG" in _texto(
                app.screen.query_one("#modal-conteudo", Static).content
            )

            await pilot.press("escape")
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert consultas == 1

    asyncio.run(executar_fluxo())


def test_app_falha_ao_verificar_preserva_lista_de_chamados():
    consultas = 0

    def consultar_runner(opcao: RepoOption, numero: str) -> list[ChamadoConsultado]:
        nonlocal consultas
        consultas += 1
        return [ChamadoConsultado(chamado="255514", estado="pendente", commits=[])]

    def falhar(repo, numero, auditar):
        raise MotorError("verificação falhou")

    async def executar_fluxo() -> None:
        app = _app_com_consulta(executar=falhar, consultar_versao=consultar_runner)
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar(app, pilot)

            base = app.screen_stack[0]
            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert "verificação falhou" in _texto(
                app.screen.query_one("#modal-conteudo", Static).content
            )
            assert base.query_one("#consulta-painel").display

            await pilot.press("escape")
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert consultas == 1

    asyncio.run(executar_fluxo())


def test_app_atualizar_com_lista_visivel_recarrega_chamados():
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")
    consultas = 0

    def consultar_runner(opcao: RepoOption, numero: str) -> list[ChamadoConsultado]:
        nonlocal consultas
        consultas += 1
        return [
            ChamadoConsultado(chamado="255514", estado="pendente", commits=[commit])
        ]

    async def executar_fluxo() -> None:
        app = _app_com_consulta(
            executar=lambda repo, versao, auditar: VersionStatus(
                verde=False, estado_integro=True, faltantes=[commit]
            ),
            atualizar_repo=lambda repo, numero: AtualizarResult(
                status=AtualizarStatus.DONE, aplicados=[commit]
            ),
            consultar_versao=consultar_runner,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar(app, pilot)

            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert consultas == 2

            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "Atualização concluída" in _texto(
                app.screen.query_one("#modal-conteudo", Static).content
            )

            await pilot.press("escape")
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert consultas == 3

    asyncio.run(executar_fluxo())


def test_app_exibe_loading_na_lista_durante_verificacao():
    iniciou = Event()
    liberar = Event()

    def executar(opcao, numero, auditar):
        iniciou.set()
        liberar.wait(timeout=2)
        return VersionStatus(verde=True, estado_integro=True)

    async def executar_fluxo() -> None:
        app = _app_com_consulta(
            executar=executar,
            consultar_versao=lambda opcao, numero: [
                ChamadoConsultado(chamado="255514", estado="pendente", commits=[])
            ],
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar(app, pilot)

            painel = app.query_one("#consulta-painel")
            await pilot.click("#verificar")
            assert await asyncio.to_thread(iniciou.wait, 1)
            await pilot.pause()

            assert painel.display
            assert painel.loading

            liberar.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not painel.loading

    asyncio.run(executar_fluxo())


def _app_de_cadastro(registrar, repos: list[str]) -> MotorTUI:
    """Base dos testes de cadastro: a lista de repos sai de `repos`, que o
    registrador de cada teste alimenta, para provar o recarregamento."""
    return MotorTUI(
        carregar_repos=lambda: [
            RepoOption(nome=nome, caminho=f"/projetos/{nome}") for nome in repos
        ],
        carregar_versoes=lambda opcao: [],
        executar=_nunca_executa,
        registrar_repo=registrar,
    )


async def _preencher_cadastro(app: MotorTUI, pilot, nome: str, sistema: str) -> None:
    await pilot.press("n")
    await pilot.pause()
    app.screen.query_one("#cadastro-nome", Input).value = nome
    app.screen.query_one("#cadastro-sistema", Input).value = sistema
    await pilot.pause()
    await pilot.click("#cadastro-salvar")
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def test_app_cadastra_repo_e_recarrega_lista():
    repos = ["alpha"]
    chamadas: list[tuple[str, int]] = []

    def registrar(nome: str, sistema_id: int) -> None:
        chamadas.append((nome, sistema_id))
        repos.append(nome)

    async def executar_fluxo() -> None:
        app = _app_de_cadastro(registrar, repos)
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            await _preencher_cadastro(app, pilot, "delta", "7")

            assert chamadas == [("delta", 7)]
            assert not isinstance(app.screen, tui.CadastroModal)
            nomes = [
                opcao.nome
                for _, opcao in app.query_one("#repo", Select)._options[1:]
                if isinstance(opcao, RepoOption)
            ]
            assert nomes == ["alpha", "delta"]
            assert "delta" in _texto(app.query_one("#resultado", Static).content)

    asyncio.run(executar_fluxo())


def test_app_cadastro_recusa_sistema_id_nao_numerico_e_mantem_modal():
    def registrar(nome: str, sistema_id: int) -> None:
        raise AssertionError("id invalido nao pode chegar ao registrador")

    async def executar_fluxo() -> None:
        app = _app_de_cadastro(registrar, ["alpha"])
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            await _preencher_cadastro(app, pilot, "delta", "abc")

            assert isinstance(app.screen, tui.CadastroModal)
            assert "inteiro positivo" in _texto(
                app.screen.query_one("#cadastro-erro", Static).content
            )

    asyncio.run(executar_fluxo())


def test_app_cadastro_recusa_nome_com_caminho_e_mantem_modal():
    def registrar(nome: str, sistema_id: int) -> None:
        raise AssertionError("nome invalido nao pode chegar ao registrador")

    async def executar_fluxo() -> None:
        app = _app_de_cadastro(registrar, ["alpha"])
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            await _preencher_cadastro(app, pilot, "sub/delta", "7")

            assert isinstance(app.screen, tui.CadastroModal)
            assert "sem caminho" in _texto(
                app.screen.query_one("#cadastro-erro", Static).content
            )

    asyncio.run(executar_fluxo())


def test_app_cadastro_de_repo_duplicado_mostra_erro_no_painel():
    def registrar(nome: str, sistema_id: int) -> None:
        raise MotorError(f"repo '{nome}' ja cadastrado")

    async def executar_fluxo() -> None:
        app = _app_de_cadastro(registrar, ["alpha"])
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            await _preencher_cadastro(app, pilot, "alpha", "1")

            assert not isinstance(app.screen, tui.CadastroModal)
            assert "ja cadastrado" in _texto(
                app.query_one("#resultado", Static).content
            )

    asyncio.run(executar_fluxo())


def test_app_sem_registrador_ignora_a_tecla_de_cadastro():
    async def executar_fluxo() -> None:
        app = MotorTUI(
            carregar_repos=lambda: [RepoOption(nome="alpha", caminho="/p/alpha")],
            carregar_versoes=lambda opcao: [],
            executar=_nunca_executa,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("n")
            await pilot.pause()

            assert not isinstance(app.screen, tui.CadastroModal)

    asyncio.run(executar_fluxo())


def test_app_cadastro_digita_a_propria_tecla_de_atalho_no_campo():
    """A tecla que abre o modal e uma letra: dentro dele ela tem de ser texto."""

    async def executar_fluxo() -> None:
        app = _app_de_cadastro(lambda nome, sistema_id: None, ["alpha"])
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("n")
            await pilot.pause()
            await pilot.press("n", "u", "v", "e", "m")
            await pilot.pause()

            assert isinstance(app.screen, tui.CadastroModal)
            assert len(app.screen_stack) == 2
            assert app.screen.query_one("#cadastro-nome", Input).value == "nuvem"

    asyncio.run(executar_fluxo())


def test_app_desenha_a_fase_e_a_contagem_do_motor_no_lugar_do_spinner():
    """O spinner generico nao diz nada num verificar de 40s. O painel que cobre
    o resultado passa a mostrar a fase do motor e, quando ela e contavel, a
    barra de verdade.
    """
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    slot = SlotProgresso()
    liberar = Event()

    def executar(opcao: RepoOption, numero: str, auditar: bool) -> VersionStatus:
        slot.relatar(Progresso("presença dos commits", 3, 8))
        liberar.wait(5)
        return VersionStatus(verde=True, estado_integro=True)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            carregar_repos=lambda: [repo],
            carregar_versoes=lambda opcao: [versao],
            executar=executar,
            slot=slot,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            await pilot.click("#verificar")
            for _ in range(50):
                if slot.ultimo is not None:
                    break
                await pilot.pause()
            # chama o pintor direto em vez de esperar o set_interval: prender o
            # teste no relogio de 10 Hz o deixaria intermitente sem provar nada.
            app._pintar_progresso()
            await pilot.pause()

            # O painel de loading e um "cover widget": o Textual o pendura fora
            # da arvore de nos, entao query_one a partir do app nao o acha.
            painel = app._painel_progresso
            assert isinstance(painel, PainelProgresso)
            assert painel.progresso == Progresso("presença dos commits", 3, 8)
            # e chegou na tela, nao so no atributo
            assert "presença dos commits" in _texto(painel.content)
            assert "3/8" in _texto(painel.content)

            liberar.set()
            await app.workers.wait_for_complete()

    asyncio.run(executar_fluxo())


def test_app_volta_para_o_indeterminado_em_fase_sem_contagem():
    """Fase de I/O (fetch, push) nao sabe quanto falta: barra parada em 0% mente,
    barra indeterminada nao.
    """
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    slot = SlotProgresso()
    liberar = Event()

    def executar(opcao: RepoOption, numero: str, auditar: bool) -> VersionStatus:
        slot.relatar(Progresso("presença dos commits", 3, 8))
        liberar.wait(5)
        slot.relatar(Progresso("gravando estado"))
        return VersionStatus(verde=True, estado_integro=True)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            carregar_repos=lambda: [repo],
            carregar_versoes=lambda opcao: [versao],
            executar=executar,
            slot=slot,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            await pilot.click("#verificar")
            for _ in range(50):
                if slot.ultimo is not None:
                    break
                await pilot.pause()
            app._pintar_progresso()
            await pilot.pause()

            slot.relatar(Progresso("gravando estado"))
            app._pintar_progresso()
            await pilot.pause()

            painel = app._painel_progresso
            assert painel is not None
            assert painel.progresso == Progresso("gravando estado")
            # sem contagem na tela: a barra virou pulso
            assert "3/8" not in _texto(painel.content)

            liberar.set()
            await app.workers.wait_for_complete()

    asyncio.run(executar_fluxo())


def test_descobrir_versoes_relata_o_fetch():
    """O `fetch` da lista de versoes e a primeira espera longa da TUI: sem
    relato, trocar de repo parece travamento.
    """
    relatos: list[Progresso] = []

    descobrir_versoes(cast(GitRepo, GitCatalogoFake()), progresso=relatos.append)

    assert [p.fase for p in relatos] == ["buscando refs do origin"]
