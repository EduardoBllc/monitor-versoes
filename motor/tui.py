from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Checkbox, Footer, Header, Select, Static

from motor.__main__ import _agrupar_por_task
from motor.domain.types import VersionStatus
from motor.errors import MotorError
from motor.ports import EstadoRepo, GitRepo


@dataclass(frozen=True)
class RepoOption:
    nome: str
    caminho: str | None

    @property
    def disponivel(self) -> bool:
        return self.caminho is not None


@dataclass(frozen=True)
class VersionOption:
    numero: str
    liberada: bool


RepoLoader = Callable[[], list[RepoOption]]
VersionLoader = Callable[[RepoOption], list[VersionOption]]
VerifyRunner = Callable[[RepoOption, str, bool], VersionStatus]


class MotorTUI(App[None]):
    BINDINGS = [("q", "quit", "Sair")]
    CSS = """
    #barra { height: auto; padding: 1; }
    #repo, #versao { width: 1fr; }
    #acao { width: 18; padding: 1 2; border: round $panel; }
    #auditar { display: none; height: auto; margin: 0 1; }
    #resultado-scroll { height: 1fr; padding: 1 2; }
    #resultado { width: 1fr; }
    """

    def __init__(
        self,
        carregar_repos: RepoLoader,
        carregar_versoes: VersionLoader,
        executar: VerifyRunner,
    ) -> None:
        super().__init__()
        self._carregar_repos = carregar_repos
        self._carregar_versoes = carregar_versoes
        self._executar = executar
        self._repo: RepoOption | None = None
        self._versao: VersionOption | None = None
        self._ocupado = False
        self._tem_repos = False
        self._tem_versoes = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="barra"):
            yield Select([], prompt="Repo", id="repo", disabled=True)
            yield Static("Verificar", id="acao")
            yield Select([], prompt="Versão", id="versao", disabled=True)
            yield Checkbox("Auditar tag agora", id="auditar")
            yield Button("Executar", id="executar", variant="primary", disabled=True)
        with VerticalScroll(id="resultado-scroll"):
            yield Static("Selecione um repositório.", id="resultado")
        yield Footer()

    def on_mount(self) -> None:
        self.carregar_repos_worker()

    def _erro(self, mensagem: str) -> None:
        self.query_one("#resultado", Static).update(
            Panel(mensagem, title="Erro", style="bold red")
        )

    def _mostrar_resultado(self, status: VersionStatus, auditado: bool) -> None:
        self.query_one("#resultado", Static).update(
            renderizar_status(status, auditado=auditado)
        )

    def _falha(self, erro: Exception) -> None:
        if isinstance(erro, MotorError):
            self._erro(str(erro))
            return
        logging.error(
            "Erro interno fatal na TUI",
            exc_info=(type(erro), erro, erro.__traceback__),
        )
        self._erro("Erro interno fatal")

    def _bloquear(self, ocupado: bool) -> None:
        self._ocupado = ocupado
        self.query_one("#repo", Select).disabled = ocupado or not self._tem_repos
        self.query_one("#versao", Select).disabled = ocupado or not self._tem_versoes
        self.query_one("#auditar", Checkbox).disabled = ocupado
        self.query_one("#executar", Button).disabled = (
            ocupado or self._repo is None or self._versao is None
        )

    @work(thread=True, exclusive=True, group="repos")
    def carregar_repos_worker(self) -> None:
        try:
            opcoes = self._carregar_repos()
        except Exception as erro:
            self.call_from_thread(self._falha, erro)
            return
        self.call_from_thread(self._mostrar_repos, opcoes)

    def _mostrar_repos(self, opcoes: list[RepoOption]) -> None:
        select = self.query_one("#repo", Select)
        select.set_options(
            [
                (
                    Text(
                        opcao.nome
                        if opcao.disponivel
                        else f"{opcao.nome} — checkout local não encontrado",
                        style="" if opcao.disponivel else "dim",
                    ),
                    opcao,
                )
                for opcao in opcoes
            ]
        )
        self._tem_repos = bool(opcoes)
        self._bloquear(False)
        if opcoes and not any(opcao.disponivel for opcao in opcoes):
            self._erro("nenhum checkout local encontrado; confira PROJECTS_DIR")

    def on_select_changed(self, evento: Select.Changed) -> None:
        if evento.select.id == "repo":
            self._selecionar_repo(evento.value)
        elif evento.select.id == "versao":
            self._selecionar_versao(evento.value)

    def _selecionar_repo(self, valor: object) -> None:
        self._repo = valor if isinstance(valor, RepoOption) else None
        self._versao = None
        self._tem_versoes = False
        versoes = self.query_one("#versao", Select)
        versoes.set_options([])
        versoes.value = Select.NULL
        versoes.disabled = True
        self.query_one("#auditar", Checkbox).display = False
        if self._repo is None:
            self._bloquear(False)
            return
        if not self._repo.disponivel:
            self._erro("checkout local não encontrado")
            self._bloquear(False)
            return
        self._bloquear(True)
        self.carregar_versoes_worker(self._repo)

    @work(thread=True, exclusive=True, group="versoes")
    def carregar_versoes_worker(self, repo: RepoOption) -> None:
        try:
            opcoes = self._carregar_versoes(repo)
        except Exception as erro:
            self.call_from_thread(self._falha, erro)
            self.call_from_thread(self._bloquear, False)
            return
        self.call_from_thread(self._mostrar_versoes, opcoes)

    def _mostrar_versoes(self, opcoes: list[VersionOption]) -> None:
        select = self.query_one("#versao", Select)
        select.set_options([(opcao.numero, opcao) for opcao in opcoes])
        self._tem_versoes = bool(opcoes)
        self._bloquear(False)
        if not opcoes:
            self._erro("nenhuma branch ou tag X.Y.Z encontrada")

    def _selecionar_versao(self, valor: object) -> None:
        self._versao = valor if isinstance(valor, VersionOption) else None
        auditoria = self.query_one("#auditar", Checkbox)
        auditoria.value = False
        auditoria.display = bool(self._versao and self._versao.liberada)
        self._bloquear(False)

    def on_button_pressed(self, evento: Button.Pressed) -> None:
        if evento.button.id != "executar" or self._ocupado:
            return
        if self._repo is None or self._versao is None:
            return
        self._bloquear(True)
        self.executar_worker(
            self._repo,
            self._versao,
            self.query_one("#auditar", Checkbox).value,
        )

    @work(thread=True, exclusive=True, group="executar")
    def executar_worker(
        self, repo: RepoOption, versao: VersionOption, auditar: bool
    ) -> None:
        try:
            status = self._executar(repo, versao.numero, auditar)
        except Exception as erro:
            self.call_from_thread(self._falha, erro)
        else:
            self.call_from_thread(self._mostrar_resultado, status, auditar)
        finally:
            self.call_from_thread(self._bloquear, False)


