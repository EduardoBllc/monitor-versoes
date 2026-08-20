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
