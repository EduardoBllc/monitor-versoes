# TUI para verificar versões — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar `motor tui`, uma interface Textual em processo que lista repos do banco, descobre versões Git e apresenta `verificar()` de forma estruturada.

**Architecture:** `MotorTUI` é uma fachada do engine existente e recebe três funções de borda para carregar repos, carregar versões e verificar. Workers do Textual executam todo banco/rede/Git; funções puras descobrem opções e transformam `VersionStatus` em renderables Rich. O CLI apenas carrega o ambiente e inicia a TUI.

**Tech Stack:** Python 3.14, Textual 8.2.8, Rich, SQLAlchemy, pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-tui-verificar-design.md`

## Global Constraints

- Executar todos os comandos pelo RTK: cada segmento começa com `rtk`.
- Usar apenas a dependência `textual>=8.2.8` já instalada; não adicionar pacote.
- Manter Git, Tickio, Postgres e Textual no mesmo processo; não criar daemon/API.
- Expor somente `verificar` com Tickio; fonte manual e outras ações ficam no CLI.
- Não alterar engines nem modelos de domínio.
- Abrir sessões SQLAlchemy e executar Git/rede somente dentro dos workers.
- Repos vêm do banco; `PROJECTS_DIR` serve apenas para associar o checkout local.
- Aplicar TDD em cada tarefa e fazer um commit pequeno ao final de cada uma.

---

### Task 1: Listagem canônica de repos no estado

**Files:**
- Modify: `motor/ports.py:164-210`
- Modify: `motor/adapters/estado/fake.py:20-39`
- Modify: `motor/adapters/estado/postgres.py:32-65`
- Modify: `tests/test_estado_contrato.py:78-117`

**Interfaces:**
- Consumes: `RepoInfo(nome: str, tickio_sistema_id: int)`.
- Produces: `EstadoRepo.listar_repos() -> list[RepoInfo]`, ordenado por nome e sem aliases.

- [ ] **Step 1: Escrever o teste de contrato que falha nos dois adapters**

Adicionar depois dos testes de resolução de repo:

```python
def test_listar_repos_devolve_canonicos_em_ordem_sem_alias(estado):
    estado.registrar_repo("zzz", 99)
    estado.registrar_repo("aaa", 11)

    assert estado.listar_repos() == [
        RepoInfo(nome="aaa", tickio_sistema_id=11),
        RepoInfo(nome=REPO, tickio_sistema_id=SISTEMA_ID),
        RepoInfo(nome="zzz", tickio_sistema_id=99),
    ]
```

- [ ] **Step 2: Confirmar a falha no fake**

Run: `rtk uv run pytest 'tests/test_estado_contrato.py::test_listar_repos_devolve_canonicos_em_ordem_sem_alias[fake]' -q`

Expected: FAIL com `AttributeError: 'FakeEstado' object has no attribute 'listar_repos'`.

- [ ] **Step 3: Adicionar o contrato e a implementação fake mínima**

Em `EstadoRepo`:

```python
def listar_repos(self) -> list[RepoInfo]:
    """Repos canonicos cadastrados, em ordem de nome; aliases nao entram."""
    pass
```

Em `FakeEstado`:

```python
def listar_repos(self) -> list[RepoInfo]:
    return [self.repos[nome] for nome in sorted(self.repos)]
```

- [ ] **Step 4: Confirmar o contrato no fake**

Run: `rtk uv run pytest 'tests/test_estado_contrato.py::test_listar_repos_devolve_canonicos_em_ordem_sem_alias[fake]' -q`

Expected: PASS.

- [ ] **Step 5: Implementar a consulta Postgres pela mesma ordem**

Adicionar a `PostgresEstado`:

```python
def listar_repos(self) -> list[RepoInfo]:
    return [
        RepoInfo(nome=linha.nome, tickio_sistema_id=linha.tickio_sistema_id)
        for linha in self._scalars(select(models.Repo).order_by(models.Repo.nome))
    ]
