"""Montagem do front-end: transforma ambiente e entrada do operador em `Deps`.

Esta e a unica camada que conhece adapters concretos ao mesmo tempo que conhece
o `Deps`. O CLI e a TUI importam daqui em vez de um do outro, e o engine volta a
ver so `motor.ports`.

**Montar nao e usar.** Nada aqui faz I/O de rede, nem valida credencial, nem
consulta o git: `atualizar --abort` e `reconstruir-estado` recebem as mesmas
fontes e nunca as chamam. Quem cobra credencial e o adapter, na primeira busca.
Unica excecao deliberada: `resolver_repo`, porque o nome canonico e o
`tickio_sistema_id` decidem *como* montar o resto.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from motor.adapters.commitsource.bitbucket import BitbucketPRCommitSource
from motor.adapters.commitsource.chain import ChainCommitSource
from motor.adapters.commitsource.grep import GrepCommitSource
from motor.adapters.estado.postgres import PostgresEstado
from motor.adapters.git.subprocess import new_git_subprocess
from motor.adapters.tasksource.manuallist import ManualList
from motor.adapters.tasksource.tickio import TickioRest
from motor.config import database_url, worktrees_mantidas
from motor.engine.deps import Deps
from motor.errors import MotorError
from motor.ports import CommitSource, EstadoRepo, GitRepo, TaskSource
from motor.progresso import RelatorProgresso, silencioso


def validar_nome_repo(valor: str) -> str:
    """Nome canonico do repo: basename puro, sem caminho e sem espaco em volta.

    O nome e a chave do estado — aceitar 'pasta/backend' fragmentaria o repo em
    duas linhas paralelas sem erro nenhum aparecer.
    """
    if not valor.strip() or valor != valor.strip() or os.path.basename(valor) != valor:
        raise MotorError("use um nome simples, sem caminho")
    return valor


def validar_sistema_id(valor: str) -> int:
    """ID do sistema no Tickio. Vai cru na query `?sistema=`."""
    try:
        numero = int(valor)
    except ValueError:
        raise MotorError("deve ser um inteiro positivo") from None
    if numero <= 0:
        raise MotorError("deve ser um inteiro positivo")
    return numero


@contextmanager
def abrir_sessao() -> Iterator[Session]:
    """Ciclo de vida do banco: uma engine e uma sessao por comando.

    O CLI e um processo de segundos, entao nao ha o que reaproveitar de um pool
    — a engine nasce aqui, e descartada no fim e a sessao fecha com o `with`.
    Nada disso vive em nivel de modulo: a suite roda sem banco, e uma sessao
    montada no import (ou na construcao do parser) exigiria banco de pe so
    para rodar `--help`.
    """
    engine = create_engine(database_url())
    try:
        with Session(engine) as sessao:
            yield sessao
    finally:
        engine.dispose()


def montar_task_source(
    sistema_id: int, *, fonte: str = "tickio", lista_manual: str = ""
) -> TaskSource:
    """A fonte de tasks depende do repo: o `sistema_id` sai da linha `repo` do
    banco, lida antes daqui via `EstadoRepo.resolver_repo`.

    Sem validar as variaveis aqui — quem cobra credencial e o `TickioRest`, na
    primeira busca.
    """
    if fonte == "tickio":
        return TickioRest(
            base_url=os.environ.get("TICKIO_BASE_URL", ""),
            usuario=os.environ.get("TICKIO_USER", ""),
            senha=os.environ.get("TICKIO_PASSWORD", ""),
            sistema_id=sistema_id,
        )
    return ManualList(caminho=lista_manual)


def montar_commit_source(
    git: GitRepo,
    *,
    token: str = "",
    email: str = "",
    estado: EstadoRepo | None = None,
    repo: str = "",
    progresso: RelatorProgresso = silencioso,
) -> CommitSource:
    """Grep em master e o fallback sempre disponivel. Com token do Bitbucket, a
    PR (merged) vira a fonte primaria: ordem da lista = prioridade.

    O `workspace/repo` do Bitbucket nao e resolvido aqui: sai do
    `git.remote_url("origin")` na primeira busca, dentro do adapter. Resolver
    agora faria todo comando pagar uma chamada de git — e `atualizar --abort`
    num clone sem `origin` passaria a falhar na montagem.
    """
    grep = GrepCommitSource(git=git, progresso=progresso)
    # sem estado nao ha indice local de PRs, e a fonte de PR depende dele.
    if not token or estado is None:
        return grep
    pr = BitbucketPRCommitSource(
        token=token,
        email=email,
        git=git,
        progresso=progresso,
        # indice local de PRs + cache de `PR -> commits`: uma varredura
        # incremental no lugar de uma busca por chamado.
        estado=estado,
        repo_estado=repo,
    )
    return ChainCommitSource(sources=[pr, grep])


def montar_deps(
    caminho_repo: str,
    sessao: Session,
    *,
    fonte_tasks: str = "tickio",
    lista_manual: str = "",
    bitbucket_token: str = "",
    bitbucket_email: str = "",
    progresso: RelatorProgresso = silencioso,
) -> Deps:
    """O `Deps` completo, com as quatro portas montadas.

    Token e email vazios caem no ambiente: e assim que a TUI, que nao tem flag
    nenhuma, liga a fonte de PR do Bitbucket.
    """
    git = new_git_subprocess(caminho_repo, progresso=progresso)
    estado = PostgresEstado(sessao=sessao)
    # O estado vem antes das fontes: o nome canonico do repo e o
    # tickio_sistema_id saem da linha `repo` (que aceita nome ou alias).
    info = estado.resolver_repo(os.path.basename(caminho_repo))
    return Deps(
        git=git,
        tasks=montar_task_source(
            info.tickio_sistema_id, fonte=fonte_tasks, lista_manual=lista_manual
        ),
        estado=estado,
        repo=info.nome,
        commit_source=montar_commit_source(
            git,
            token=bitbucket_token or os.environ.get("BITBUCKET_TOKEN", ""),
            email=bitbucket_email or os.environ.get("BITBUCKET_EMAIL", ""),
            estado=estado,
            repo=info.nome,
            progresso=progresso,
        ),
        progresso=progresso,
        worktrees_mantidas=worktrees_mantidas(),
    )
