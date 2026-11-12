"""Modal da TUI que edita o `config.toml` central pelo núcleo de `config_edicao`."""

from __future__ import annotations

import hashlib
from typing import ClassVar, Final

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from motor.config import TABELA_AMBIENTE, Backend, VarAmbiente
from motor.config_edicao import (
    ORIGEM_MOTOR,
    AcaoAlteracao,
    Alteracao,
    Campo,
    ConfigEditavel,
    Escopo,
    TipoCampo,
    ValorLido,
    gravar,
)
from motor.errors import ErroDeEntrada, RecusaDeInvariante, formatar_com_notas

Escalar = str | int | bool | None
ChaveForm = tuple[str | None, str | None, str]

MSG_DEFINIDO = "definido"
MSG_NAO_DEFINIDO = "não definido"
MSG_SOMENTE_LEITURA = "somente leitura"
ABA_REPOS = "aba-repos"
TEXTO_TRUE = "true"
TEXTO_FALSE = "false"
TIPO_INPUT_INTEIRO: Final = "integer"
TIPO_INPUT_TEXTO: Final = "text"
_V_BACKEND: Final = VarAmbiente.DATABASE_BACKEND
_CHAVE_BACKEND: Final = (None, TABELA_AMBIENTE, _V_BACKEND)


def _chave_de(v: ValorLido) -> ChaveForm:
    return (v.repo, v.tabela, v.chave)


def _vazio(valor: Escalar) -> bool:
    return valor is None or valor == ""


def alteracoes_do_formulario(
    original: ConfigEditavel,
    valores: dict[ChaveForm, Escalar],
    repos_criados: list[str],
    repos_removidos: list[str],
) -> list[Alteracao]:
    """Mesma regra de `alteracoesDe` na web; segredo: `None` apaga, `""` não toca."""
    lidos = {_chave_de(v): v for v in original.valores}
    segredos = {(c.tabela, c.chave) for c in original.campos if c.segredo}
    criar = [Alteracao(AcaoAlteracao.CRIAR_REPO, repo) for repo in repos_criados]
    chaves: list[Alteracao] = []
    for (repo, tabela, chave), novo in valores.items():
        lido = lidos.get((repo, tabela, chave))
        if repo in repos_removidos or (lido and not lido.editavel):
            continue
        base = (repo, tabela, chave)
        if (tabela, chave) in segredos:
            if novo is None:
                if lido and lido.definido:
                    chaves.append(Alteracao(AcaoAlteracao.REMOVER, *base))
            elif novo != "":
                chaves.append(Alteracao(AcaoAlteracao.DEFINIR, *base, novo))
        elif _vazio(novo):
            if lido and lido.definido:
                chaves.append(Alteracao(AcaoAlteracao.REMOVER, *base))
        elif lido is None or str(novo) != str(lido.valor):
            chaves.append(Alteracao(AcaoAlteracao.DEFINIR, *base, novo))
    remover = [
        Alteracao(AcaoAlteracao.REMOVER_REPO, repo)
        for repo in repos_removidos
        if repo not in repos_criados
    ]
    return [*criar, *chaves, *remover]


def converter_texto(texto: str, lido: ValorLido | None, inteiro: bool) -> Escalar:
    """Texto do Input no tipo TOML do valor lido; texto inválido para o tipo é erro."""
    if texto == "":
        return texto
    original = None if lido is None else lido.valor
    try:
        if isinstance(original, bool):
            booleano = texto.lower()
            if booleano not in (TEXTO_TRUE, TEXTO_FALSE):
                raise ValueError(texto)
            return booleano == TEXTO_TRUE
        if inteiro or isinstance(original, int):
            return int(texto)
    except ValueError:
        raise ErroDeEntrada(f"valor inválido: {texto!r}") from None
    return texto


