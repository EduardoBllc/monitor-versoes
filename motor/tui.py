from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Protocol

from sqlalchemy.orm import Session

from rich import box
from rich.console import RenderableType
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
from textual.visual import VisualType
from textual.widgets.option_list import Option

from motor.adapters.estado.postgres import PostgresEstado
from motor.adapters.git.subprocess import new_git_subprocess
from motor.domain.commits import agrupar_por_chamado
from motor.domain.types import CommitRef, VersionStatus
from motor.domain.version import chave, inferir_base, inferir_tipo
from motor.engine.atualizar import (
    AtualizarResult,
    AtualizarStatus,
    atualizar,
    atualizar_abort,
    atualizar_continue,
)
from motor.engine.consultar import ChamadoConsultado, consultar
from motor.engine.criar import criar
from motor.engine.deps import Deps
from motor.engine.verificar import verificar
from motor.errors import MotorError, NaoEncontrado, formatar_com_notas
from motor.montagem import (
    abrir_sessao,
    montar_deps,
    validar_nome_repo,
    validar_sistema_id,
)
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
AbortRunner = Callable[[RepoOption, str], None]
CriarRunner = Callable[[RepoOption, str], AtualizarResult]


class ContinueRunner(Protocol):
    """Como UpdateRunner, mais o `allow_empty` do `atualizar_continue`: e a
    confirmacao do operador de que a resolucao sem alteracao pode entrar como
    commit vazio."""

    def __call__(
        self, repo: RepoOption, versao: str, /, *, allow_empty: bool = False
    ) -> AtualizarResult: ...
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

    def __init__(self, conteudo: VisualType) -> None:
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
            nome = validar_nome_repo(self.query_one("#cadastro-nome", Input).value)
            sistema_id = validar_sistema_id(
                self.query_one("#cadastro-sistema", Input).value
            )
        except MotorError as erro:
            self.query_one("#cadastro-erro", Static).update(str(erro))
            return
        self.dismiss((nome, sistema_id))


