from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.progress_bar import ProgressBar as BarraRich
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    OptionList,
    Select,
    Static,
)
from textual.widgets.option_list import Option

from motor.__main__ import _abrir_sessao, _nome_repo, _tickio_sistema_id
from motor.adapters.estado.postgres import PostgresEstado
from motor.adapters.git.subprocess import new_git_subprocess
from motor.adapters.tasksource.tickio import TickioRest
from motor.__main__ import _agrupar_por_task
from motor.domain.types import VersionStatus
from motor.domain.version import chave
from motor.engine.atualizar import AtualizarResult, AtualizarStatus, atualizar
from motor.engine.consultar import ChamadoConsultado, consultar
from motor.engine.deps import Deps
from motor.engine.verificar import verificar
from motor.errors import MotorError
from motor.ports import EstadoRepo, GitRepo
from motor.progresso import Progresso, RelatorProgresso, SlotProgresso, silencioso


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
ConsultaRunner = Callable[[RepoOption, str], list[ChamadoConsultado]]
RepoRegistrar = Callable[[str, int], None]


class ResultadoModal(ModalScreen[None]):
    """Resultado de verificar/atualizar por cima da lista de chamados.

    A lista continua montada embaixo: fechar o modal volta para ela em vez de
    exigir uma troca de versao para reconstrui-la.
    """

    BINDINGS = [("escape,enter,q", "dismiss", "Fechar")]
    DEFAULT_CSS = """
    ResultadoModal { align: center middle; }
    ResultadoModal > VerticalScroll {
        width: 90%;
        height: 80%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    """

    def __init__(self, conteudo: object) -> None:
        super().__init__()
        self._conteudo = conteudo

    def compose(self) -> ComposeResult:
        with VerticalScroll() as caixa:
            caixa.border_subtitle = "esc para fechar"
            yield Static(self._conteudo, id="modal-conteudo")