def descobrir_repos(estado: EstadoRepo, projects_dir: str) -> list[RepoOption]:
    repos = estado.listar_repos()
    canonicos = {repo.nome: repo for repo in repos}
    encontrados: dict[str, Path] = {}
    raiz = Path(projects_dir)

    if raiz.is_dir():
        for caminho in sorted(raiz.iterdir(), key=lambda item: item.name):
            if not caminho.is_dir() or not (caminho / ".git").exists():
                continue
            if caminho.name in canonicos:
                info = canonicos[caminho.name]
            else:
                try:
                    info = estado.resolver_repo(caminho.name)
                except MotorError as erro:
                    if "desconhecido" in str(erro):
                        continue
                    raise
            atual = encontrados.get(info.nome)
            if atual is None or (
                caminho.name == info.nome and atual.name != info.nome
            ):
                encontrados[info.nome] = caminho

    return [
        RepoOption(
            nome=repo.nome,
            caminho=str(encontrados[repo.nome]) if repo.nome in encontrados else None,
        )
        for repo in repos
    ]


def _chave_versao(numero: str) -> tuple[int, int, int]:
    major, minor, patch = numero.split(".")
    return int(major), int(minor), int(patch)


def descobrir_versoes(git: GitRepo) -> list[VersionOption]:
    git.fetch("origin")
    tags = set(git.list_version_tags())
    numeros = sorted(
        set(git.list_version_branches()), key=_chave_versao, reverse=True
    )
    return [VersionOption(numero, numero in tags) for numero in numeros]


def _resumo(status: VersionStatus) -> Table:
    tabela = Table.grid(expand=True)
    for _ in range(4):
        tabela.add_column(ratio=1)
    tabela.add_row(
        f"Tasks novas {len(status.tasks_novas)}",
        f"Tasks removidas {len(status.tasks_removidas)}",
        f"Faltantes {len(status.faltantes)}",
        f"Conflitos {len(status.conflitantes)}",
    )
    return tabela


def _alertas(status: VersionStatus) -> Text | None:
    linhas: list[str] = []
    if status.tasks_ambiguas:
        linhas.append(f"Tasks em mais de uma versão: {', '.join(status.tasks_ambiguas)}")
    if status.tasks_sem_commits:
        linhas.append(f"Tasks sem commits: {', '.join(status.tasks_sem_commits)}")
    if not status.estado_integro:
        hashes = ", ".join(hash_[:8] for hash_ in status.commits_sumidos)
        linhas.append(f"Estado divergente do git: {hashes}")
    return Text("\n".join(linhas), style="bold yellow") if linhas else None


def _faltantes(status: VersionStatus) -> Table | None:
    if not status.faltantes:
        return None
    conflitos = {commit.hash_origem for commit in status.conflitantes}
    suspeitos = {commit.hash_origem for commit in status.suspeitos_conteudo}
    tabela = Table("Chamado", "Commit", "Mensagem", "Estado", expand=True)
    for chamado, commits in _agrupar_por_task(status.faltantes).items():
        for commit in commits:
            badges: list[str] = []
            if commit.hash_origem in conflitos:
                badges.append("CONFLITANTE")
            if commit.hash_origem in suspeitos:
                badges.append("SUSPEITO")
            tabela.add_row(
                chamado,
                commit.hash_origem[:8],
                commit.msg.splitlines()[0] if commit.msg else "",
                " · ".join(badges) or "FALTANTE",
            )
    return tabela


def renderizar_status(status: VersionStatus, auditado: bool = False) -> Group:
    if status.liberada_em is not None and not auditado:
        return Group(
            Panel("SNAPSHOT CONGELADO", style="bold green"),
            Text(f"Liberada em {status.liberada_em:%Y-%m-%d %H:%M}"),
            Text(f"Chamados: {', '.join(status.chamados)}"),
        )

    partes: list = []
    if auditado:
        partes.append(Text("AUDITORIA DA TAG — snapshot não alterado", style="bold cyan"))
    titulo = "VERDE" if status.verde else "REQUER ATENÇÃO"
    estilo = "bold green" if status.verde else "bold red"
    partes.extend([Panel(titulo, style=estilo), _resumo(status)])
    alertas = _alertas(status)
    faltantes = _faltantes(status)
    if alertas is not None:
        partes.append(alertas)
    if faltantes is not None:
        partes.append(faltantes)
    return Group(*partes)
