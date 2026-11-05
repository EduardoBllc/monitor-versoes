from __future__ import annotations

import datetime
import logging
import time
from dataclasses import dataclass, field, replace
from enum import IntEnum

from motor.domain.types import CommitRef, VersionStatus
from motor.engine.deps import Deps
from motor.engine.verificar import (
    descartar_worktrees,
    preparar_worktree,
    verificar_sem_fetch,
)
from motor.engine.vigencia import verificacao_vigente
from motor.errors import ErroDeEntrada, RecusaDeInvariante
from motor.ports import CherryPickOutcome
from motor.progresso import Progresso
from motor.services.catalogo import Catalogo
from motor.services.publication_gate import PublicationGate
from motor.services.versionamento import aplicar

logger = logging.getLogger(__name__)


class AtualizarStatus(IntEnum):
    DONE = 0
    BLOCKED = 1
    # Resolucao de conflito que nao deixou alteracao: o pick fica aberto
    # esperando decisao do operador (ver `atualizar_continue`).
    VAZIO = 2


@dataclass
class AtualizarResult:
    status: AtualizarStatus
    blocked_commit: str = ""
    arquivos_conflito: list[str] = field(default_factory=list)
    # commits cherry-picked nesta invocacao (vazio = nada a fazer)
    aplicados: list[CommitRef] = field(default_factory=list)
    # commits que ja estavam no historico (ancestrais, sem cherry-pick a fazer)
    ja_presentes: int = 0
    # commits cujo pick nao deixou alteracao e entraram como commit vazio (com
    # o trailer -x, para o oraculo nao os devolver como faltantes no proximo run)
    vazios: list[CommitRef] = field(default_factory=list)
    # o VersionStatus do verificar que abriu o lote. O lote e empurrado mesmo
    # quando ele nao esta verde (todo commit vem de status.faltantes, nada
    # ilegitimo embarca, e travar em tasks_sem_commits emperraria o fluxo toda
    # vez que um chamado nao tem codigo), mas as secoes vermelhas tem de chegar
    # ao terminal: sem isso tasks_ambiguas, tasks_sem_commits e commits_sumidos
    # eram calculados e descartados. commits_sumidos e o pior — significa
    # historico reescrito debaixo de um commit ja aplicado, e o verificar ja
    # sobrescreveu a linha de estado que guardava a evidencia.
    status_versao: VersionStatus | None = None
    # o `verificado_em` do carimbo reaproveitado; None = verificou agora
    reaproveitada_de: datetime.datetime | None = None


def _recusar_se_liberada(deps: Deps, versao: str) -> None:
    """Trava de escrita em versao liberada, na entrada de todo ponto que mexe na
    branch (`atualizar` e `atualizar_continue`, os dois expostos pelo CLI).

    O fetch vem antes da leitura, nao depois: o `Catalogo` le o ref store
    local, e a tag de uma versao liberada em outra maquina so entra aqui pelo
    fetch. Sem ele a recusa seria decidida em cima de refs velhas e o motor
    mexeria numa versao que ja saiu.

    `liberada_em` gravada tambem recusa: o criterio de liberacao pode mudar e
    deixar de reconhecer a versao, mas o snapshot dela ja congelou.
    """
    versionamento = deps.versionamento()
    versionamento.esquema.validar(versao)
    deps.progresso(Progresso("conferindo se a vers\u00e3o j\u00e1 saiu"))
    deps.git.fetch("origin")

    gate = PublicationGate(deps.git, Catalogo(deps.git, versionamento))
    info = deps.estado.versao(deps.repo, versao)
    if gate.liberada(versao) or (info is not None and info.liberada_em is not None):
        raise RecusaDeInvariante(
            f"versao {versao} ja liberada - remarque a tarefa "
            "para a proxima versao em construcao"
        )


def _status_do_lote(
    deps: Deps, versao: str
) -> tuple[VersionStatus, datetime.datetime | None]:
    preparar_worktree(deps, versao)
    vigente = verificacao_vigente(deps, versao)
    if vigente is not None:
        return vigente.status, vigente.verificado_em
    status = verificar_sem_fetch(
        deps, versao, manter_worktree=True, auditar=False, com_worktree=False
    )
    return status, None