class AbortarModal(ModalScreen[bool]):
    """Confirmacao do abort do cherry-pick.

    Unico ponto da TUI que pergunta antes de agir: `git cherry-pick --abort`
    joga fora a resolucao de conflito que esta na worktree, e ela nao esta
    commitada em lugar nenhum — um `a` sem querer apagaria o trabalho manual do
    operador. O resto do app so escreve o que da para refazer sozinho.
    """

    BINDINGS = [("escape", "recusar", "Cancelar")]
    DEFAULT_CSS = """
    AbortarModal { align: center middle; }
    AbortarModal > Vertical {
        width: 60;
        height: auto;
        padding: 1 2;
        border: round $error;
        background: $surface;
    }
    #abortar-botoes { height: auto; align-horizontal: right; padding-top: 1; }
    #abortar-botoes Button { margin-left: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical() as caixa:
            caixa.border_title = "Abortar cherry-pick"
            caixa.border_subtitle = "esc para cancelar"
            yield Static(
                "A resolução de conflito que está na worktree será descartada."
            )
            with Horizontal(id="abortar-botoes"):
                yield Button("Cancelar", id="abortar-nao")
                yield Button("Abortar", id="abortar-sim", variant="error")

    def action_recusar(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, evento: Button.Pressed) -> None:
        self.dismiss(evento.button.id == "abortar-sim")


class ConfirmarModal(ModalScreen[bool]):
    """O lote na tela antes do primeiro cherry-pick.

    E o que substitui a exigencia de rodar um Verificar antes do Atualizar. A
    exigencia nao protegia nada: o `atualizar` do motor chama o `verificar` ele
    mesmo e recalcula o lote do git na hora, entao o status da tela anterior
    nunca era o que embarcava. Aqui o status mostrado e o da mesma varredura que
    vai alimentar os picks, e a decisao acontece antes de qualquer escrita.

    Mesma tabela do Verificar, de proposito: as secoes vermelhas (ambiguas, sem
    commits, commits sumidos, suspeitos) tem de estar na frente do operador no
    momento em que ele decide, nao num modal que ele fechou dois cliques atras.
    """

    BINDINGS = [("escape", "recusar", "Cancelar")]
    DEFAULT_CSS = """
    ConfirmarModal { align: center middle; }
    ConfirmarModal > Vertical {
        width: 90%;
        height: 80%;
        padding: 1 2;
        border: round $warning;
        background: $surface;
    }
    #confirmar-aviso { height: auto; padding-top: 1; color: $text-muted; }
    #confirmar-botoes { height: auto; align-horizontal: right; padding-top: 1; }
    #confirmar-botoes Button { margin-left: 1; }
    """

    def __init__(self, status: VersionStatus, versao: str) -> None:
        super().__init__()
        self._status = status
        self._versao = versao

    def compose(self) -> ComposeResult:
        with Vertical() as caixa:
            caixa.border_title = f"Atualizar {self._versao}"
            caixa.border_subtitle = "esc para cancelar"
            with VerticalScroll():
                yield Static(renderizar_status(self._status), id="modal-conteudo")
            yield Static(
                f"{len(self._status.faltantes)} commits entram na branch "
                f"{self._versao} e são publicados na origin.",
                id="confirmar-aviso",
            )
            with Horizontal(id="confirmar-botoes"):
                yield Button("Cancelar", id="confirmar-nao")
                yield Button(
                    "Aplicar e publicar", id="confirmar-sim", variant="warning"
                )

    def action_recusar(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, evento: Button.Pressed) -> None:
        self.dismiss(evento.button.id == "confirmar-sim")


def sugerir_versoes(existentes: list[str]) -> list[str]:
    """Os tres proximos numeros a partir da mais alta que existe, um por tipo.

    Ordem de uso, nao de magnitude: cliente e o caso do dia a dia, fechada e o
    corte raro. Lista vazia (repo sem nenhuma versao) nao sugere nada — a
    primeira versao de um repo e digitada, porque nao ha de onde derivar.
    """
    if not existentes:
        return []
    x, y, z = max(chave(numero) for numero in existentes)
    return [f"{x}.{y}.{z + 1}", f"{x}.{y + 1}.0", f"{x + 1}.0.0"]


class CriarModal(ModalScreen["str | None"]):
    """Numero da versao nova, com o tipo e a base que ele resolveria.

    A prévia e o ponto: numero certo com base errada e o erro caro deste
    comando, porque a base entra em `versao.base_commit` e fica definitiva. E
    ela nao custa git nenhum — `inferir_tipo` e `inferir_base` sao funcoes puras
    e a lista de versoes existentes o app ja carregou para o Select.

    Este modal e a confirmacao do `criar`: nao ha previa do lote de commits para
    mostrar depois, porque o `verificar` de dentro do `atualizar` precisa da
    branch, e a branch e justamente o que ainda nao existe.
    """

    BINDINGS = [("escape", "cancelar", "Cancelar")]
    DEFAULT_CSS = """
    CriarModal { align: center middle; }
    CriarModal > Vertical {
        width: 68;
        height: auto;
        padding: 1 2;
        border: round $warning;
        background: $surface;
    }
    CriarModal .rotulo { height: auto; color: $text-muted; }
    #criar-sugestoes { height: auto; padding-top: 1; }
    #criar-sugestoes Button { width: 20; margin-right: 1; }
    #criar-previa { height: auto; padding-top: 1; }
    #criar-erro { height: auto; color: $error; }
    #criar-aviso { height: auto; padding-top: 1; color: $text-muted; }
    #criar-botoes { height: auto; align-horizontal: right; padding-top: 1; }
    #criar-botoes Button { margin-left: 1; }
    """

    def __init__(self, existentes: list[str]) -> None:
        super().__init__()
        self._existentes = existentes
        self._sugestoes = sugerir_versoes(existentes)

    def compose(self) -> ComposeResult:
        with Vertical() as caixa:
            caixa.border_title = "Nova versão"
            caixa.border_subtitle = "esc para cancelar"
            yield Static("número", classes="rotulo")
            yield Input(placeholder="X.Y.Z", id="criar-numero")
            with Horizontal(id="criar-sugestoes"):
                for indice, numero in enumerate(self._sugestoes):
                    tipo = inferir_tipo(numero).name.lower()
                    yield Button(f"{numero} · {tipo}", id=f"criar-sugestao-{indice}")
            yield Static(id="criar-previa")
            yield Static(id="criar-erro")
            yield Static(
                "A branch sai da base, o VERSAO é commitado e o lote vai para a "
                "origin.",
                id="criar-aviso",
            )
            with Horizontal(id="criar-botoes"):
                yield Button("Cancelar", id="criar-cancelar")
                yield Button("Criar e publicar", id="criar-ok", variant="warning")

    def action_cancelar(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, evento: Button.Pressed) -> None:
        id_botao = evento.button.id or ""
        if id_botao.startswith("criar-sugestao-"):
            # Escreve no campo em vez de submeter direto: a sugestao e um atalho
            # de digitacao, e o operador ainda ve tipo e base antes do sim.
            self.query_one("#criar-numero", Input).value = self._sugestoes[
                int(id_botao.rsplit("-", 1)[1])
            ]
            return
        if id_botao == "criar-ok":
            self._confirmar()
            return
        self.dismiss(None)

    def on_input_changed(self, evento: Input.Changed) -> None:
        previa, erro = self._avaliar(evento.value)
        self.query_one("#criar-previa", Static).update(previa)
        self.query_one("#criar-erro", Static).update(erro)

    def on_input_submitted(self, evento: Input.Submitted) -> None:
        self._confirmar()

    def _avaliar(self, numero: str) -> tuple[str, str]:
        """(previa, erro) do que esta digitado. Campo vazio nao e erro ainda."""
        numero = numero.strip()
        if not numero:
            return "", ""
        try:
            tipo = inferir_tipo(numero)
        except MotorError as erro:
            return "", str(erro)
        if numero in self._existentes:
            return "", f"versao {numero} ja existe - use Atualizar"
        try:
            base = inferir_base(numero, self._existentes)
        except MotorError as erro:
            return "", str(erro)
        return f"{tipo.name.lower()} · base {base}", ""

    def _confirmar(self) -> None:
        numero = self.query_one("#criar-numero", Input).value.strip()
        previa, erro = self._avaliar(numero)
        if erro or not previa:
            self.query_one("#criar-erro", Static).update(
                erro or "informe o número da versão"
            )
            return
        self.dismiss(numero)


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
        ("a", "abortar", "Abortar"),
        ("c", "criar", "Nova versão"),
        ("n", "cadastrar", "Cadastrar repo"),
    ]
    CSS = """
    #barra { height: auto; padding: 1; align-vertical: middle; }
    .rotulo { width: auto; height: auto; padding: 1 1 0 0; color: $text-muted; }
    #separador { width: 3; height: auto; padding-top: 1; color: $text-muted; text-align: center; }
    #repo { width: 2fr; max-width: 30; }
    #versao { width: 1fr; max-width: 30; }
    #verificar, #atualizar { width: 18; margin-left: 1; }
    #abortar { display: none; width: 13; margin-left: 1; }
    #auditar { display: none; height: auto; margin: 0 1; }
    #conteudo { height: 1fr; }
    #resultado-scroll { height: 1fr; padding: 1 2; }
    #resultado { width: 1fr; }
    #resultado.aviso { height: 100%; content-align: center middle; }
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
        continuar_repo: ContinueRunner | None = None,
        abortar_repo: AbortRunner | None = None,
        consultar_versao: ConsultaRunner | None = None,
        registrar_repo: RepoRegistrar | None = None,
        criar_repo: CriarRunner | None = None,
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
        self._continuar = continuar_repo
        self._abortar = abortar_repo
        self._consultar = consultar_versao
        self._registrar = registrar_repo
        self._criar = criar_repo
        self._repo: RepoOption | None = None
        self._versao: VersionOption | None = None
        self._ocupado = False
        self._tem_repos = False
        self._tem_versoes = False
        self._geracao_versoes = 0
        self._bloqueado = False
        # Pick pendente que nao deixou alteracao: espera confirmacao explicita
        # do operador, nao o mesmo clique de "Continuar".
        self._vazio_pendente = False
        self._chamados_consultados: list[ChamadoConsultado] = []
        # Numeros ja existentes, para as sugestoes e a recusa do CriarModal. Sai
        # daqui e nao do Select porque o `criar` os precisa com o modal aberto,
        # quando ler o widget seria ler a tela em vez do estado.
        self._versoes: list[VersionOption] = []

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
            yield Button("Abortar", id="abortar", variant="error")
        with Container(id="conteudo"):
            with VerticalScroll(id="resultado-scroll"):
                yield Static(
                    "Selecione um repositório.", id="resultado", classes="aviso"
                )
            with Vertical(id="consulta-painel"):
                yield Static(id="consulta-resumo")
                with Horizontal(id="consulta-corpo"):
                    yield OptionList(id="consulta-chamados", compact=True)
                    with VerticalScroll(id="consulta-detalhe-scroll"):
                        yield Static(id="consulta-detalhe")
        yield Footer()

    def on_mount(self) -> None:
        self._ocupar_resultado()
        self._bloquear(True)
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

    def _exibir_resultado(self, conteudo: VisualType) -> Static:
        self.query_one("#consulta-painel").display = False
        self.query_one("#resultado-scroll").display = True
        resultado = self.query_one("#resultado", Static)
        # Aviso de uma linha fica centrado no painel vazio; conteudo de verdade
        # (tabela, Panel de erro) continua no canto de cima, alinhado a esquerda.
        resultado.set_class(isinstance(conteudo, (str, Text)), "aviso")
        resultado.update(conteudo)
        return resultado

    def _apresentar(self, conteudo: VisualType, *, reconsultar: bool = False) -> None:
        """Resultado que o verificar/atualizar acabou de gravar no banco e
        transitorio: vai para um modal e ao fechar recarrega a lista de chamados.
        Vale tambem na primeira verificacao da versao, quando a consulta veio
        vazia e a lista ainda nao esta na tela — o snapshot que ela vai mostrar
        e justamente o que este resultado escreveu. Sem recarga pendente (erro,
        auditoria, TUI sem consulta) e sem lista, ocupa o painel.
        """
        recarrega = reconsultar and self._consultar is not None
        if not recarrega and not self.query_one("#consulta-painel").display:
            self._exibir_resultado(conteudo)
            return
        self.push_screen(
            ResultadoModal(conteudo),
            (lambda _: self._reconsultar()) if reconsultar else None,
        )

    def _ocupar_resultado(self) -> None:
        """Loading vai no scroll, nao no Static de dentro.

        O `#resultado` tem altura auto — com uma linha de texto, o cover widget
        do Textual cobre uma linha, e do PainelProgresso sobrava so a fase: o
        pulso ficava recortado fora da tela. O scroll tem `height: 1fr`, entao
        o painel aparece inteiro e centrado, igual ao da lista de chamados.
        """
        self.query_one("#resultado-scroll").loading = True

    def _ocupar_lista(self) -> bool:
        """Marca a lista de chamados como carregando, se e ela que esta na tela."""
        painel = self.query_one("#consulta-painel")
        painel.loading = painel.display
        return painel.display

    def _reconsultar(self) -> None:
        if self._repo is None or self._versao is None or self._consultar is None:
            return
        if not self._ocupar_lista():
            self._ocupar_resultado()
        self._bloquear(True)
        self.consultar_worker(self._repo, self._versao)

    def _erro(self, mensagem: str, transitorio: bool = False) -> None:
        painel = Panel(mensagem, title="Erro", style="bold red")
        if transitorio:
            self._apresentar(painel)
        else:
            self._exibir_resultado(painel)

    def _pode_atualizar(self) -> bool:
        """Atualizar depende da selecao, nao de ter rodado um Verificar antes.

        Derivado em vez de gravado num flag porque a pre-condicao que o flag
        guardava (ter um status fresco na tela) nao era pre-condicao de nada: o
        `atualizar` do motor abre chamando o `verificar`, e o lote sai dessa
        varredura, nao da anterior. O que existe no lugar e o `ConfirmarModal`,
        que mostra o lote de verdade antes do primeiro pick.

        Lote bloqueado sem runner de continuacao e o unico caso que trava o
        botao: ha cherry-pick pendente na worktree e um lote novo por cima dele
        nao passa do `use_worktree`.
        """
        if self._bloqueado and self._continuar is None:
            return False
        return bool(
            self._atualizar is not None
            and self._repo is not None
            and self._versao is not None
            and not self._versao.liberada
        )

    def _rotular_atualizacao(self, faltantes: int) -> None:
        """Contagem no rotulo e destaque, a partir do ultimo verificar.

        So cosmetica — o botao ja esta habilitado sem isto. Versao liberada (ou
        TUI sem runner de atualizacao) nao ganha contagem: o botao esta
        desabilitado, e "Atualizar · 3" em botao morto so confunde.
        """
        if not self._pode_atualizar():
            faltantes = 0
        atualizar_botao = self.query_one("#atualizar", Button)
        atualizar_botao.label = (
            f"Atualizar · {faltantes}" if faltantes else "Atualizar"
        )
        atualizar_botao.variant = "warning" if faltantes else "default"
        self.query_one("#verificar", Button).variant = (
            "default" if faltantes else "primary"
        )

    def _mostrar_resultado(self, status: VersionStatus, auditado: bool) -> None:
        # Auditoria nao persiste (verificar --auditar nao toca no snapshot):
        # recarregar a lista traria o mesmo conteudo por um round de git a mais.
        self._apresentar(
            renderizar_status(status, auditado=auditado),
            reconsultar=not auditado,
        )
        self._rotular_atualizacao(len(status.faltantes))

    def _mostrar_atualizacao(self, resultado: AtualizarResult) -> None:
        """Lote BLOCKED deixa o cherry-pick aberto na worktree: o mesmo botao
        vira "Continuar" e passa a chamar o `atualizar_continue`, em vez de
        mandar o operador para a CLI.

        VAZIO usa o mesmo mecanismo com outro rotulo: o pick tambem segue aberto,
        mas o que falta nao e resolver arquivo — e o operador dizer que a
        resolucao sem alteracao pode entrar como commit vazio. O rotulo distinto
        e a confirmacao, e por isso nao ha modal aqui: um clique em "Continuar"
        marcaria o commit como aplicado para sempre no oraculo de presenca sem o
        operador saber que assinou isso.

        Nao reabilita nada aqui — o `_bloquear(False)` do `finally` do worker
        vem depois e le o `_pode_atualizar` que este metodo acabou de firmar.
        """
        self._apresentar(renderizar_atualizacao(resultado), reconsultar=True)
        self._resetar_atualizacao()
        if resultado.status not in (AtualizarStatus.BLOCKED, AtualizarStatus.VAZIO):
            return
        self._bloqueado = True
        self._vazio_pendente = resultado.status == AtualizarStatus.VAZIO
        if self._continuar is not None:
            botao = self.query_one("#atualizar", Button)
            botao.label = "Registrar vazio" if self._vazio_pendente else "Continuar"
            botao.variant = "warning" if self._vazio_pendente else "error"
        self.query_one("#abortar", Button).display = self._abortar is not None

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
        largura_commits = max(len(str(len(chamado.commits))) for chamado in chamados)
        opcoes: list[Option] = []
        for indice, chamado in enumerate(chamados):
            rotulo, cor = rotulo_estado(chamado)
            opcoes.append(
                Option(
                    Text.assemble(
                        (f"#{chamado.chamado}", "bold"),
                        (f"  {len(chamado.commits):>{largura_commits}}", "dim"),
                        (f"  ● {rotulo}", cor),
                    ),
                    id=str(indice),
                )
            )
        lista.add_options(opcoes)
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
        # O pick pendente e da worktree daquela versao: sem limpar isto, o
        # clique seguinte retomaria o lote na versao errada.
        self._bloqueado = False
        self._vazio_pendente = False
        botao = self.query_one("#atualizar", Button)
        botao.label = "Atualizar"
        botao.variant = "default"
        self.query_one("#abortar", Button).display = False
        self.query_one("#verificar", Button).variant = "primary"

    def _falha(self, erro: Exception, transitorio: bool = False) -> None:
        if isinstance(erro, MotorError):
            self._erro(formatar_com_notas(erro), transitorio)
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
            self.query_one("#resultado-scroll").loading = False
            self.query_one("#consulta-painel").loading = False
        self.query_one("#repo", Select).disabled = ocupado or not self._tem_repos
        self.query_one("#versao", Select).disabled = ocupado or not self._tem_versoes
        self.query_one("#auditar", Checkbox).disabled = ocupado
        self.query_one("#verificar", Button).disabled = (
            ocupado or self._repo is None or self._versao is None
        )
        self.query_one("#atualizar", Button).disabled = (
            ocupado or not self._pode_atualizar()
        )
        # So a ocupacao: quem esconde o abort fora do bloqueio e o `display`.
        self.query_one("#abortar", Button).disabled = ocupado

    @work(thread=True, exclusive=True, group="repos")
    def carregar_repos_worker(self) -> None:
        try:
            opcoes = self._carregar_repos()
        except Exception as erro:
            self.call_from_thread(self._falha, erro)
            self.call_from_thread(self._bloquear, False)
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
        self._versoes = []
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
        self._ocupar_resultado()
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
        self._versoes = opcoes
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
            self._exibir_resultado(
                f"Consultando {self._repo.nome} {self._versao.numero}…"
            )
            self._ocupar_resultado()
            self._bloquear(True)
            self.consultar_worker(self._repo, self._versao)
        elif self._versao is not None and self._repo is not None:
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
        elif evento.button.id == "abortar":
            self._iniciar_abort()

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
        self._ocupar_resultado()
        self.carregar_repos_worker()

    def action_criar(self) -> None:
        if self._ocupado or self._criar is None or self._repo is None:
            return
        if not self._repo.disponivel:
            return
        self.push_screen(
            CriarModal([opcao.numero for opcao in self._versoes]), self._criar_versao
        )

    def _criar_versao(self, numero: str | None) -> None:
        if numero is None or self._criar is None or self._repo is None:
            return
        self._exibir_resultado(f"Criando {self._repo.nome} {numero}…")
        self._ocupar_resultado()
        self._bloquear(True)
        self.criar_worker(self._criar, self._repo, numero)

    @work(thread=True, exclusive=True, group="executar")
    def criar_worker(
        self, executar: CriarRunner, repo: RepoOption, numero: str
    ) -> None:
        try:
            resultado = executar(repo, numero)
        except Exception as erro:
            self.call_from_thread(self._falha, erro, True)
        else:
            self.call_from_thread(self._mostrar_criacao, numero, resultado)
        finally:
            self.call_from_thread(self._bloquear, False)

    def _mostrar_criacao(self, numero: str, resultado: AtualizarResult) -> None:
        """A versao criada passa a ser a selecionada, sem disparar o
        `_selecionar_versao`.

        Nao e conveniencia: o `criar` termina chamando o `atualizar`, entao o
        lote pode voltar BLOCKED ou VAZIO, e retomar o pick depende de
        `self._versao` apontar para a versao nova. Deixar o Select disparar a
        selecao chamaria `_resetar_atualizacao`, que apaga exatamente o bloqueio
        que o `_mostrar_atualizacao` esta a um passo de estabelecer.
        """
        nova = VersionOption(numero=numero, liberada=False)
        self._versoes = sorted(
            [nova, *self._versoes], key=lambda o: chave(o.numero), reverse=True
        )
        select = self.query_one("#versao", Select)
        with self.prevent(Select.Changed):
            select.set_options([(opcao.numero, opcao) for opcao in self._versoes])
            select.query_one(OptionList).disable_option_at_index(0)
            select.value = nova
        self._versao = nova
        self._tem_versoes = True
        auditoria = self.query_one("#auditar", Checkbox)
        auditoria.value = False
        auditoria.display = False
        self._mostrar_atualizacao(resultado)

    def action_verificar(self) -> None:
        self._iniciar_verificacao()

    def action_atualizar(self) -> None:
        self._iniciar_atualizacao()

    def action_abortar(self) -> None:
        self._iniciar_abort()

    def _iniciar_verificacao(self) -> None:
        if self._ocupado:
            return
        if self._repo is None or self._versao is None:
            return
        self._resetar_atualizacao()
        if not self._ocupar_lista():
            self._exibir_resultado(
                f"Verificando {self._repo.nome} {self._versao.numero}…"
            )
            self._ocupar_resultado()
        self._bloquear(True)
        self.executar_worker(
            self._repo,
            self._versao,
            self.query_one("#auditar", Checkbox).value,
        )

    def _iniciar_atualizacao(self) -> None:
        """Verifica primeiro, mostra o lote, aplica so depois do sim.

        A verificacao aqui nao e a que o motor usa — o `atualizar` roda a sua
        propria — e nao ha promessa de que as duas vejam a mesma coisa: sao duas
        varreduras separadas, e nada impede um push na origem no meio. E uma
        previa para decidir, nao um contrato. O que garante que nada ilegitimo
        embarca continua sendo o `verificar` de dentro do motor.
        """
        if self._ocupado or not self._pode_atualizar():
            return
        if self._repo is None or self._versao is None:
            return
        if self._bloqueado:
            # Continuar: o lote ja esta aberto na worktree e o operador acabou de
            # resolver o conflito na mao. Previa aqui nao muda decisao nenhuma e
            # custaria uma varredura de git inteira antes de retomar o pick.
            self._rodar_atualizacao()
            return
        if not self._ocupar_lista():
            self._exibir_resultado(
                f"Verificando {self._repo.nome} {self._versao.numero}…"
            )
            self._ocupar_resultado()
        self._bloquear(True)
        self.executar_worker(self._repo, self._versao, False, confirmar=True)

    def _confirmar_atualizacao(self, status: VersionStatus) -> None:
        """Previa do lote entre o verificar e o primeiro cherry-pick.

        Lote vazio nao pergunta nada: cai no caminho de resultado normal, que e
        exatamente o que o Verificar mostraria. `suspeitos_conteudo` tambem nao
        pergunta — o motor recusa esse lote na entrada (`RecusaDeInvariante`), e
        um sim aqui so gastaria a varredura para levar uma recusa.
        """
        self._rotular_atualizacao(len(status.faltantes))
        if not status.faltantes or status.suspeitos_conteudo:
            self._mostrar_resultado(status, False)
            return
        self.push_screen(
            ConfirmarModal(status, self._versao.numero if self._versao else ""),
            partial(self._atualizacao_confirmada, status),
        )

    def _atualizacao_confirmada(
        self, status: VersionStatus, confirmado: bool | None
    ) -> None:
        if confirmado:
            self._rodar_atualizacao()
            return
        # Cancelar nao desfaz o verificar: ele ja regravou o snapshot, e a lista
        # atras do modal esta velha. Sem modal de resultado por cima — o
        # operador acabou de fechar essa mesma tabela.
        if self._consultar is not None:
            self._reconsultar()
        else:
            self._exibir_resultado(renderizar_status(status))

    def _rodar_atualizacao(self) -> None:
        executar: UpdateRunner | None
        if self._vazio_pendente and self._continuar is not None:
            # O clique em "Registrar vazio" E a confirmacao que o
            # `atualizar_continue` exige; sem ela ele so devolveria VAZIO de novo.
            executar = partial(self._continuar, allow_empty=True)
        elif self._bloqueado:
            executar = self._continuar
        else:
            executar = self._atualizar
        if executar is None or self._repo is None or self._versao is None:
            return
        self._ocupar_lista()
        self._bloquear(True)
        self.atualizar_worker(executar, self._repo, self._versao)

    def _iniciar_abort(self) -> None:
        if self._ocupado or not self._bloqueado or self._abortar is None:
            return
        self.push_screen(AbortarModal(), self._abortar_confirmado)

    def _abortar_confirmado(self, confirmado: bool | None) -> None:
        if not confirmado or self._abortar is None:
            return
        if self._repo is None or self._versao is None:
            return
        self._ocupar_lista()
        self._bloquear(True)
        self.abortar_worker(self._abortar, self._repo, self._versao)

    @work(thread=True, exclusive=True, group="executar")
    def executar_worker(
        self,
        repo: RepoOption,
        versao: VersionOption,
        auditar: bool,
        confirmar: bool = False,
    ) -> None:
        """Uma verificacao, dois destinos: tela de resultado ou previa do lote.

        Mesmo worker (mesmo grupo exclusivo, mesmo caminho de erro) porque a
        varredura e a mesma. Verificacao que falha no caminho `confirmar` cai no
        `_falha` e nao pergunta nada — sem lote na tela nao ha o que confirmar.
        """
        try:
            status = self._executar(repo, versao.numero, auditar)
        except Exception as erro:
            self.call_from_thread(self._falha, erro, True)
        else:
            if confirmar:
                self.call_from_thread(self._confirmar_atualizacao, status)
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

    def _mostrar_abort(self) -> None:
        self._apresentar(
            Text("● Atualização abortada", style="bold yellow"), reconsultar=True
        )
        self._resetar_atualizacao()

    @work(thread=True, exclusive=True, group="executar")
    def abortar_worker(
        self, executar: AbortRunner, repo: RepoOption, versao: VersionOption
    ) -> None:
        try:
            executar(repo, versao.numero)
        except Exception as erro:
            self.call_from_thread(self._falha, erro, True)
        else:
            self.call_from_thread(self._mostrar_abort)
        finally:
            self.call_from_thread(self._bloquear, False)

    @work(thread=True, exclusive=True, group="executar")
    def atualizar_worker(
        self, executar: UpdateRunner, repo: RepoOption, versao: VersionOption
    ) -> None:
        try:
            resultado = executar(repo, versao.numero)
        except Exception as erro:
            self.call_from_thread(self._falha, erro, True)
        else:
            self.call_from_thread(self._mostrar_atualizacao, resultado)
        finally:
            self.call_from_thread(self._bloquear, False)