class ConfigModal(ModalScreen[bool]):
    """Edita a config central; devolve `True` se gravou."""

    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancelar", "Cancelar")]
    DEFAULT_CSS = """
    ConfigModal { align: center middle; }
    ConfigModal > Vertical {
        width: 90%;
        height: 90%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    ConfigModal TabbedContent { height: 1fr; }
    ConfigModal TabPane { padding: 0 1; height: 1fr; }
    ConfigModal .novo-repo { height: auto; }
    ConfigModal #novo-repo { width: 1fr; }
    ConfigModal #criar-repo { width: 18; }
    ConfigModal .repo { height: auto; border: round $primary-darken-2; padding: 0 1; }
    ConfigModal #config-botoes { height: auto; align-horizontal: right; padding-top: 1; }
    ConfigModal #config-botoes Button { margin-left: 1; }
    """

    def __init__(self, config: ConfigEditavel) -> None:
        super().__init__()
        self._config = config
        self._entradas: dict[ChaveForm, Input | Select[str]] = {}
        self._apagar: dict[ChaveForm, Checkbox] = {}
        self._criados: list[str] = []
        self._removidos: list[str] = []
        self._containers: dict[str, Widget] = {}
        self._lidos = {_chave_de(v): v for v in config.valores}
        self._do_backend: list[tuple[Backend, list[Widget]]] = []

    @staticmethod
    def id_de(chave: ChaveForm) -> str:
        return "campo-" + hashlib.sha1(repr(chave).encode()).hexdigest()[:12]

    def compose(self) -> ComposeResult:
        cfg = self._config
        with Vertical():
            with TabbedContent():
                with TabPane("Geral"):
                    yield VerticalScroll(*self._campos_de(Escopo.GERAL, None, True))
                with TabPane("Repos", id=ABA_REPOS):
                    with VerticalScroll(id="repos-lista"):
                        for nome in cfg.repos:
                            yield self._container_do_repo(nome)
                    with Horizontal(classes="novo-repo"):
                        yield Input(placeholder="nome do novo repo", id="novo-repo")
                        yield Button("Criar repo", id="criar-repo")
                with TabPane("Ambiente"):
                    yield VerticalScroll(*self._campos_de(Escopo.AMBIENTE, None, True))
                if any(c.origem != ORIGEM_MOTOR for c in cfg.campos):
                    with TabPane("Plugins"):
                        yield VerticalScroll(
                            *self._campos_de(Escopo.GERAL, None, False),
                            *self._campos_de(Escopo.AMBIENTE, None, False),
                        )
            with Horizontal(id="config-botoes"):
                yield Button("Cancelar", id="cancelar")
                yield Button("Salvar", id="salvar", variant="primary")

    def _campos_de(self, escopo: Escopo, repo: str | None, motor: bool) -> list[Widget]:
        """Campos do escopo (do motor ou de plugin) mais as chaves livres dele."""
        campos = [
            c
            for c in self._config.campos
            if c.escopo == escopo and (c.origem == ORIGEM_MOTOR) == motor
        ]
        conhecidos = {(c.tabela, c.chave) for c in self._config.campos}
        if motor and repo is None:
            campos += [
                self._campo_livre(v)
                for v in self._config.valores
                if v.repo is None
                and (v.tabela, v.chave) not in conhecidos
                and (v.tabela == TABELA_AMBIENTE) == (escopo == Escopo.AMBIENTE)
            ]
        if motor and repo is not None and escopo == Escopo.REPO:
            campos += [
                self._campo_livre(v)
                for v in self._config.valores
                if v.repo == repo and (v.tabela, v.chave) not in conhecidos
            ]
        widgets: list[Widget] = []
        for campo in campos:
            widgets += self._widgets_do_campo(repo, campo)
        return widgets

    @staticmethod
    def _campo_livre(v: ValorLido) -> Campo:
        escopo = Escopo.AMBIENTE if v.tabela == TABELA_AMBIENTE else Escopo.GERAL
        return Campo(escopo, v.tabela, v.chave, TipoCampo.TEXTO, v.chave)

    def _widgets_do_campo(self, repo: str | None, campo: Campo) -> list[Widget]:
        widgets = self._widgets_sem_backend(repo, campo)
        if campo.backend is not None:
            self._do_backend.append((campo.backend, widgets))
        return widgets

    def _widgets_sem_backend(self, repo: str | None, campo: Campo) -> list[Widget]:
        chave = (repo, campo.tabela, campo.chave)
        lido = self._lidos.get(chave)
        herdado = self._lidos.get((None, campo.tabela, campo.chave)) if repo else None
        dica = "" if herdado is None or herdado.valor is None else str(herdado.valor)
        # Com valor herdado do topo, o padrão do motor não vale: a dica mostra o herdado.
        padrao = "" if campo.padrao is None or dica else f" (padrão: {campo.padrao})"
        rotulo = Label(campo.rotulo + padrao, classes="rotulo", markup=False)
        if lido is not None and not lido.editavel:
            return [rotulo, Static(f"({MSG_SOMENTE_LEITURA})")]
        if campo.segredo:
            return self._widgets_do_segredo(chave, campo, lido, rotulo)
        atual = None if lido is None or lido.valor is None else lido.valor
        entrada: Input | Select[str]
        if campo.tipo == TipoCampo.ESCOLHA:
            opcoes = list(campo.opcoes)
            if isinstance(atual, str) and atual not in opcoes:
                opcoes.append(atual)
            entrada = Select(
                [(o, o) for o in opcoes],
                value=atual if isinstance(atual, str) else Select.NULL,
                prompt=dica or "Select",
                id=self.id_de(chave),
            )
        else:
            entrada = Input(
                "" if atual is None else str(atual),
                placeholder=dica,
                type=TIPO_INPUT_INTEIRO
                if campo.tipo == TipoCampo.INTEIRO
                else TIPO_INPUT_TEXTO,
                id=self.id_de(chave),
            )
        self._entradas[chave] = entrada
        return [rotulo, entrada]

    def _widgets_do_segredo(
        self, chave: ChaveForm, campo: Campo, lido: ValorLido | None, rotulo: Label
    ) -> list[Widget]:
        definido = lido is not None and lido.definido
        entrada = Input(
            password=True,
            placeholder=MSG_DEFINIDO if definido else MSG_NAO_DEFINIDO,
            id=self.id_de(chave),
        )
        self._entradas[chave] = entrada
        widgets: list[Widget] = [rotulo, entrada]
        if definido:
            apagar = Checkbox("apagar", id=self.id_de(chave) + "-apagar")
            self._apagar[chave] = apagar
            widgets.append(apagar)
        return widgets

    def _container_do_repo(self, nome: str) -> Widget:
        campos = [
            widget
            for escopo in (Escopo.REPO, Escopo.GERAL)
            for motor in (True, False)
            for widget in self._campos_de(escopo, nome, motor)
        ]
        botao = Button("Remover repo", name=nome, classes="remover-repo")
        container = Vertical(Label(f"[b]{nome}[/b]"), *campos, botao)
        container.add_class("repo")
        self._containers[nome] = container
        return container

    def on_mount(self) -> None:
        self._mostrar_do_backend()

    def on_select_changed(self, evento: Select.Changed) -> None:
        if evento.select is self._entradas.get(_CHAVE_BACKEND):
            self._mostrar_do_backend()

    def _mostrar_do_backend(self) -> None:
        """Campos de banco só do backend escolhido; sem escolha, o padrão."""
        entrada = self._entradas.get(_CHAVE_BACKEND)
        escolhido = None if entrada is None else entrada.value
        if escolhido in (None, "", Select.NULL):
            escolhido = next(
                (c.padrao for c in self._config.campos if c.chave == _V_BACKEND),
                None,
            )
        for backend, widgets in self._do_backend:
            for widget in widgets:
                widget.display = backend == escolhido

    async def on_button_pressed(self, evento: Button.Pressed) -> None:
        evento.stop()
        botao = evento.button
        if botao.id == "salvar":
            self._salvar()
        elif botao.id == "cancelar":
            self.dismiss(False)
        elif botao.id == "criar-repo":
            await self._criar_repo()
        elif botao.name:
            await self._remover_repo(botao.name)

    def action_cancelar(self) -> None:
        self.dismiss(False)

    async def _criar_repo(self) -> None:
        campo = self.query_one("#novo-repo", Input)
        nome = campo.value.strip()
        existentes = {*self._config.repos, *self._criados} - set(self._removidos)
        if not nome or nome in existentes:
            self.app.notify("informe um nome novo para o repo", severity="error")
            return
        campo.value = ""
        if nome in self._removidos:  # volta o repo que ainda existe no arquivo
            self._removidos.remove(nome)
            self._containers[nome].display = True
            return
        self._criados.append(nome)
        await self.query_one("#repos-lista", VerticalScroll).mount(
            self._container_do_repo(nome)
        )

    async def _remover_repo(self, nome: str) -> None:
        if nome in self._criados:
            self._criados.remove(nome)
            for chave in [k for k in self._entradas if k[0] == nome]:
                del self._entradas[chave]
            await self._containers.pop(nome).remove()
            return
        self._removidos.append(nome)
        self._containers[nome].display = False

    def _valores_do_formulario(self) -> dict[ChaveForm, Escalar]:
        valores: dict[ChaveForm, Escalar] = {}
        for chave, entrada in self._entradas.items():
            apagar = self._apagar.get(chave)
            if apagar is not None and apagar.value:
                valores[chave] = None
            elif isinstance(entrada, Select):
                valores[chave] = (
                    "" if entrada.value is Select.NULL else str(entrada.value)
                )
            else:
                valores[chave] = self._converter(chave, entrada.value)
        return valores

    def _converter(self, chave: ChaveForm, texto: str) -> Escalar:
        campo_int = any(
            c.tipo == TipoCampo.INTEIRO and (c.tabela, c.chave) == chave[1:]
            for c in self._config.campos
        )
        return converter_texto(texto, self._lidos.get(chave), campo_int)

    def _salvar(self) -> None:
        try:
            alteracoes = alteracoes_do_formulario(
                self._config,
                self._valores_do_formulario(),
                self._criados,
                self._removidos,
            )
            gravar(alteracoes, self._config.versao)
        except (ErroDeEntrada, RecusaDeInvariante) as erro:
            self.app.notify(formatar_com_notas(erro), severity="error")
            return
        self.dismiss(True)
