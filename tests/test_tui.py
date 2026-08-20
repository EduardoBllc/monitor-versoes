from pathlib import Path

from motor.adapters.estado.fake import FakeEstado
from motor.domain.types import RepoInfo
from motor.tui import VersionOption, RepoOption, descobrir_repos, descobrir_versoes


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
