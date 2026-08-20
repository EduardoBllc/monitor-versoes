from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

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