def descobrir_repos(
    estado: EstadoRepo, projects_dir: str, *, progresso: RelatorProgresso = silencioso
) -> list[RepoOption]:
    progresso(Progresso("lendo os repos cadastrados"))
    repos = estado.listar_repos()
    if not projects_dir:
        return [RepoOption(nome=repo.nome, caminho=None) for repo in repos]
    canonicos = {repo.nome: repo for repo in repos}
    encontrados: dict[str, Path] = {}
    raiz = Path(projects_dir)

    if raiz.is_dir():
        # Conta os diretorios porque a varredura pode consultar o banco em cada
        # um (`resolver_repo` de nome que nao esta na lista canonica).
        candidatos = sorted(raiz.iterdir(), key=lambda item: item.name)
        for indice, caminho in enumerate(candidatos, start=1):
            progresso(Progresso("procurando os checkouts", indice, len(candidatos)))
            if not caminho.is_dir() or not (caminho / ".git").exists():
                continue
            if caminho.name in canonicos:
                info = canonicos[caminho.name]
            else:
                try:
                    info = estado.resolver_repo(caminho.name)
                except NaoEncontrado:
                    continue
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


def _repos_do_ambiente(
    *, progresso: RelatorProgresso = silencioso
) -> list[RepoOption]:
    with abrir_sessao() as sessao:
        return descobrir_repos(
            PostgresEstado(sessao=sessao),
            os.environ.get("PROJECTS_DIR", ""),
            progresso=progresso,
        )