```

- [ ] **Step 6: Rodar o contrato completo do estado**

Run: `rtk uv run pytest tests/test_estado_contrato.py -q`

Expected: fake PASS; Postgres PASS quando `DATABASE_HOST` estiver configurado, ou SKIP pela marca `integracao`.

- [ ] **Step 7: Commit**

```bash
rtk git add motor/ports.py motor/adapters/estado/fake.py motor/adapters/estado/postgres.py tests/test_estado_contrato.py
rtk git commit -m "feat(estado): lista repos cadastrados"
```

---

### Task 2: Descoberta determinística de repos e versões

**Files:**
- Create: `motor/tui.py`
- Create: `tests/test_tui.py`

**Interfaces:**
- Consumes: `EstadoRepo.listar_repos()`, `EstadoRepo.resolver_repo()`, `GitRepo.fetch()`, `GitRepo.list_version_branches()` e `GitRepo.list_version_tags()`.
- Produces: `RepoOption`, `VersionOption`, `descobrir_repos()` e `descobrir_versoes()` para a aplicação da Task 4.

- [ ] **Step 1: Escrever os testes de descoberta de repos**

Criar `tests/test_tui.py`:

```python
from pathlib import Path

from motor.adapters.estado.fake import FakeEstado
from motor.domain.types import RepoInfo
from motor.tui import RepoOption, descobrir_repos


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
```

- [ ] **Step 2: Rodar os testes para confirmar a falha de importação**

Run: `rtk uv run pytest tests/test_tui.py -q`

Expected: FAIL porque `motor.tui` ainda não existe.

- [ ] **Step 3: Implementar o catálogo mínimo de repos**

Criar `motor/tui.py` com:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
```

- [ ] **Step 4: Confirmar os testes de repos**

Run: `rtk uv run pytest tests/test_tui.py -q`

Expected: 3 PASS.

- [ ] **Step 5: Escrever o teste de versões, incluindo ordem numérica e tags**

Adicionar a `tests/test_tui.py`:

```python
from motor.tui import VersionOption, descobrir_versoes


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

    assert descobrir_versoes(git) == [
        VersionOption(numero="14.0.0", liberada=False),
        VersionOption(numero="13.10.0", liberada=False),
        VersionOption(numero="13.9.0", liberada=True),
    ]
    assert git.fetched == ["origin"]
```

- [ ] **Step 6: Confirmar a falha e implementar a descoberta de versões**

Run: `rtk uv run pytest tests/test_tui.py::test_descobrir_versoes_faz_fetch_deduplica_ordena_e_marca_tag -q`

Expected: FAIL porque `descobrir_versoes` ainda não existe.

Adicionar a `motor/tui.py`:

```python
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
```

- [ ] **Step 7: Rodar os testes da descoberta**

Run: `rtk uv run pytest tests/test_tui.py -q`

Expected: 4 PASS.

- [ ] **Step 8: Commit**

```bash
rtk git add motor/tui.py tests/test_tui.py
rtk git commit -m "feat(tui): descobre repos e versões"
```

---

### Task 3: Renderização estruturada de `VersionStatus`

**Files:**
- Modify: `motor/tui.py`
- Modify: `tests/test_tui.py`

**Interfaces:**
- Consumes: `VersionStatus` e `_agrupar_por_task()` existentes.
- Produces: `renderizar_status(status: VersionStatus, auditado: bool = False) -> Group`.

- [ ] **Step 1: Escrever testes de texto para pendências, snapshot e auditoria**

Adicionar a `tests/test_tui.py`:

```python
import datetime

from rich.console import Console

from motor.domain.types import CommitRef, VersionStatus
from motor.tui import renderizar_status


def _texto(renderable) -> str:
    console = Console(record=True, width=120, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_renderizar_status_agrupa_pendencias_e_exibe_alertas():
    commit = CommitRef(
        hash_origem="deadbeefcafe",
        chamado="255514",
        msg="Ajusta pagamento\ncorpo",
    )
    status = VersionStatus(
        verde=False,
        tasks_novas=["255514"],
        tasks_removidas=["200000"],
        estado_integro=False,
        tasks_ambiguas=["300000"],
        commits_sumidos=["badc0ffee000"],
        faltantes=[commit],
        conflitantes=[commit],
        suspeitos_conteudo=[commit],
        tasks_sem_commits=["400000"],
    )

    texto = _texto(renderizar_status(status))

    for esperado in (
        "REQUER ATENÇÃO",
        "Tasks novas 1",
        "Tasks removidas 1",
        "Faltantes 1",
        "Conflitos 1",
        "255514",
        "deadbeef",
        "CONFLITANTE",
        "SUSPEITO",
        "300000",
        "400000",
        "badc0ffe",
    ):
        assert esperado in texto


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


def test_renderizar_auditoria_nomeia_recalculo_sem_alterar_snapshot():
    texto = _texto(
        renderizar_status(VersionStatus(verde=True, estado_integro=True), auditado=True)
    )

    assert "AUDITORIA DA TAG" in texto
    assert "snapshot não alterado" in texto
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `rtk uv run pytest tests/test_tui.py -k renderizar -q`

Expected: FAIL porque `renderizar_status` ainda não existe.

- [ ] **Step 3: Implementar os renderables Rich sem estado de UI**

Adicionar os imports `Group`, `Panel`, `Table` e `Text`. Implementar:

```python
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from motor.__main__ import _agrupar_por_task
from motor.domain.types import VersionStatus


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
```

- [ ] **Step 4: Rodar os testes de renderização**

Run: `rtk uv run pytest tests/test_tui.py -k renderizar -q`

Expected: 3 PASS.

- [ ] **Step 5: Rodar todos os testes da TUI**

Run: `rtk uv run pytest tests/test_tui.py -q`

Expected: 7 PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add motor/tui.py tests/test_tui.py
rtk git commit -m "feat(tui): estrutura resultado da verificação"
```

---

### Task 4: Aplicação Textual responsiva e testável

**Files:**
- Modify: `motor/tui.py`
- Modify: `tests/test_tui.py`

**Interfaces:**
- Consumes: `RepoOption`, `VersionOption` e `renderizar_status()`.
- Produces: `MotorTUI(carregar_repos, carregar_versoes, executar)`; os três callbacks são executados em workers.

- [ ] **Step 1: Escrever o teste Pilot do fluxo principal e da auditoria**

Adicionar a `tests/test_tui.py`:

```python
import asyncio
from textual.widgets import Button, Checkbox, Select, Static

from motor.tui import MotorTUI


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
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            assert app.query_one("#auditar", Checkbox).display
            assert not app.query_one("#auditar", Checkbox).value
            app.query_one("#auditar", Checkbox).value = True
            assert not app.query_one("#executar", Button).disabled
            await pilot.click("#executar")
            await app.workers.wait_for_complete()

            assert chamadas == [(repo, "14.0.0", True)]
            assert "VERDE" in _texto(
                app.query_one("#resultado", Static).renderable
            )

    asyncio.run(executar_fluxo())
```

Adicionar os testes de erro e concorrência:

```python
from threading import Event

from motor.errors import MotorError


def test_app_exibe_motor_error_sem_traceback():
    def falhar():
        raise MotorError("banco inacessível")

    async def executar_fluxo() -> None:
        app = MotorTUI(falhar, lambda repo: [], lambda repo, versao, auditar: None)
        async with app.run_test(size=(120, 36)):
            await app.workers.wait_for_complete()
            assert "banco inacessível" in _texto(
                app.query_one("#resultado", Static).renderable
            )

    asyncio.run(executar_fluxo())


def test_app_esconde_erro_interno_e_registra_traceback(caplog):
    def falhar():
        raise RuntimeError("bug secreto")

    async def executar_fluxo() -> None:
        app = MotorTUI(falhar, lambda repo: [], lambda repo, versao, auditar: None)
        async with app.run_test(size=(120, 36)):
            await app.workers.wait_for_complete()
            texto = _texto(app.query_one("#resultado", Static).renderable)
            assert "Erro interno fatal" in texto
            assert "bug secreto" not in texto

    asyncio.run(executar_fluxo())
    assert "Erro interno fatal na TUI" in caplog.text
    assert "Traceback" in caplog.text


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
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            await pilot.click("#executar")
            assert await asyncio.to_thread(iniciou.wait, 1)
            assert app.query_one("#executar", Button).disabled
            await pilot.click("#executar")
            liberar.set()
            await app.workers.wait_for_complete()

    asyncio.run(executar_fluxo())
    assert chamadas == ["14.0.0"]
```

