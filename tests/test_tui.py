import datetime
from pathlib import Path

from rich.console import Console

from motor.adapters.estado.fake import FakeEstado
from motor.domain.types import CommitRef, RepoInfo, VersionStatus
from motor.tui import (
    RepoOption,
    VersionOption,
    descobrir_repos,
    descobrir_versoes,
    renderizar_status,
)


def _texto(renderable) -> str:
    console = Console(record=True, width=120, color_system=None)
    console.print(renderable)
    return console.export_text()


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
