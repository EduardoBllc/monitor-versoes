from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from enum import IntEnum

from motor.domain.commits import ordenar_por_data
from motor.domain.types import CommitRef, VersionStatus
from motor.engine.deps import Deps
from motor.engine.verificar import verificar
from motor.errors import ErroDeEntrada, RecusaDeInvariante
from motor.ports import CherryPickOutcome
from motor.progresso import Progresso
from motor.services.publication_gate import PublicationGate

logger = logging.getLogger(__name__)


class AtualizarStatus(IntEnum):
    DONE = 0
    BLOCKED = 1


@dataclass
class AtualizarResult:
    status: AtualizarStatus
    blocked_commit: str = ""
    arquivos_conflito: list[str] = field(default_factory=list)
    # commits cherry-picked nesta invocacao (vazio = nada a fazer)
    aplicados: list[CommitRef] = field(default_factory=list)
    # commits que ja estavam no historico (ancestrais, sem cherry-pick a fazer)
    ja_presentes: int = 0
    # o VersionStatus do verificar que abriu o lote. O lote e empurrado mesmo
    # quando ele nao esta verde (todo commit vem de status.faltantes, nada
    # ilegitimo embarca, e travar em tasks_sem_commits emperraria o fluxo toda
    # vez que um chamado nao tem codigo), mas as secoes vermelhas tem de chegar
    # ao terminal: sem isso tasks_ambiguas, tasks_sem_commits e commits_sumidos
    # eram calculados e descartados. commits_sumidos e o pior — significa
    # historico reescrito debaixo de um commit ja aplicado, e o verificar ja
    # sobrescreveu a linha de estado que guardava a evidencia.
    status_versao: VersionStatus | None = None


def _recusar_se_liberada(deps: Deps, versao: str) -> None:
    """Trava de escrita em versao liberada, na entrada de todo ponto que mexe na
    branch (`atualizar` e `atualizar_continue`, os dois expostos pelo CLI).

    O fetch vem antes da leitura, nao depois: `tag_exists` le o ref store local,
    e a tag de uma versao liberada em outra maquina so entra aqui pelo fetch. Sem
    ele a recusa seria decidida em cima de refs velhas e o motor mexeria numa
    versao que ja saiu.
    """
    deps.progresso(Progresso("conferindo se a vers\u00e3o j\u00e1 saiu"))
    deps.git.fetch("origin")

    if PublicationGate(git=deps.git).liberada(versao):
        raise RecusaDeInvariante(
            f"versao {versao} ja liberada (tem tag) - remarque a tarefa "
            "para a proxima versao em construcao"
        )


def atualizar(deps: Deps, versao: str) -> AtualizarResult:
    """Aplica os commits faltantes por commit-date asc (spec §5).

    Versao com tag e recusada: o alvo dela congelou na liberacao, e alteracao
    na branch nao reflete no que a tag aponta. Esquecimento vai para a proxima
    versao (spec §2).
    """
    _recusar_se_liberada(deps, versao)

    status = verificar(deps, versao, manter_worktree=True)

    if status.suspeitos_conteudo:
        hashes = ", ".join(c.hash_origem[:8] for c in status.suspeitos_conteudo)
        raise RecusaDeInvariante(
            "commits suspeitos de cherry-pick manual com conteudo divergente "
            f"(mesma mensagem e arquivos ja existem no alvo, sem trailer -x): {hashes}. "
            "Confirme manualmente (exclua no estado se ja aplicado) antes de rodar atualizar de novo."
        )

    faltam = ordenar_por_data(status.faltantes)

    deps.git.use_worktree(versao)

    aplicados: list[CommitRef] = []
    ja_presentes = len(status.ancestrais)
    t = time.monotonic()
    for indice, c in enumerate(faltam, start=1):
        deps.progresso(Progresso("cherry-pick", indice, len(faltam)))
        outcome = deps.git.cherry_pick_x(c.hash_origem)
        if outcome == CherryPickOutcome.CONFLITO:
            paths = deps.git.conflicted_paths()
            if len(paths) == 0:
                # rerere.autoUpdate resolveu sozinho (§8) - segue o pick.
                deps.git.continue_cherry_pick()
                aplicados.append(c)
                continue
            return AtualizarResult(
                status=AtualizarStatus.BLOCKED,
                blocked_commit=c.hash_origem,
                arquivos_conflito=paths,
                aplicados=aplicados,
                ja_presentes=ja_presentes,
                status_versao=status,
            )
        aplicados.append(c)
    logger.debug("cherry-pick de %d commits: %.3fs", len(faltam), time.monotonic() - t)

    # O estado ja foi gravado pelo verificar no comeco do run, com a presenca de
    # ANTES dos picks; regrava com o lote aplicado para o `estado` das
    # atribuicoes refletir a realidade. Tarefa sem commit nenhum continua
    # pendente: o lote nao entregou nada dela.
    aplicadas = [
        replace(a, estado="aplicado") if a.commits else a
        for a in deps.estado.atribuicoes(deps.repo, versao)
    ]
    deps.estado.substituir_atribuicoes(deps.repo, versao, aplicadas)

    # publica so apos o lote fechar sem conflito (§6, "branch compartilhada") -
    # um lote BLOCKED fica so local ate resolver e rodar de novo.
    deps.progresso(Progresso("publicando na origin"))
    deps.git.push_branch("origin", versao)
    # a worktree e so um checkout local descartavel - o que importa (commits) ja
    # esta na branch e no remoto. use_worktree recria sob demanda.
    deps.git.worktree_remove(versao)
    return AtualizarResult(
        status=AtualizarStatus.DONE,
        aplicados=aplicados,
        ja_presentes=ja_presentes,
        status_versao=status,
    )


def atualizar_continue(deps: Deps, versao: str) -> AtualizarResult:
    """Retoma um cherry-pick resolvido manualmente (checkpoint resumivel, §8).

    Invocacao nova do CLI, sem contexto em memoria de quais commits do lote ja
    foram aplicados. Nao precisa reconstruir nada a mao: o `atualizar` abaixo
    chama `verificar`, que reprojeta o estado a partir do git de verdade.

    A recusa por tag e reavaliada aqui, antes do `continue_cherry_pick`: se a
    versao foi liberada enquanto o conflito estava aberto, deixar o pick entrar
    poria um commit na branch de uma versao congelada — a recusa do `atualizar`
    la embaixo chegaria tarde.
    """
    _recusar_se_liberada(deps, versao)

    deps.progresso(Progresso("retomando o cherry-pick"))
    deps.git.use_worktree(versao)
    _, ok = deps.git.pending_cherry_pick()
    if not ok:
        raise ErroDeEntrada("nenhum cherry-pick pendente pra continuar")

    deps.git.continue_cherry_pick()
    return atualizar(deps, versao)


def atualizar_abort(deps: Deps, versao: str) -> None:
    deps.git.use_worktree(versao)
    deps.git.abort_cherry_pick()
    deps.git.worktree_remove(versao)