Adicionar o segundo teste completo:

```python
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
            assert app.query_one("#executar", Button).disabled
            assert "checkout local não encontrado" in _texto(
                app.query_one("#resultado", Static).renderable
            )

    asyncio.run(executar_fluxo())
```

- [ ] **Step 2: Confirmar a falha da classe ausente**

Run: `rtk uv run pytest tests/test_tui.py -k 'app_' -q`

Expected: FAIL porque `MotorTUI` ainda não existe.

- [ ] **Step 3: Implementar composição, estado e bindings**

Adicionar a `motor/tui.py`:

```python
import logging
from collections.abc import Callable

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Checkbox, Footer, Header, Select, Static

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
```

- [ ] **Step 4: Implementar workers, eventos e bloqueio contra concorrência**

Adicionar à classe:

```python
    def _erro(self, mensagem: str) -> None:
        self.query_one("#resultado", Static).update(
            Panel(mensagem, title="Erro", style="bold red")
        )

    def _falha(self, erro: Exception) -> None:
        if isinstance(erro, MotorError):
            self._erro(str(erro))
        else:
            logging.exception("Erro interno fatal na TUI", exc_info=erro)
            self._erro("Erro interno fatal")

    def _bloquear(self, ocupado: bool) -> None:
        self._ocupado = ocupado
        self.query_one("#repo", Select).disabled = ocupado or not self._tem_repos
        self.query_one("#versao", Select).disabled = (
            ocupado or not self._tem_versoes
        )
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
        select.set_options([
            (
                Text(
                    opcao.nome if opcao.disponivel else f"{opcao.nome} — checkout local não encontrado",
                    style="" if opcao.disponivel else "dim",
                ),
                opcao,
            )
            for opcao in opcoes
        ])
        self._tem_repos = bool(opcoes)
        self._bloquear(False)
        if opcoes and not any(opcao.disponivel for opcao in opcoes):
            self._erro(
                "nenhum checkout local encontrado; confira PROJECTS_DIR"
            )

    def on_select_changed(self, evento: Select.Changed) -> None:
        if evento.select.id == "repo":
            self._selecionar_repo(evento.value)
        elif evento.select.id == "versao":
            self._selecionar_versao(evento.value)

    def _selecionar_repo(self, valor) -> None:
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

    def _selecionar_versao(self, valor) -> None:
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
            self.call_from_thread(
                self.query_one("#resultado", Static).update,
                renderizar_status(status, auditado=auditar),
            )
        finally:
            self.call_from_thread(self._bloquear, False)
```

- [ ] **Step 5: Rodar os testes Pilot**

Run: `rtk uv run pytest tests/test_tui.py -k 'app_' -q`

Expected: 5 PASS; nenhum callback roda na thread da UI, erros ficam classificados e apenas uma execução é registrada.

- [ ] **Step 6: Rodar todos os testes da TUI**

Run: `rtk uv run pytest tests/test_tui.py -q`

Expected: todos PASS.

- [ ] **Step 7: Commit**

```bash
rtk git add motor/tui.py tests/test_tui.py
rtk git commit -m "feat(tui): adiciona interface de verificação"
```

---

### Task 5: Composição de produção, CLI e documentação viva

