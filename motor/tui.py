"""TUI interativa pro motor - esqueleto.

Reusa motor/engine/* e Deps exatamente como __main__.py; so troca a camada
de I/O (prints -> widgets). Verificar roda em worker thread pra nao travar a
UI enquanto o git subprocess responde.
"""

from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from motor.__main__ import _agrupar_por_task
from motor.adapters.git.subprocess import new_git_subprocess
from motor.adapters.tasksource.rest import ClickUpRest
from motor.engine.deps import Deps
from motor.engine.verificar import verificar
from motor.errors import MotorError


def _resolver_repo(valor: str) -> str:
    if os.path.isdir(valor):
        return os.path.abspath(valor)
    projects_dir = os.environ.get("PROJECTS_DIR", "")
    if projects_dir:
        candidato = os.path.join(projects_dir, valor)
        if os.path.isdir(candidato):
            return candidato
    raise MotorError(f"--repo nao encontrado: '{valor}'")


def _lock_dir_para(repo: str) -> str:
    motor_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(motor_root, "locks", os.path.basename(repo))


class MotorTUI(App):
    """Conecta direto no engine: repo + versao -> verificar() -> log."""

    CSS = """
    Horizontal { height: auto; }
    #repo, #versao { width: 1fr; }
    #status { height: auto; padding: 0 1; text-style: bold; }
    #status.ok { background: $success; }
    #status.bad { background: $error; }
    DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield Input(placeholder="repo (ex: vendabemweb)", id="repo")
            yield Input(placeholder="versao (ex: 14.0.0)", id="versao")
            yield Button("Verificar", id="verificar", variant="primary")
        yield Static("", id="status")
        yield DataTable(id="tabela")
        yield Footer()

    def on_mount(self) -> None:
        tabela = self.query_one("#tabela", DataTable)
        tabela.cursor_type = "row"
        tabela.add_columns("Chamado", "Task", "Título", "Commit", "Mensagem", "")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "verificar":
            self.rodar_verificar(
                self.query_one("#repo", Input).value,
                self.query_one("#versao", Input).value,
            )

    def _mostrar_status(self, texto: str, ok: bool) -> None:
        badge = self.query_one("#status", Static)
        badge.update(texto)
        badge.set_class(ok, "ok")
        badge.set_class(not ok, "bad")

    def _preencher_tabela(self, status) -> None:
        tabela = self.query_one("#tabela", DataTable)
        tabela.clear()
        conflitantes = {c.hash_origem for c in status.conflitantes}
        grupos = _agrupar_por_task(status.faltantes)
        for chave, commits in grupos.items():
            for c in commits:
                primeira_linha = c.msg.splitlines()[0] if c.msg else ""
                marca = "⚠ conflito" if c.hash_origem in conflitantes else ""
                tabela.add_row(
                    c.chamado, c.task, c.titulo, c.hash_origem[:8], primeira_linha, marca
                )

    @work(thread=True)
    def rodar_verificar(self, repo_arg: str, versao: str) -> None:
        self.call_from_thread(self._mostrar_status, f"verificando {versao}...", True)
        try:
            repo = _resolver_repo(repo_arg)
            deps = Deps(
                git=new_git_subprocess(repo),
                tasks=ClickUpRest(token=os.environ.get("CLICKUP_TOKEN", "")),
                lock_dir=_lock_dir_para(repo),
            )
            status = verificar(deps, versao)
        except MotorError as e:
            self.call_from_thread(self._mostrar_status, f"erro: {e}", False)
            return

        resumo = (
            f"{'✅ VERDE' if status.verde else '❌ FALTAM COMMITS'}  "
            f"| tasks novas: {len(status.tasks_novas)} "
            f"| removidas: {len(status.tasks_removidas)} "
            f"| lock {'integro' if status.lock_integro else 'DIVERGENTE'} "
            f"| faltantes: {len(status.faltantes)} "
            f"| conflitantes: {len(status.conflitantes)}"
        )
        self.call_from_thread(self._mostrar_status, resumo, status.verde)
        self.call_from_thread(self._preencher_tabela, status)


def main() -> None:
    if load_dotenv:
        load_dotenv()
    MotorTUI().run()


if __name__ == "__main__":
    main()
