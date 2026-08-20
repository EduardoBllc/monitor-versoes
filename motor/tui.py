from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Checkbox, Footer, Header, Select, Static

from motor.__main__ import _abrir_sessao
from motor.adapters.estado.postgres import PostgresEstado
from motor.adapters.git.subprocess import new_git_subprocess
from motor.adapters.tasksource.tickio import TickioRest
from motor.__main__ import _agrupar_por_task
from motor.domain.types import VersionStatus
from motor.domain.version import chave
from motor.engine.atualizar import AtualizarResult, AtualizarStatus, atualizar
from motor.engine.deps import Deps
from motor.engine.verificar import verificar
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
UpdateRunner = Callable[[RepoOption, str], AtualizarResult]


class MotorTUI(App[None]):
    BINDINGS = [
        ("q", "quit", "Sair"),
        ("v", "verificar", "Verificar"),
        ("u", "atualizar", "Atualizar"),
    ]
    CSS = """
    #barra { height: auto; padding: 1; align-vertical: middle; }
    .rotulo { width: auto; height: auto; padding: 1 1 0 0; color: $text-muted; }
    #separador { width: 3; height: auto; padding-top: 1; color: $text-muted; text-align: center; }
    #repo { width: 2fr; max-width: 30; }
    #versao { width: 1fr; max-width: 30; }
    #verificar, #atualizar { width: 18; margin-left: 1; }
    #auditar { display: none; height: auto; margin: 0 1; }
    #resultado-scroll { height: 1fr; padding: 1 2; }
    #resultado { width: 1fr; }
    """

    def __init__(
        self,
        carregar_repos: RepoLoader,
        carregar_versoes: VersionLoader,
        executar: VerifyRunner,
        atualizar_repo: UpdateRunner | None = None,
    ) -> None:
        super().__init__()
        self._carregar_repos = carregar_repos
        self._carregar_versoes = carregar_versoes
        self._executar = executar
        self._atualizar = atualizar_repo
        self._repo: RepoOption | None = None
        self._versao: VersionOption | None = None
        self._ocupado = False
        self._tem_repos = False
        self._tem_versoes = False
        self._geracao_versoes = 0
        self._pode_atualizar = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="barra"):
            yield Static("repo", classes="rotulo")
            yield Select([], prompt="Repo", id="repo", disabled=True)
            yield Static("/", id="separador")
            yield Static("versão", classes="rotulo")
            yield Select([], prompt="Versão", id="versao", disabled=True)
            yield Checkbox("Auditar tag agora", id="auditar")
            yield Button("Verificar", id="verificar", variant="primary", disabled=True)
            yield Button("Atualizar", id="atualizar", disabled=True)
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
        self._pode_atualizar = bool(
            self._atualizar
            and self._versao
            and not self._versao.liberada
            and status.faltantes
        )
        atualizar_botao = self.query_one("#atualizar", Button)
        atualizar_botao.label = (
            f"Atualizar · {len(status.faltantes)}"
            if self._pode_atualizar
            else "Atualizar"
        )
        atualizar_botao.variant = "warning" if self._pode_atualizar else "default"
        self.query_one("#verificar", Button).variant = (
            "default" if self._pode_atualizar else "primary"
        )

    def _mostrar_atualizacao(self, resultado: AtualizarResult) -> None:
        self.query_one("#resultado", Static).update(
            renderizar_atualizacao(resultado)
        )
        self._resetar_atualizacao()

    def _resetar_atualizacao(self) -> None:
        self._pode_atualizar = False
        botao = self.query_one("#atualizar", Button)
        botao.label = "Atualizar"
        botao.variant = "default"
        self.query_one("#verificar", Button).variant = "primary"

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
        if not ocupado:
            self.query_one("#resultado", Static).loading = False
        self.query_one("#repo", Select).disabled = ocupado or not self._tem_repos
        self.query_one("#versao", Select).disabled = ocupado or not self._tem_versoes
        self.query_one("#auditar", Checkbox).disabled = ocupado
        self.query_one("#verificar", Button).disabled = (
            ocupado or self._repo is None or self._versao is None
        )
        self.query_one("#atualizar", Button).disabled = (
            ocupado or not self._pode_atualizar
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
        self._geracao_versoes += 1
        self._resetar_atualizacao()
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
        self.query_one("#resultado", Static).update(
            f"Carregando versões de {self._repo.nome}…"
        )
        self._bloquear(True)
        self.carregar_versoes_worker(self._repo, self._geracao_versoes)

    @work(thread=True, exclusive=True, group="versoes")
    def carregar_versoes_worker(self, repo: RepoOption, geracao: int) -> None:
        try:
            opcoes = self._carregar_versoes(repo)
        except Exception as erro:
            self.call_from_thread(self._falha_versoes, repo, geracao, erro)
            return
        self.call_from_thread(self._mostrar_versoes, repo, geracao, opcoes)

    def _falha_versoes(self, repo: RepoOption, geracao: int, erro: Exception) -> None:
        if self._repo != repo or self._geracao_versoes != geracao:
            return
        self._falha(erro)
        self._bloquear(False)

    def _mostrar_versoes(
        self, repo: RepoOption, geracao: int, opcoes: list[VersionOption]
    ) -> None:
        if self._repo != repo or self._geracao_versoes != geracao:
            return
        select = self.query_one("#versao", Select)
        select.set_options([(opcao.numero, opcao) for opcao in opcoes])
        self._tem_versoes = bool(opcoes)
        self._bloquear(False)
        self.query_one("#resultado", Static).update("Selecione uma versão.")
        if not opcoes:
            self._erro("nenhuma branch ou tag X.Y.Z encontrada")

    def _selecionar_versao(self, valor: object) -> None:
        self._versao = valor if isinstance(valor, VersionOption) else None
        self._resetar_atualizacao()
        auditoria = self.query_one("#auditar", Checkbox)
        auditoria.value = False
        auditoria.display = bool(self._versao and self._versao.liberada)
        if self._versao is not None:
            self.query_one("#resultado", Static).update(
                f"Pronto para verificar {self._repo.nome} {self._versao.numero}."
            )
        if not self._ocupado:
            self._bloquear(False)

    def on_button_pressed(self, evento: Button.Pressed) -> None:
        if evento.button.id == "verificar":
            self._iniciar_verificacao()
        elif evento.button.id == "atualizar":
            self._iniciar_atualizacao()

    def action_verificar(self) -> None:
        self._iniciar_verificacao()

    def action_atualizar(self) -> None:
        self._iniciar_atualizacao()

    def _iniciar_verificacao(self) -> None:
        if self._ocupado:
            return
        if self._repo is None or self._versao is None:
            return
        self._resetar_atualizacao()
        resultado = self.query_one("#resultado", Static)
        resultado.update(f"Verificando {self._repo.nome} {self._versao.numero}…")
        resultado.loading = True
        self._bloquear(True)
        self.executar_worker(
            self._repo,
            self._versao,
            self.query_one("#auditar", Checkbox).value,
        )

    def _iniciar_atualizacao(self) -> None:
        if self._ocupado or not self._pode_atualizar or self._atualizar is None:
            return
        if self._repo is None or self._versao is None:
            return
        self._bloquear(True)
        self.atualizar_worker(self._repo, self._versao)

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

    @work(thread=True, exclusive=True, group="executar")
    def atualizar_worker(self, repo: RepoOption, versao: VersionOption) -> None:
        try:
            resultado = self._atualizar(repo, versao.numero) if self._atualizar else None
        except Exception as erro:
            self.call_from_thread(self._falha, erro)
        else:
            if resultado is not None:
                self.call_from_thread(self._mostrar_atualizacao, resultado)
        finally:
            self.call_from_thread(self._bloquear, False)


def descobrir_repos(estado: EstadoRepo, projects_dir: str) -> list[RepoOption]:
    repos = estado.listar_repos()
    if not projects_dir:
        return [RepoOption(nome=repo.nome, caminho=None) for repo in repos]
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


def descobrir_versoes(git: GitRepo) -> list[VersionOption]:
    git.fetch("origin")
    tags = set(git.list_version_tags())
    numeros = sorted(
        set(git.list_version_branches()), key=chave, reverse=True
    )
    return [VersionOption(numero, numero in tags) for numero in numeros]


def _repos_do_ambiente() -> list[RepoOption]:
    with _abrir_sessao() as sessao:
        return descobrir_repos(
            PostgresEstado(sessao=sessao), os.environ.get("PROJECTS_DIR", "")
        )


def _versoes_do_repo(repo: RepoOption) -> list[VersionOption]:
    if repo.caminho is None:
        return []
    return descobrir_versoes(new_git_subprocess(repo.caminho))


def _deps_do_repo(repo: RepoOption, sessao: object) -> Deps:
    if repo.caminho is None:
        raise MotorError("checkout local não encontrado")
    git = new_git_subprocess(repo.caminho)
    estado = PostgresEstado(sessao=sessao)
    info = estado.resolver_repo(os.path.basename(repo.caminho))
    tasks = TickioRest(
        base_url=os.environ.get("TICKIO_BASE_URL", ""),
        usuario=os.environ.get("TICKIO_USER", ""),
        senha=os.environ.get("TICKIO_PASSWORD", ""),
        sistema_id=info.tickio_sistema_id,
    )
    return Deps(
        git=git,
        tasks=tasks,
        estado=estado,
        repo=info.nome,
        bitbucket_token=os.environ.get("BITBUCKET_TOKEN", ""),
        bitbucket_email=os.environ.get("BITBUCKET_EMAIL", ""),
    )


def _verificar_repo(
    repo: RepoOption, versao: str, auditar: bool
) -> VersionStatus:
    with _abrir_sessao() as sessao:
        deps = _deps_do_repo(repo, sessao)
        return verificar(deps, versao, auditar=auditar)


def _atualizar_repo(repo: RepoOption, versao: str) -> AtualizarResult:
    with _abrir_sessao() as sessao:
        return atualizar(_deps_do_repo(repo, sessao), versao)


def run_tui() -> None:
    MotorTUI(
        _repos_do_ambiente,
        _versoes_do_repo,
        _verificar_repo,
        _atualizar_repo,
    ).run()


def _resumo(status: VersionStatus) -> Text:
    return Text.assemble(
        ("Escopo ", "dim"),
        (f"+{len(status.tasks_novas)} −{len(status.tasks_removidas)}", "bold"),
        ("  ·  Git ", "dim"),
        (f"{len(status.faltantes)} faltantes", "bold"),
        (" · ", "dim"),
        (f"{len(status.conflitantes)} conflitos", "bold"),
        ("  ·  Sem commits ", "dim"),
        (f"{len(status.tasks_sem_commits)} chamados", "bold"),
    )


def _alertas(status: VersionStatus) -> Text | None:
    linhas: list[str] = []
    if status.tasks_ambiguas:
        linhas.append(
            f"Chamados em mais de uma versão: {', '.join(status.tasks_ambiguas)}"
        )
    if status.tasks_sem_commits:
        linhas.append(f"Chamados sem commits: {', '.join(status.tasks_sem_commits)}")
    if not status.estado_integro:
        hashes = ", ".join(hash_[:8] for hash_ in status.commits_sumidos)
        linhas.append(f"Estado divergente do git: {hashes}")
    return Text("\n".join(linhas), style="bold yellow") if linhas else None


def _commits_agrupados(commits: list, estados: dict[str, str]) -> Group | None:
    if not commits:
        return None
    tabelas: list[Table] = []
    for chamado, itens in _agrupar_por_task(commits).items():
        quantidade = len(itens)
        tabela = Table(
            "Commit",
            "Mensagem",
            "Estado",
            title=f"#{chamado} · {quantidade} commit{'s' if quantidade != 1 else ''}",
            title_justify="left",
            expand=True,
            box=box.SIMPLE_HEAD,
            show_edge=False,
            pad_edge=False,
        )
        for commit in itens:
            tabela.add_row(
                commit.hash_origem[:8],
                commit.msg.splitlines()[0] if commit.msg else "",
                estados.get(commit.hash_origem, ""),
            )
        tabelas.append(tabela)
    return Group(*tabelas)


def _faltantes(status: VersionStatus) -> Group | None:
    if not status.faltantes:
        return None
    conflitos = {commit.hash_origem for commit in status.conflitantes}
    suspeitos = {commit.hash_origem for commit in status.suspeitos_conteudo}
    estados: dict[str, str] = {}
    for commit in status.faltantes:
        badges: list[str] = []
        if commit.hash_origem in conflitos:
            badges.append("CONFLITANTE")
        if commit.hash_origem in suspeitos:
            badges.append("SUSPEITO")
        estados[commit.hash_origem] = " · ".join(badges) or "FALTANTE"
    return _commits_agrupados(status.faltantes, estados)


def renderizar_atualizacao(resultado: AtualizarResult) -> Group:
    bloqueada = resultado.status == AtualizarStatus.BLOCKED
    partes: list = [
        Text(
            "● Atualização bloqueada" if bloqueada else "● Atualização concluída",
            style="bold red" if bloqueada else "bold green",
        )
    ]
    aplicados = _commits_agrupados(
        resultado.aplicados,
        {commit.hash_origem: "APLICADO" for commit in resultado.aplicados},
    )
    if aplicados is not None:
        partes.append(aplicados)
    elif not bloqueada:
        partes.append(Text("Branch já estava atualizada.", style="dim"))
    if resultado.ja_presentes:
        partes.append(
            Text(
                f"{resultado.ja_presentes} commits já presentes no histórico.",
                style="dim",
            )
        )
    if bloqueada:
        partes.append(Text(f"Commit: {resultado.blocked_commit[:8]}"))
        partes.append(Text("Arquivos em conflito:"))
        partes.extend(Text(f"  {caminho}") for caminho in resultado.arquivos_conflito)
        partes.append(
            Text(
                "Resolva os arquivos e continue pela CLI com --continue.",
                style="bold yellow",
            )
        )
    if resultado.status_versao is not None:
        alertas = _alertas(resultado.status_versao)
        if alertas is not None:
            partes.append(alertas)
    return Group(*partes)


def renderizar_status(status: VersionStatus, auditado: bool = False) -> Group:
    partes: list = []
    if status.liberada_em is not None and not auditado:
        partes.extend(
            [
                Text("SNAPSHOT CONGELADO — não recalculado", style="bold cyan"),
                Text(f"Liberada em {status.liberada_em:%Y-%m-%d %H:%M}"),
            ]
        )
        if status.chamados:
            partes.append(Text(f"Chamados: {', '.join(status.chamados)}"))
    elif auditado:
        partes.append(Text("AUDITORIA DA TAG — snapshot não alterado", style="bold cyan"))
    titulo = "VERDE" if status.verde else "● Pendências encontradas"
    estilo = "bold green" if status.verde else "bold yellow"
    partes.extend([Text(titulo, style=estilo), _resumo(status)])
    alertas = _alertas(status)
    faltantes = _faltantes(status)
    if alertas is not None:
        partes.append(alertas)
    if faltantes is not None:
        partes.append(faltantes)
    return Group(*partes)