**Files:**
- Modify: `motor/tui.py`
- Modify: `motor/__main__.py:77-127,297-346`
- Modify: `tests/test_main.py:20-100`
- Modify: `tests/test_tui.py`
- Modify: `ferramenta_versoes_design.md:486-544`

**Interfaces:**
- Consumes: `_abrir_sessao()`, `database_url()`, `new_git_subprocess()`, `TickioRest`, `Deps` e `verificar()` existentes.
- Produces: `run_tui() -> None`, `_iniciar_tui() -> None` e o subcomando `motor tui`.

- [ ] **Step 1: Escrever o teste de despacho do CLI sem abrir banco no main thread**

Adicionar a `tests/test_main.py`:

```python
def test_tui_despacha_sem_abrir_banco_no_cli(monkeypatch):
    chamadas: list[str] = []
    monkeypatch.setattr(cli, "_iniciar_tui", lambda: chamadas.append("tui"))
    monkeypatch.setattr(
        cli,
        "_abrir_sessao",
        lambda: pytest.fail("o CLI nao deve abrir banco antes da TUI"),
    )

    main(["tui"])

    assert chamadas == ["tui"]
```

- [ ] **Step 2: Confirmar a falha e adicionar o subcomando mínimo**

Run: `rtk uv run pytest tests/test_main.py::test_tui_despacha_sem_abrir_banco_no_cli -q`

Expected: FAIL porque argparse ainda não conhece `tui` ou `_iniciar_tui` não existe.

Em `_build_parser()`:

```python
sub.add_parser("tui", help="abre a interface interativa de verificacao")
```

Antes de qualquer sessão do banco em `main()`:

```python
def _iniciar_tui() -> None:
    from motor.tui import run_tui

    run_tui()
```

No bloco `try` de `main()`:

```python
if args.comando == "tui":
    _iniciar_tui()
    return
```

- [ ] **Step 3: Confirmar o despacho**

Run: `rtk uv run pytest tests/test_main.py::test_tui_despacha_sem_abrir_banco_no_cli -q`

Expected: PASS.

- [ ] **Step 4: Escrever testes das funções de produção com bordas substituídas**

Em `tests/test_tui.py`, adicionar testes completos das três funções:

```python
import contextlib

import motor.tui as tui


def test_repos_do_ambiente_usa_estado_e_projects_dir(tmp_path, monkeypatch):
    estado = FakeEstado(
        repos={"alpha": RepoInfo(nome="alpha", tickio_sistema_id=7)}
    )
    checkout = _checkout(tmp_path, "alpha")
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setattr(tui, "_abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(tui, "PostgresEstado", lambda sessao: estado)

    assert tui._repos_do_ambiente() == [
        RepoOption(nome="alpha", caminho=str(checkout))
    ]


def test_versoes_do_repo_abre_git_no_checkout(monkeypatch):
    git = GitCatalogoFake()
    caminhos: list[str] = []
    monkeypatch.setattr(
        tui,
        "new_git_subprocess",
        lambda caminho: caminhos.append(caminho) or git,
    )

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
        capturado.update(
            repo=deps.repo,
            versao=versao,
            auditar=auditar,
            tickio_sistema_id=deps.tasks.sistema_id,
            bitbucket_token=deps.bitbucket_token,
            bitbucket_email=deps.bitbucket_email,
        )
        return VersionStatus(verde=True, estado_integro=True)

    monkeypatch.setenv("BITBUCKET_TOKEN", "tok-secreto")
    monkeypatch.setenv("BITBUCKET_EMAIL", "dev@example.com")
    monkeypatch.setattr(tui, "_abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(tui, "PostgresEstado", lambda sessao: estado)
    monkeypatch.setattr(tui, "new_git_subprocess", lambda caminho: object())
    monkeypatch.setattr(tui, "TickioRest", TickioSpy)
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
```

- [ ] **Step 5: Implementar as funções de composição sem fábrica genérica**