def previa_atualizacao(deps: Deps, versao: str) -> VersionStatus:
    """O lote que o `atualizar` aplicaria, deixando o carimbo para ele reaproveitar."""
    _recusar_se_liberada(deps, versao)
    return _status_do_lote(deps, versao)[0]


def _pick(deps: Deps, hash_origem: str) -> CherryPickOutcome:
    """`cherry_pick_x` com o pick vazio ja fechado.

    Vazio nao e conflito nem aplicacao: o commit nao deixou alteracao (o
    conteudo ja esta no alvo por outro caminho). Aqui nao houve julgamento
    humano nenhum — quem disse "isso nao muda nada" foi o proprio git — entao o
    motor fecha como commit vazio e segue o lote. O commit vazio leva o trailer
    -x, e e ele que impede o proximo `verificar` de devolver o mesmo commit como
    faltante para sempre.
    """
    outcome = deps.git.cherry_pick_x(hash_origem)
    if outcome == CherryPickOutcome.VAZIO:
        deps.git.commit_pick_vazio()
    return outcome


def atualizar(deps: Deps, versao: str) -> AtualizarResult:
    """Aplica os commits faltantes na ordem do grafo
    (docs/decisoes/014-ordem-de-aplicacao-pelo-grafo.md).

    Versao com tag e recusada: o alvo dela congelou na liberacao, e alteracao
    na branch nao reflete no que a tag aponta. Esquecimento vai para a proxima
    versao (docs/decisoes/010-travas-publicada-e-liberada.md).
    """
    _recusar_se_liberada(deps, versao)

    status, reaproveitada_de = _status_do_lote(deps, versao)

    if status.suspeitos_conteudo:
        hashes = ", ".join(c.hash_origem[:8] for c in status.suspeitos_conteudo)
        raise RecusaDeInvariante(
            "commits suspeitos de cherry-pick manual com conteudo divergente "
            f"(mesma mensagem e arquivos ja existem no alvo, sem trailer -x): {hashes}. "
            "Confirme manualmente (exclua no estado se ja aplicado) antes de rodar atualizar de novo."
        )

    faltam = status.faltantes

    aplicados: list[CommitRef] = []
    vazios: list[CommitRef] = []
    ja_presentes = len(status.ancestrais)
    t = time.monotonic()
    for indice, c in enumerate(faltam, start=1):
        deps.progresso(Progresso("cherry-pick", indice, len(faltam)))
        outcome = _pick(deps, c.hash_origem)
        if outcome == CherryPickOutcome.VAZIO:
            vazios.append(c)
            continue
        if outcome == CherryPickOutcome.CONFLITO:
            paths = deps.git.conflicted_paths()
            if len(paths) == 0:
                # rerere.autoUpdate resolveu sozinho
                # (docs/decisoes/013-conflito-e-checkpoint.md) - segue o pick. Se a
                # resolucao gravada era "fica como esta no alvo", o --continue
                # devolve VAZIO: e o julgamento que o operador ja fez na
                # primeira vez, replayado, entao entra como commit vazio sem
                # parar o lote.
                if deps.git.continue_cherry_pick() == CherryPickOutcome.VAZIO:
                    deps.git.commit_pick_vazio()
                    vazios.append(c)
                else:
                    aplicados.append(c)
                continue
            return AtualizarResult(
                status=AtualizarStatus.BLOCKED,
                blocked_commit=c.hash_origem,
                arquivos_conflito=paths,
                aplicados=aplicados,
                vazios=vazios,
                ja_presentes=ja_presentes,
                status_versao=status,
                reaproveitada_de=reaproveitada_de,
            )
        aplicados.append(c)
    logger.debug("cherry-pick de %d commits: %.3fs", len(faltam), time.monotonic() - t)

    # O estado veio da verificacao em uso (carimbo valido ou nova), com a presenca
    # de ANTES dos picks; regrava com o lote aplicado para o `estado` das
    # atribuicoes refletir a realidade. Tarefa sem commit nenhum continua
    # pendente: o lote nao entregou nada dela.
    aplicadas = [
        replace(a, estado="aplicado") if a.commits else a
        for a in deps.estado.atribuicoes(deps.repo, versao)
    ]
    deps.estado.substituir_atribuicoes(deps.repo, versao, aplicadas)

    # publica so apos o lote fechar sem conflito (branch remota trava o
    # rebuild, docs/decisoes/010-travas-publicada-e-liberada.md) -
    # um lote BLOCKED fica so local ate resolver e rodar de novo.
    deps.progresso(Progresso("publicando na origin"))
    deps.git.push_branch("origin", deps.versionamento().branch(versao))
    # a worktree e so um checkout local descartavel - o que importa (commits) ja
    # esta na branch e no remoto. use_worktree recria sob demanda. Com
    # worktrees_mantidas > 0 este checkout fica, e o proximo run nao o paga.
    descartar_worktrees(deps, versao)
    return AtualizarResult(
        status=AtualizarStatus.DONE,
        aplicados=aplicados,
        vazios=vazios,
        ja_presentes=ja_presentes,
        status_versao=status,
        reaproveitada_de=reaproveitada_de,
    )