def _registrar_no_banco(nome: str, sistema_id: int) -> None:
    with abrir_sessao() as sessao:
        PostgresEstado(sessao=sessao).registrar_repo(nome, sistema_id)


def _versoes_do_repo(
    repo: RepoOption, *, progresso: RelatorProgresso = silencioso
) -> list[VersionOption]:
    if repo.caminho is None:
        return []
    return descobrir_versoes(
        new_git_subprocess(repo.caminho, progresso=progresso), progresso=progresso
    )


def _deps_do_repo(
    repo: RepoOption, sessao: Session, progresso: RelatorProgresso = silencioso
) -> Deps:
    if repo.caminho is None:
        raise NaoEncontrado("checkout local não encontrado")
    # Sem flags: token e email do Bitbucket saem do ambiente dentro do
    # montar_deps, e a fonte de tasks e sempre o Tickio.
    return montar_deps(repo.caminho, sessao, progresso=progresso)


def _verificar_repo(
    repo: RepoOption,
    versao: str,
    auditar: bool,
    *,
    progresso: RelatorProgresso = silencioso,
) -> VersionStatus:
    with abrir_sessao() as sessao:
        deps = _deps_do_repo(repo, sessao, progresso)
        return verificar(deps, versao, auditar=auditar)


def _atualizar_repo(
    repo: RepoOption, versao: str, *, progresso: RelatorProgresso = silencioso
) -> AtualizarResult:
    with abrir_sessao() as sessao:
        return atualizar(_deps_do_repo(repo, sessao, progresso), versao)