class CadastroModal(ModalScreen["tuple[str, int] | None"]):
    """Formulario de cadastro de repo.

    Valida o formato aqui, com as mesmas funcoes que o CLI usa, e devolve o par
    pronto. Erro de banco (nome duplicado) nao e do formulario: sai pelo
    caminho de erro normal do app, com o modal ja fechado.
    """

    BINDINGS = [("escape", "cancelar", "Cancelar")]
    DEFAULT_CSS = """
    CadastroModal { align: center middle; }
    CadastroModal > Vertical {
        width: 60;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    CadastroModal .rotulo { height: auto; color: $text-muted; }
    #cadastro-erro { height: auto; color: $error; }
    #cadastro-botoes { height: auto; align-horizontal: right; padding-top: 1; }
    #cadastro-botoes Button { margin-left: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical() as caixa:
            caixa.border_title = "Cadastrar repositório"
            caixa.border_subtitle = "esc para cancelar"
            yield Static("nome", classes="rotulo")
            yield Input(placeholder="nome canônico, sem caminho", id="cadastro-nome")
            yield Static("tickio_sistema_id", classes="rotulo")
            yield Input(placeholder="inteiro positivo", id="cadastro-sistema")
            yield Static(id="cadastro-erro")
            with Horizontal(id="cadastro-botoes"):
                yield Button("Cancelar", id="cadastro-cancelar")
                yield Button("Salvar", id="cadastro-salvar", variant="primary")

    def action_cancelar(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, evento: Button.Pressed) -> None:
        if evento.button.id == "cadastro-salvar":
            self._salvar()
        else:
            self.dismiss(None)

    def on_input_submitted(self, evento: Input.Submitted) -> None:
        self._salvar()

    def _salvar(self) -> None:
        try:
            nome = _nome_repo(self.query_one("#cadastro-nome", Input).value)
            sistema_id = _tickio_sistema_id(
                self.query_one("#cadastro-sistema", Input).value
            )
        except argparse.ArgumentTypeError as erro:
            self.query_one("#cadastro-erro", Static).update(str(erro))
            return
        self.dismiss((nome, sistema_id))


def renderizar_progresso(progresso: Progresso, quadro: int = 0) -> Group:
    """Fase em cima, barra e contagem lado a lado embaixo.

    Fase sem total vira pulso em vez de barra: barra parada em 0% durante um
    `fetch` de 20s sugere travamento.
    """
    linha = Table.grid(padding=(0, 2))
    if progresso.total:
        linha.add_row(
            BarraRich(total=progresso.total, completed=progresso.feito, width=40),
            Text(f"{progresso.feito}/{progresso.total}", style="dim"),
        )
    else:
        # animation_time anda com o quadro do pintor: o rich desenha o pulso a
        # partir dele, e fixo o pulso sai congelado — igualzinho a uma barra
        # travada, que e exatamente o que o pulso existe para desmentir.
        linha.add_row(BarraRich(pulse=True, width=40, animation_time=quadro / 10))
    return Group(Text(progresso.fase), Text(""), linha)


class PainelProgresso(Static):
    """Cobre o painel enquanto o comando roda, no lugar do spinner generico.

    Devolvido por `MotorTUI.get_loading_widget`, entao vale para os dois paineis
    (resultado e lista de chamados) de uma vez — `loading = True` em qualquer
    widget passa a mostrar isto.

    Desenha tudo num renderable so, sem widgets filhos, e isso e proposital: o
    Textual pendura o widget de cobertura fora da arvore de nos e o compoe num
    tick posterior, entao qualquer `query_one` daqui e uma corrida contra o
    primeiro tick do pintor — que este projeto ja perdeu de forma intermitente.
    """

    DEFAULT_CSS = """
    PainelProgresso {
        width: 100%;
        height: 100%;
        content-align: center middle;
        color: $text-muted;
    }
    """

    #: ultimo evento desenhado; e o que os testes leem para nao depender do
    #: texto renderizado.
    progresso: Progresso | None = None
    _quadro: int = 0

    def mostrar(self, progresso: Progresso | None) -> None:
        if progresso is None:
            return
        self.progresso = progresso
        self._quadro += 1
        self.update(renderizar_progresso(progresso, self._quadro))


class MotorTUI(App[None]):
    BINDINGS = [
        ("q", "quit", "Sair"),
        ("v", "verificar", "Verificar"),
        ("u", "atualizar", "Atualizar"),
        ("n", "cadastrar", "Cadastrar repo"),
    ]
    CSS = """
    #barra { height: auto; padding: 1; align-vertical: middle; }
    .rotulo { width: auto; height: auto; padding: 1 1 0 0; color: $text-muted; }
    #separador { width: 3; height: auto; padding-top: 1; color: $text-muted; text-align: center; }
    #repo { width: 2fr; max-width: 30; }
    #versao { width: 1fr; max-width: 30; }
    #verificar, #atualizar { width: 18; margin-left: 1; }
    #auditar { display: none; height: auto; margin: 0 1; }
    #conteudo { height: 1fr; }
    #resultado-scroll { height: 1fr; padding: 1 2; }
    #resultado { width: 1fr; }
    #consulta-painel { display: none; height: 1fr; padding: 1 2; }
    #consulta-resumo { height: auto; padding-bottom: 1; color: $text-muted; }
    #consulta-corpo { height: 1fr; }
    #consulta-chamados { width: 34; height: 1fr; border-right: tall $primary; }
    #consulta-detalhe-scroll { width: 1fr; height: 1fr; padding-left: 2; }
    #consulta-detalhe { width: 1fr; }
    """

    def __init__(
        self,
        carregar_repos: RepoLoader,
        carregar_versoes: VersionLoader,
        executar: VerifyRunner,
        atualizar_repo: UpdateRunner | None = None,
        consultar_versao: ConsultaRunner | None = None,
        registrar_repo: RepoRegistrar | None = None,
        slot: SlotProgresso | None = None,
    ) -> None:
        super().__init__()
        # Compartilhado com os runners (ver run_tui): eles relatam de dentro da
        # thread do worker, esta classe so amostra na thread principal.
        self._slot = slot or SlotProgresso()
        self._painel_progresso: PainelProgresso | None = None
        self._carregar_repos = carregar_repos
        self._carregar_versoes = carregar_versoes
        self._executar = executar
        self._atualizar = atualizar_repo
        self._consultar = consultar_versao
        self._registrar = registrar_repo
        self._repo: RepoOption | None = None
        self._versao: VersionOption | None = None
        self._ocupado = False
        self._tem_repos = False
        self._tem_versoes = False
        self._geracao_versoes = 0
        self._pode_atualizar = False
        self._chamados_consultados: list[ChamadoConsultado] = []

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
        with Container(id="conteudo"):
            with VerticalScroll(id="resultado-scroll"):
                yield Static("Selecione um repositório.", id="resultado")
            with Vertical(id="consulta-painel"):
                yield Static(id="consulta-resumo")
                with Horizontal(id="consulta-corpo"):
                    yield OptionList(id="consulta-chamados", compact=True)
                    with VerticalScroll(id="consulta-detalhe-scroll"):
                        yield Static(id="consulta-detalhe")
        yield Footer()

    def on_mount(self) -> None:
        self.carregar_repos_worker()
        # Amostragem a 10 Hz em vez de call_from_thread por evento: o motor
        # relata uma vez por commit, e cada call_from_thread bloquearia a thread
        # dele ate o loop desenhar (ver SlotProgresso).
        self.set_interval(0.1, self._pintar_progresso)

    def get_loading_widget(self) -> Widget:
        self._painel_progresso = PainelProgresso()
        return self._painel_progresso

    def _pintar_progresso(self) -> None:
        painel = self._painel_progresso
        if painel is None or not painel.is_mounted:
            return
        painel.mostrar(self._slot.ultimo)

    def _exibir_resultado(self, conteudo: object) -> Static:
        self.query_one("#consulta-painel").display = False
        self.query_one("#resultado-scroll").display = True
        resultado = self.query_one("#resultado", Static)
        resultado.update(conteudo)
        return resultado

    def _apresentar(self, conteudo: object, *, reconsultar: bool = False) -> None:
        """Com a lista de chamados na tela, resultado e transitorio: vai para um
        modal e ao fechar recarrega a lista, que o verificar/atualizar acabou de
        reescrever no banco. Sem lista, ocupa o painel como antes.
        """
        if not self.query_one("#consulta-painel").display:
            self._exibir_resultado(conteudo)
            return
        self.push_screen(
            ResultadoModal(conteudo),
            (lambda _: self._reconsultar()) if reconsultar else None,
        )

    def _ocupar_lista(self) -> bool:
        """Marca a lista de chamados como carregando, se e ela que esta na tela."""
        painel = self.query_one("#consulta-painel")
        painel.loading = painel.display
        return painel.display

    def _reconsultar(self) -> None:
        if self._repo is None or self._versao is None or self._consultar is None:
            return
        self._ocupar_lista()
        self._bloquear(True)
        self.consultar_worker(self._repo, self._versao)

    def _erro(self, mensagem: str, transitorio: bool = False) -> None:
        painel = Panel(mensagem, title="Erro", style="bold red")
        if transitorio:
            self._apresentar(painel)
        else:
            self._exibir_resultado(painel)

    def _mostrar_resultado(self, status: VersionStatus, auditado: bool) -> None:
        # Auditoria nao persiste (verificar --auditar nao toca no snapshot):
        # recarregar a lista traria o mesmo conteudo por um round de git a mais.
        self._apresentar(
            renderizar_status(status, auditado=auditado),
            reconsultar=not auditado,
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
        self._apresentar(renderizar_atualizacao(resultado), reconsultar=True)
        self._resetar_atualizacao()

    def _mostrar_consulta(self, chamados: list[ChamadoConsultado]) -> None:
        self._chamados_consultados = chamados
        lista = self.query_one("#consulta-chamados", OptionList)
        lista.clear_options()
        if not chamados:
            self._exibir_resultado(
                Text("Nenhum chamado registrado para esta versão.", style="dim")
            )
            return

        total_commits = sum(len(chamado.commits) for chamado in chamados)
        numero = self._versao.numero if self._versao else ""
        self.query_one("#consulta-resumo", Static).update(
            Text.assemble(
                (numero, "bold"),
                (f"  ·  {len(chamados)} chamados", "dim"),
                (f"  ·  {total_commits} commits", "dim"),
                ("  ·  snapshot salvo", "green"),
            )
        )
        lista.add_options(
            [
                Option(
                    Text.assemble(
                        (f"#{chamado.chamado}", "bold"),
                        (f"  {len(chamado.commits)}", "dim"),
                        (
                            f"  ● {chamado.estado}",
                            "green" if chamado.estado == "aplicado" else "yellow",
                        ),
                    ),
                    id=str(indice),
                )
                for indice, chamado in enumerate(chamados)
            ]
        )
        self.query_one("#resultado-scroll").display = False
        self.query_one("#consulta-painel").display = True
        lista.highlighted = 0
        self._mostrar_detalhe_consulta(0)
        lista.focus()

    def _mostrar_detalhe_consulta(self, indice: int) -> None:
        self.query_one("#consulta-detalhe", Static).update(
            renderizar_chamado(self._chamados_consultados[indice])
        )

    def on_option_list_option_highlighted(
        self, evento: OptionList.OptionHighlighted
    ) -> None:
        if evento.option_list.id == "consulta-chamados":
            self._mostrar_detalhe_consulta(evento.option_index)

    def _resetar_atualizacao(self) -> None:
        self._pode_atualizar = False
        botao = self.query_one("#atualizar", Button)
        botao.label = "Atualizar"
        botao.variant = "default"
        self.query_one("#verificar", Button).variant = "primary"

    def _falha(self, erro: Exception, transitorio: bool = False) -> None:
        if isinstance(erro, MotorError):
            self._erro(str(erro), transitorio)
            return
        logging.error(
            "Erro interno fatal na TUI",
            exc_info=(type(erro), erro, erro.__traceback__),
        )
        self._erro("Erro interno fatal", transitorio)

    def _bloquear(self, ocupado: bool) -> None:
        self._ocupado = ocupado
        if ocupado:
            # Aqui e nao em cada _iniciar_*: todo caminho que dispara worker
            # passa por este ponto, e sem limpar a fase final do comando
            # anterior pisca antes da primeira do novo.
            self._slot.limpar()
        if not ocupado:
            self.query_one("#resultado", Static).loading = False
            self.query_one("#consulta-painel").loading = False
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
        select.query_one(OptionList).disable_option_at_index(0)
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
        self._exibir_resultado(
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
        select.query_one(OptionList).disable_option_at_index(0)
        self._tem_versoes = bool(opcoes)
        self._bloquear(False)
        self._exibir_resultado("Selecione uma versão.")
        if not opcoes:
            self._erro("nenhuma branch ou tag X.Y.Z encontrada")

    def _selecionar_versao(self, valor: object) -> None:
        self._versao = valor if isinstance(valor, VersionOption) else None
        self._resetar_atualizacao()
        auditoria = self.query_one("#auditar", Checkbox)
        auditoria.value = False
        auditoria.display = bool(self._versao and self._versao.liberada)
        if self._versao is not None and self._repo is not None and self._consultar:
            resultado = self._exibir_resultado(
                f"Consultando {self._repo.nome} {self._versao.numero}…"
            )
            resultado.loading = True
            self._bloquear(True)
            self.consultar_worker(self._repo, self._versao)
        elif self._versao is not None:
            self._exibir_resultado(
                f"Pronto para verificar {self._repo.nome} {self._versao.numero}."
            )
        if not self._ocupado:
            self._bloquear(False)

    def on_button_pressed(self, evento: Button.Pressed) -> None:
        if evento.button.id == "verificar":
            self._iniciar_verificacao()
        elif evento.button.id == "atualizar":
            self._iniciar_atualizacao()

    def action_cadastrar(self) -> None:
        if self._ocupado or self._registrar is None:
            return
        self.push_screen(CadastroModal(), self._cadastrar)

    def _cadastrar(self, dados: tuple[str, int] | None) -> None:
        if dados is None:
            return
        self._bloquear(True)
        self.cadastrar_worker(*dados)

    @work(thread=True, exclusive=True, group="cadastro")
    def cadastrar_worker(self, nome: str, sistema_id: int) -> None:
        try:
            if self._registrar is not None:
                self._registrar(nome, sistema_id)
        except Exception as erro:
            self.call_from_thread(self._falha, erro)
            self.call_from_thread(self._bloquear, False)
            return
        self.call_from_thread(self._cadastrado, nome)

    def _cadastrado(self, nome: str) -> None:
        self._exibir_resultado(f"repo '{nome}' cadastrado.")
        self.carregar_repos_worker()

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
        if not self._ocupar_lista():
            self._exibir_resultado(
                f"Verificando {self._repo.nome} {self._versao.numero}…"
            ).loading = True
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
        self._ocupar_lista()
        self._bloquear(True)
        self.atualizar_worker(self._repo, self._versao)

    @work(thread=True, exclusive=True, group="executar")
    def executar_worker(
        self, repo: RepoOption, versao: VersionOption, auditar: bool
    ) -> None:
        try:
            status = self._executar(repo, versao.numero, auditar)
        except Exception as erro:
            self.call_from_thread(self._falha, erro, True)
        else:
            self.call_from_thread(self._mostrar_resultado, status, auditar)
        finally:
            self.call_from_thread(self._bloquear, False)

    @work(thread=True, exclusive=True, group="consulta")
    def consultar_worker(self, repo: RepoOption, versao: VersionOption) -> None:
        try:
            chamados = self._consultar(repo, versao.numero) if self._consultar else []
        except Exception as erro:
            self.call_from_thread(self._falha, erro)
        else:
            self.call_from_thread(self._mostrar_consulta, chamados)
        finally:
            self.call_from_thread(self._bloquear, False)

    @work(thread=True, exclusive=True, group="executar")
    def atualizar_worker(self, repo: RepoOption, versao: VersionOption) -> None:
        try:
            resultado = self._atualizar(repo, versao.numero) if self._atualizar else None
        except Exception as erro:
            self.call_from_thread(self._falha, erro, True)
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


def descobrir_versoes(
    git: GitRepo, *, progresso: RelatorProgresso = silencioso
) -> list[VersionOption]:
    progresso(Progresso("buscando refs do origin"))
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


def _registrar_no_banco(nome: str, sistema_id: int) -> None:
    with _abrir_sessao() as sessao:
        PostgresEstado(sessao=sessao).registrar_repo(nome, sistema_id)


def _versoes_do_repo(
    repo: RepoOption, *, progresso: RelatorProgresso = silencioso
) -> list[VersionOption]:
    if repo.caminho is None:
        return []
    return descobrir_versoes(new_git_subprocess(repo.caminho), progresso=progresso)


def _deps_do_repo(
    repo: RepoOption, sessao: object, progresso: RelatorProgresso = silencioso
) -> Deps:
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
        progresso=progresso,
    )


def _verificar_repo(
    repo: RepoOption,
    versao: str,
    auditar: bool,
    *,
    progresso: RelatorProgresso = silencioso,
) -> VersionStatus:
    with _abrir_sessao() as sessao:
        deps = _deps_do_repo(repo, sessao, progresso)
        return verificar(deps, versao, auditar=auditar)


def _atualizar_repo(
    repo: RepoOption, versao: str, *, progresso: RelatorProgresso = silencioso
) -> AtualizarResult:
    with _abrir_sessao() as sessao:
        return atualizar(_deps_do_repo(repo, sessao, progresso), versao)


def _consultar_repo(
    repo: RepoOption, versao: str, *, progresso: RelatorProgresso = silencioso
) -> list[ChamadoConsultado]:
    with _abrir_sessao() as sessao:
        return consultar(_deps_do_repo(repo, sessao, progresso), versao)


def run_tui() -> None:
    # O relator entra por `partial`, nao na assinatura dos runners que a TUI
    # chama: assim os aliases (VerifyRunner e companhia) e os doubles dos testes
    # seguem com a mesma aridade, e quem injeta runner nao precisa saber que
    # progresso existe.
    slot = SlotProgresso()
    MotorTUI(
        _repos_do_ambiente,
        partial(_versoes_do_repo, progresso=slot.relatar),
        partial(_verificar_repo, progresso=slot.relatar),
        partial(_atualizar_repo, progresso=slot.relatar),
        partial(_consultar_repo, progresso=slot.relatar),
        _registrar_no_banco,
        slot=slot,
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
            title=f"#{chamado} · {quantidade} commit{'s' if quantidade != 1 else ''}",
            title_justify="left",
            expand=True,
            box=box.SIMPLE_HEAD,
            show_edge=False,
            pad_edge=False,
        )
        tabela.add_column("Commit", width=8, no_wrap=True)
        tabela.add_column("Mensagem", ratio=1, no_wrap=True, overflow="ellipsis")
        tabela.add_column("Estado", width=24, no_wrap=True)
        for commit in itens:
            tabela.add_row(
                commit.hash_origem[:8],
                commit.msg.splitlines()[0] if commit.msg else "",
                estados.get(commit.hash_origem, ""),
            )
        tabelas.append(tabela)
    return Group(*tabelas)


def renderizar_chamado(chamado: ChamadoConsultado) -> Group:
    quantidade = len(chamado.commits)
    cabecalho = Text.assemble(
        (f"#{chamado.chamado}", "bold"),
        (f"  ·  {quantidade} commit{'s' if quantidade != 1 else ''}", "dim"),
        (
            f"  ·  {chamado.estado.upper()}",
            "bold green" if chamado.estado == "aplicado" else "bold yellow",
        ),
    )
    if not chamado.commits:
        return Group(cabecalho, Text("Nenhum commit registrado.", style="dim"))

    tabela = Table(
        expand=True,
        box=box.SIMPLE_HEAD,
        show_edge=False,
        pad_edge=False,
    )
    tabela.add_column("Commit", width=8, no_wrap=True)
    tabela.add_column("Título", ratio=1, no_wrap=True, overflow="ellipsis")
    for commit in chamado.commits:
        tabela.add_row(
            commit.hash_origem[:8],
            commit.msg.splitlines()[0] if commit.msg else "mensagem indisponível",
        )
    return Group(cabecalho, tabela)


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