Adicionar a `motor/tui.py`:

```python
import os

from motor.__main__ import _abrir_sessao
from motor.adapters.estado.postgres import PostgresEstado
from motor.adapters.git.subprocess import new_git_subprocess
from motor.adapters.tasksource.tickio import TickioRest
from motor.engine.deps import Deps
from motor.engine.verificar import verificar


def _repos_do_ambiente() -> list[RepoOption]:
    with _abrir_sessao() as sessao:
        return descobrir_repos(
            PostgresEstado(sessao=sessao), os.environ.get("PROJECTS_DIR", "")
        )


def _versoes_do_repo(repo: RepoOption) -> list[VersionOption]:
    if repo.caminho is None:
        return []
    return descobrir_versoes(new_git_subprocess(repo.caminho))


def _verificar_repo(
    repo: RepoOption, versao: str, auditar: bool
) -> VersionStatus:
    if repo.caminho is None:
        raise MotorError("checkout local não encontrado")
    git = new_git_subprocess(repo.caminho)
    with _abrir_sessao() as sessao:
        estado = PostgresEstado(sessao=sessao)
        info = estado.resolver_repo(os.path.basename(repo.caminho))
        tasks = TickioRest(
            base_url=os.environ.get("TICKIO_BASE_URL", ""),
            usuario=os.environ.get("TICKIO_USER", ""),
            senha=os.environ.get("TICKIO_PASSWORD", ""),
            sistema_id=info.tickio_sistema_id,
        )
        deps = Deps(
            git=git,
            tasks=tasks,
            estado=estado,
            repo=info.nome,
            bitbucket_token=os.environ.get("BITBUCKET_TOKEN", ""),
            bitbucket_email=os.environ.get("BITBUCKET_EMAIL", ""),
        )
        return verificar(deps, versao, auditar=auditar)


def run_tui() -> None:
    MotorTUI(_repos_do_ambiente, _versoes_do_repo, _verificar_repo).run()
```

- [ ] **Step 6: Rodar testes de composição, TUI e CLI**

Run: `rtk uv run pytest tests/test_tui.py tests/test_main.py -q`

Expected: todos PASS.

- [ ] **Step 7: Atualizar o desenho principal sem reabrir o escopo**

Em `ferramenta_versoes_design.md`, registrar:

- etapa TUI em processo para `verificar` como implementada;
- barra repo/ação/versão e auditoria explícita de tag;
- daemon adiado até existir requisito de interface web ou execução persistente;
- diagrama de front-ends como `CLI · TUI`.

Não documentar `criar`, `atualizar` ou `reconstruir-estado` como ações da TUI.

- [ ] **Step 8: Rodar verificação completa**

Run: `rtk uv run pytest -q`

Expected: suíte unitária PASS; testes `integracao` SKIP sem Postgres ou PASS com Postgres configurado.

Run: `rtk uv run motor --help`

Expected: saída contém `tui` e os comandos existentes.

Run: `rtk git diff --check`

Expected: nenhuma saída e exit code 0.

- [ ] **Step 9: Commit final da feature**

```bash
rtk git add motor/tui.py motor/__main__.py tests/test_tui.py tests/test_main.py ferramenta_versoes_design.md
rtk git commit -m "feat(cli): disponibiliza TUI de verificação"
```

---

## Execution Workflow

1. Criar uma worktree isolada na branch `codex/tui-verificar` usando
   `superpowers:using-git-worktrees`.
2. Executar Tasks 1–5 com `superpowers:subagent-driven-development`: um subagente
   implementador novo por task, seguido de revisão de conformidade e revisão de
   qualidade antes da task seguinte.
3. Após todos os commits, usar `superpowers:verification-before-completion` e
   `superpowers:requesting-code-review`.
4. Fazer merge fast-forward ou merge commit da branch `codex/tui-verificar` na
   `main`, sem rebase destrutivo e sem alterar mudanças alheias.
5. Rodar a suíte completa novamente na `main` após o merge.