def _continuar_repo(
    repo: RepoOption,
    versao: str,
    *,
    allow_empty: bool = False,
    progresso: RelatorProgresso = silencioso,
) -> AtualizarResult:
    with abrir_sessao() as sessao:
        return atualizar_continue(
            _deps_do_repo(repo, sessao, progresso), versao, allow_empty=allow_empty
        )


def _abortar_repo(
    repo: RepoOption, versao: str, *, progresso: RelatorProgresso = silencioso
) -> None:
    with abrir_sessao() as sessao:
        atualizar_abort(_deps_do_repo(repo, sessao, progresso), versao)


def _criar_repo(
    repo: RepoOption, versao: str, *, progresso: RelatorProgresso = silencioso
) -> AtualizarResult:
    with abrir_sessao() as sessao:
        return criar(_deps_do_repo(repo, sessao, progresso), versao)


def _consultar_repo(
    repo: RepoOption, versao: str, *, progresso: RelatorProgresso = silencioso
) -> list[ChamadoConsultado]:
    with abrir_sessao() as sessao:
        return consultar(_deps_do_repo(repo, sessao, progresso), versao)


def run_tui() -> None:
    # O relator entra por `partial`, nao na assinatura dos runners que a TUI
    # chama: assim os aliases (VerifyRunner e companhia) e os doubles dos testes
    # seguem com a mesma aridade, e quem injeta runner nao precisa saber que
    # progresso existe.
    slot = SlotProgresso()
    MotorTUI(
        partial(_repos_do_ambiente, progresso=slot.relatar),
        partial(_versoes_do_repo, progresso=slot.relatar),
        partial(_verificar_repo, progresso=slot.relatar),
        partial(_atualizar_repo, progresso=slot.relatar),
        partial(_continuar_repo, progresso=slot.relatar),
        partial(_abortar_repo, progresso=slot.relatar),
        partial(_consultar_repo, progresso=slot.relatar),
        _registrar_no_banco,
        partial(_criar_repo, progresso=slot.relatar),
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


def _commits_agrupados(
    commits: list[CommitRef], estados: dict[str, str]
) -> Group | None:
    if not commits:
        return None
    tabelas: list[Table] = []
    for chamado, itens in agrupar_por_chamado(commits).items():
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


def rotulo_estado(chamado: ChamadoConsultado) -> tuple[str, str]:
    """Rotulo e cor do estado de um chamado do snapshot.

    O estado gravado so tem dois valores: chamado sem nenhum commit achado cai
    em "pendente" igual a quem tem commit esperando cherry-pick. O verificar
    distingue os dois (`VersionStatus.sem_commits`); aqui a lista tem a mesma
    evidencia na mao — lista de commits vazia — e nao deve mostrar menos.
    """
    if chamado.estado == "aplicado":
        return "aplicado", "green"
    if not chamado.commits:
        return "sem commits", "red"
    return "pendente", "yellow"


def renderizar_chamado(chamado: ChamadoConsultado) -> Group:
    quantidade = len(chamado.commits)
    rotulo, cor = rotulo_estado(chamado)
    cabecalho = Text.assemble(
        (f"#{chamado.chamado}", "bold"),
        (f"  ·  {quantidade} commit{'s' if quantidade != 1 else ''}", "dim"),
        (f"  ·  {rotulo.upper()}", f"bold {cor}"),
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
    for commit in sorted(
        chamado.commits, key=lambda item: item.commit_date, reverse=True
    ):
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
    vazia = resultado.status == AtualizarStatus.VAZIO
    if bloqueada:
        cabecalho = Text("● Atualização bloqueada", style="bold red")
    elif vazia:
        cabecalho = Text("● Resolução sem alteração", style="bold yellow")
    else:
        cabecalho = Text("● Atualização concluída", style="bold green")
    partes: list[RenderableType] = [cabecalho]
    aplicados = _commits_agrupados(
        resultado.aplicados,
        {commit.hash_origem: "APLICADO" for commit in resultado.aplicados},
    )
    if aplicados is not None:
        partes.append(aplicados)
    elif not bloqueada and not vazia:
        partes.append(Text("Branch já estava atualizada.", style="dim"))
    if resultado.vazios:
        hashes = ", ".join(commit.hash_origem[:8] for commit in resultado.vazios)
        partes.append(
            Text(
                f"{len(resultado.vazios)} commits sem alteração no alvo, "
                f"registrados como commit vazio: {hashes}",
                style="yellow",
            )
        )
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
                "Resolva os arquivos e retome em Continuar (u), "
                "ou descarte em Abortar (a).",
                style="bold yellow",
            )
        )
    if vazia:
        partes.append(Text(f"Commit: {resultado.blocked_commit[:8]}"))
        partes.append(
            Text(
                "A resolução não deixou alteração nenhuma no alvo. "
                "Registrar vazio (u) entra com um commit vazio, com o trailer -x; "
                "Abortar (a) descarta o commit.",
                style="bold yellow",
            )
        )
    if resultado.status_versao is not None:
        alertas = _alertas(resultado.status_versao)
        if alertas is not None:
            partes.append(alertas)
    return Group(*partes)


def renderizar_status(status: VersionStatus, auditado: bool = False) -> Group:
    partes: list[RenderableType] = []
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