def atualizar_continue(
    deps: Deps, versao: str, *, allow_empty: bool = False
) -> AtualizarResult:
    """Retoma um cherry-pick resolvido manualmente (checkpoint resumivel,
    docs/decisoes/013-conflito-e-checkpoint.md).

    Invocacao nova do CLI, sem contexto em memoria de quais commits do lote ja
    foram aplicados. Nao precisa reconstruir nada a mao: o `atualizar` abaixo
    verifica de novo, porque o pick resolvido mudou o tip da branch e o carimbo
    deixou de valer, e a verificacao reprojeta o estado a partir do git de verdade.

    A recusa por tag e reavaliada aqui, antes do `continue_cherry_pick`: se a
    versao foi liberada enquanto o conflito estava aberto, deixar o pick entrar
    poria um commit na branch de uma versao congelada — a recusa do `atualizar`
    la embaixo chegaria tarde.

    Resolucao que nao deixou alteracao para com `AtualizarStatus.VAZIO` em vez de
    decidir sozinha, e `allow_empty=True` (o operador confirmando) fecha o pick
    como commit vazio. Nao e cerimonia: aqui quem zerou o diff foi uma pessoa, e
    "resolvi mantendo o alvo" e indistinguivel de "resolvi errado e apaguei a
    alteracao". Commit vazio com trailer -x marca o commit como aplicado para
    sempre no oraculo de presenca — se essa for a leitura errada, o erro fica
    invisivel. Quem descarta usa o --abort, que ja existe.
    """
    _recusar_se_liberada(deps, versao)

    deps.progresso(Progresso("retomando o cherry-pick"))
    deps.git.use_worktree(deps.versionamento().branch(versao))
    pendente, ok = deps.git.pending_cherry_pick()
    if not ok:
        raise ErroDeEntrada("nenhum cherry-pick pendente pra continuar")

    if deps.git.continue_cherry_pick() == CherryPickOutcome.VAZIO:
        if not allow_empty:
            return AtualizarResult(
                status=AtualizarStatus.VAZIO, blocked_commit=pendente
            )
        deps.git.commit_pick_vazio()
        resultado = atualizar(deps, versao)
        # O `atualizar` acima abre lote novo e nao sabe deste pick; sem
        # reinjetar, o commit vazio que acabou de entrar na branch nao apareceria
        # em relatorio nenhum.
        return replace(
            resultado,
            vazios=[CommitRef(hash_origem=pendente), *resultado.vazios],
        )
    return atualizar(deps, versao)


def atualizar_abort(deps: Deps, versao: str) -> None:
    """Descarta o cherry-pick pendente sem resolver o `versionamento`: um
    esquema que nao carrega, ou um piso que ele recusa, nao pode impedir o
    operador de sair de um lote travado. A branch sai so das camadas config e
    padrao (`Deps.nomes_abort`), e o GC considera so a worktree atual."""
    branch = aplicar(deps.nomes_abort[0], versao)
    deps.git.use_worktree(branch)
    deps.git.abort_cherry_pick()
    deps.git.worktree_gc(deps.worktrees_mantidas, branch, [branch])
