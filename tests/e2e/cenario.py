"""Cenário das jornadas da web: repositórios git reais, config e estado num diretório.

Cada papel é uma versão `X.Y.0` cortada do mesmo commit da `main`, com o seu
chamado e o seu arquivo, para que nenhum papel mude o desfecho de outro. As
versões já saem verificadas uma vez: a primeira verificação de uma versão dá
todas as tarefas por novas, e o daemon tem de abrir no estado da tabela.

`python -m tests.e2e.cenario <raiz>` monta e imprime o manifesto em JSON.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from motor.adapters.commitsource.bitbucket import Var as VarBitbucket
from motor.config import (
    VAR_APPDATA,
    VAR_LOCALAPPDATA,
    VAR_XDG_CACHE_HOME,
    VAR_XDG_CONFIG_HOME,
    VarAmbiente,
)
from motor.operacoes import repos_do_ambiente, verificar_repo
from tests.config_repos import secao_repo
from tests.e2e.fonte import CHAVE_MAPA

RAIZ_DO_PROJETO = Path(__file__).resolve().parents[2]
NOME_REPO = "projeto"
NOME_SEM_CHECKOUT = "sem-checkout"
PRINCIPAL = "main"
ARQUIVO_CONFLITO = "conflito.txt"
ARQUIVO_VAZIO = "vazio.txt"
VERSAO_NOVA = "1.7.0"
DATA_INICIAL = datetime.datetime(2026, 1, 5, 9, 0, tzinfo=datetime.UTC)


class VarProcesso(StrEnum):
    """Variáveis isoladas que o motor não nomeia em constante."""

    HOME = "HOME"
    PYTHONPATH = "PYTHONPATH"
    DATABASE_BACKEND = "DATABASE_BACKEND"


class PapelVersao(StrEnum):
    LIBERADA = "liberada"
    VERDE = "verde"
    FALTANTES = "faltantes"
    CONFLITO = "conflito"
    VAZIO = "vazio"
    ORFAO = "orfao"


VERSOES = {
    PapelVersao.LIBERADA: "1.1.0",
    PapelVersao.VERDE: "1.2.0",
    PapelVersao.FALTANTES: "1.3.0",
    PapelVersao.CONFLITO: "1.4.0",
    PapelVersao.VAZIO: "1.5.0",
    PapelVersao.ORFAO: "1.6.0",
}
CHAMADOS = {
    PapelVersao.LIBERADA: "101",
    PapelVersao.VERDE: "201",
    PapelVersao.FALTANTES: "301",
    PapelVersao.CONFLITO: "401",
    PapelVersao.VAZIO: "501",
    PapelVersao.ORFAO: "601",
}
#: Chamado de nenhuma versão que mexe na linha do conflito antes do 401.
CHAMADO_CULPADO = "400"
#: Chamado de nenhuma versão: leva o conteúdo do 501 para a branch sem trailer.
CHAMADO_DO_VAZIO_NA_BRANCH = "502"
_APLICADOS = (PapelVersao.LIBERADA, PapelVersao.VERDE, PapelVersao.ORFAO)
_COM_ARQUIVO_PROPRIO = (*_APLICADOS, PapelVersao.FALTANTES)


@dataclass(frozen=True)
class Manifesto:
    repo: str
    repo_sem_checkout: str
    versoes: dict[PapelVersao, str]
    chamados: dict[PapelVersao, str]
    arquivo_conflito: str
    versao_nova: str
    ambiente: dict[str, str]


class _Git:
    """Git com identidade e datas fixas, sem ler a config de quem roda."""

    def __init__(self, ambiente: dict[str, str]) -> None:
        self.ambiente = {**os.environ, **ambiente, "GIT_CONFIG_NOSYSTEM": "1"}
        self.data = DATA_INICIAL

    def __call__(self, cwd: Path, *args: str) -> str:
        self.data += datetime.timedelta(minutes=1)
        data = self.data.isoformat()
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            env={**self.ambiente, "GIT_AUTHOR_DATE": data, "GIT_COMMITTER_DATE": data},
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def identidade(self, repo: Path) -> None:
        self(repo, "config", "user.name", "Cenario E2E")
        self(repo, "config", "user.email", "cenario@e2e.invalid")

    def commit(self, repo: Path, mensagem: str, arquivos: dict[str, str]) -> str:
        for nome, conteudo in arquivos.items():
            (repo / nome).write_text(conteudo)
        self(repo, "add", *arquivos)
        self(repo, "commit", "-m", mensagem)
        return self(repo, "rev-parse", "HEAD")


def _ambiente(raiz: Path) -> dict[str, str]:
    return {
        VAR_XDG_CONFIG_HOME: str(raiz / "config"),
        VAR_XDG_CACHE_HOME: str(raiz / "cache"),
        VarAmbiente.DATABASE_SQLITE_PATH: str(raiz / "estado.db"),
        VAR_LOCALAPPDATA: str(raiz / "localappdata"),
        VAR_APPDATA: str(raiz / "appdata"),
        # Dados e travas moram em `~/.local/share`, e o git lê o `~/.gitconfig`.
        VarProcesso.HOME: str(raiz / "home"),
        VarProcesso.PYTHONPATH: str(RAIZ_DO_PROJETO),
        VarProcesso.DATABASE_BACKEND: "",
        VarBitbucket.TOKEN: "",
        VarBitbucket.EMAIL: "",
    }


def _semear(git: _Git, semente: Path) -> None:
    """A `main` com o commit de cada chamado e as branches de versão."""
    git(semente, "init", "-b", PRINCIPAL)
    git.identidade(semente)
    git.commit(semente, "inicio", {ARQUIVO_CONFLITO: "v0\n", ARQUIVO_VAZIO: "a\n"})
    for versao in VERSOES.values():
        git(semente, "branch", versao)

    def na_main(chamado: str, arquivos: dict[str, str]) -> str:
        return git.commit(semente, f"ch{chamado} tarefa {chamado}", arquivos)

    origem = {
        papel: na_main(CHAMADOS[papel], {f"{CHAMADOS[papel]}.txt": "feito\n"})
        for papel in _COM_ARQUIVO_PROPRIO
    }
    na_main(CHAMADO_CULPADO, {ARQUIVO_CONFLITO: "v1\n"})
    na_main(CHAMADOS[PapelVersao.CONFLITO], {ARQUIVO_CONFLITO: "v2\n"})
    na_main(CHAMADOS[PapelVersao.VAZIO], {ARQUIVO_VAZIO: "b\n"})

    for papel in _APLICADOS:
        git(semente, "checkout", VERSOES[papel])
        git(semente, "cherry-pick", "-x", origem[papel])
    git(semente, "checkout", VERSOES[PapelVersao.VAZIO])
    # O arquivo extra muda o patch-id: sem ele o oráculo daria o 501 por
    # presente, e o pick nem seria tentado.
    git.commit(
        semente,
        f"ch{CHAMADO_DO_VAZIO_NA_BRANCH} adianta o conteudo",
        {ARQUIVO_VAZIO: "b\n", "extra.txt": "extra\n"},
    )
    git(semente, "checkout", VERSOES[PapelVersao.ORFAO])
    git.commit(semente, "ajuste sem tarefa", {"orfao.txt": "orfao\n"})
    git(semente, "checkout", PRINCIPAL)


def _config(raiz: Path, ambiente: dict[str, str], clone: Path, mapa: Path) -> None:
    central = Path(ambiente[VAR_XDG_CONFIG_HOME]) / "monitor-versoes" / "config.toml"
    central.parent.mkdir(parents=True)
    central.write_text(
        "[atualizacoes]\n"
        "checar = false\n\n"
        "[tarefas]\n"
        'fonte = "tests.e2e.fonte:TarefasDoArquivo"\n'
        f"{CHAVE_MAPA} = '{mapa}'\n\n"
        "[referencia]\n"
        'padrao = "ch{id}"\n\n'
        + secao_repo(NOME_REPO, clone)
        + "\n"
        + secao_repo(NOME_SEM_CHECKOUT, raiz / "sem-checkout")
    )


@contextmanager
def _ambiente_aplicado(ambiente: dict[str, str]) -> Iterator[None]:
    antes = dict(os.environ)
    os.environ.update(ambiente)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(antes)


def montar(raiz: Path) -> Manifesto:
    raiz.mkdir(parents=True)
    ambiente = _ambiente(raiz)
    git = _Git(ambiente)
    semente, origin, clone = raiz / "semente", raiz / "origin.git", raiz / "projeto"
    semente.mkdir()
    _semear(git, semente)
    git(raiz, "init", "--bare", "-b", PRINCIPAL, str(origin))
    git(semente, "push", str(origin), PRINCIPAL, *VERSOES.values())
    git(raiz, "clone", str(origin), str(clone))
    git.identidade(clone)

    mapa = raiz / "mapa.json"
    mapa.write_text(
        json.dumps({VERSOES[p]: [chamado] for p, chamado in CHAMADOS.items()})
    )
    _config(raiz, ambiente, clone, mapa)

    with _ambiente_aplicado(ambiente):
        repo = next(r for r in repos_do_ambiente() if r.nome == NOME_REPO)
        for versao in VERSOES.values():
            verificar_repo(repo, versao, False)
    # A tag vem depois da verificação: liberada que o motor nunca viu não tem
    # snapshot para congelar.
    liberada = VERSOES[PapelVersao.LIBERADA]
    git(semente, "tag", liberada, liberada)
    git(semente, "push", str(origin), f"refs/tags/{liberada}")

    return Manifesto(
        repo=NOME_REPO,
        repo_sem_checkout=NOME_SEM_CHECKOUT,
        versoes=dict(VERSOES),
        chamados=dict(CHAMADOS),
        arquivo_conflito=ARQUIVO_CONFLITO,
        versao_nova=VERSAO_NOVA,
        ambiente=ambiente,
    )


if __name__ == "__main__":
    print(json.dumps(asdict(montar(Path(sys.argv[1])))))
