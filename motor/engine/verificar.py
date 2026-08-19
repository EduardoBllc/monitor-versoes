"""Porte de internal/engine/verificar.go."""

from __future__ import annotations

import datetime
import logging
import time
from dataclasses import replace

from motor.adapters.commitsource.bitbucket import (
    BitbucketPRCommitSource,
    parse_workspace_repo,
)
from motor.adapters.commitsource.chain import ChainCommitSource
from motor.adapters.commitsource.grep import GrepCommitSource
from motor.domain.reconcile import atribuicoes_de, filtrar_excluidos, reconciliar
from motor.domain.types import CommitRef, Presence, VersaoInfo, VersionStatus
from motor.domain.version import chave, inferir_tipo, versoes_abertas
from motor.engine.deps import Deps
from motor.ports import CommitSource
from motor.services.base_resolver import BaseResolver
from motor.services.presence_oracle import PresenceOracle
from motor.services.target_resolver import TargetResolver

logger = logging.getLogger(__name__)


def _montar_commit_source(deps: Deps) -> CommitSource:
    """Grep em master é o fallback sempre disponível. Com token do Bitbucket,
    a PR (merged) vira a fonte primária: ordem = prioridade (§CommitSource).
    """
    grep = GrepCommitSource(git=deps.git)
    if not deps.bitbucket_token:
        return grep
    workspace, repo = parse_workspace_repo(deps.git.remote_url("origin"))
    pr = BitbucketPRCommitSource(
        token=deps.bitbucket_token,
        email=deps.bitbucket_email,
        workspace=workspace,
        repo=repo,
        git=deps.git,
    )
    return ChainCommitSource(sources=[pr, grep])


def verificar(deps: Deps, versao: str) -> VersionStatus:
    """Cruza Tickio x estado x git e devolve o VersionStatus.

    Versao com tag e congelada: devolve o snapshot do banco sem recalcular
    nada. Nao muta dados do usuario — so avanca a branch local ate o que ja
    esta publicado, para nao cruzar contra estado desatualizado.
    """
    inicio = time.monotonic()

    # Antes de ler as refs, nao depois: `fetch` e o unico ponto em que tag
    # criada em outra maquina entra. Lendo primeiro, o motor decidiria sobre um
    # ref store velho — a versao liberada la fora apareceria como aberta, com
    # `liberada_em` ainda NULL, e o congelamento abaixo seria pulado. O
    # substituir_atribuicoes do fim reescreveria o registro de uma versao que
    # ja saiu, que e exatamente a perda que o congelamento existe para evitar.
    deps.git.fetch("origin")

    todas = deps.git.list_version_branches()
    tags = deps.git.list_version_tags()
    abertas = versoes_abertas(todas, tags)

    # Congela o que ganhou tag desde o ultimo run. A data e a do commit
    # apontado pela tag, nao a de agora: senao registraria quando o comando
    # rodou, nao quando a versao foi liberada.
    liberadas: dict[str, datetime.datetime] = {}
    for numero in tags:
        conhecida = deps.estado.versao(deps.repo, numero)
        # Versao que o motor nunca operou nao tem snapshot a proteger.
        if conhecida is not None and conhecida.liberada_em is None:
            meta = deps.git.commit_meta(deps.git.resolve_ref(f"refs/tags/{numero}"))
            liberadas[numero] = meta.commit_date
    if liberadas:
        deps.estado.marcar_liberadas(deps.repo, liberadas)

    info = deps.estado.versao(deps.repo, versao)
    if info is not None and info.liberada_em is not None:
        return _snapshot_congelado(deps, versao, info.liberada_em)

    deps.git.use_worktree(versao)
    if deps.git.remote_branch_exists("origin", versao):
        deps.git.pull_branch("origin", versao)

    if info is None:
        # Primeira vez que o motor ve esta versao: resolve e grava a base.
        resolvida = BaseResolver(git=deps.git).resolve(versao)
        deps.estado.registrar_versao(
            deps.repo,
            VersaoInfo(
                numero=versao,
                tipo=inferir_tipo(versao),
                base_ref=resolvida.ref,
                base_commit=resolvida.commit,
            ),
        )
        base_commit = resolvida.commit
    else:
        # A base gravada e a autoritativa. Recomputar faria a base de uma
        # X.0.0 seguir o tip atual do master em vez do ponto de corte, e o
        # oraculo passaria a considerar presente tudo que entrou depois.
        base_commit = info.base_commit

    fonte = deps._commit_source or _montar_commit_source(deps)
    resolver = TargetResolver(tasks=deps.tasks, commits=fonte)
    resultado = resolver.resolve(versao, sorted({*abertas, versao}, key=chave))
    logger.debug("resolver.resolve: %.3fs", time.monotonic() - inicio)

    alvo = filtrar_excluidos(
        resultado.tasks, deps.estado.exclusoes(deps.repo), versao
    )

    # ANTES de sobrescrever: e o que detecta tarefa desmarcada no Tickio.
    anteriores = deps.estado.atribuicoes(deps.repo, versao)

    todos_os_hashes: dict[str, CommitRef] = {}
    candidatos_conflito: set[str] = set()
    for tt in alvo.values():
        for c in tt.commits:
            todos_os_hashes[c.hash_origem] = c
            candidatos_conflito.add(c.hash_origem)
    for a in anteriores:
        for h in a.commits:
            todos_os_hashes.setdefault(h, CommitRef(hash_origem=h))

    oracle = PresenceOracle(git=deps.git)
    tip = deps.git.resolve_ref(versao)

    t = time.monotonic()
    presentes: dict[str, Presence] = {}
    conflitantes: list[CommitRef] = []
    suspeitos_conteudo: list[CommitRef] = []
    for hash_, c in todos_os_hashes.items():
        p = oracle.presente(hash_, base_commit, versao)
        presentes[hash_] = p
        # predict_merge e a suspeita por conteudo so fazem sentido para commit
        # que e candidato real de cherry-pick (lado alvo): conflitantes e
        # suspeitos_conteudo sao subconjunto de faltantes (VersionStatus),
        # nunca de commit que so o estado conhecia e sumiu do git.
        if p == Presence.AUSENTE and hash_ in candidatos_conflito:
            if oracle.suspeita_por_conteudo(hash_, base_commit, versao) is not None:
                suspeitos_conteudo.append(c)
            meta = deps.git.commit_meta(hash_)
            pred = deps.git.predict_merge(meta.parent, tip, hash_)
            if pred.conflita:
                conflitantes.append(c)
    logger.debug(
        "oraculo de presenca: %.3fs (%d commits)",
        time.monotonic() - t,
        len(todos_os_hashes),
    )

    status = reconciliar(
        replace(resultado, tasks=alvo),
        anteriores,
        deps.estado.sem_entrega(deps.repo),
        presentes,
        conflitantes,
        suspeitos_conteudo,
    )

    deps.estado.substituir_atribuicoes(
        deps.repo, versao, atribuicoes_de(alvo, presentes)
    )

    logger.debug("verificar total: %.3fs", time.monotonic() - inicio)
    return status


def _snapshot_congelado(
    deps: Deps, versao: str, liberada_em: datetime.datetime
) -> VersionStatus:
    """Versao liberada nao recalcula: o alvo dela congelou na tag. Se algo
    ficou de fora, a tarefa e remarcada para a proxima versao (spec §2).

    Carrega a data de liberacao e os chamados: esta e a unica superficie de
    leitura do que so o banco registra, e sem elas o snapshot sai identico ao
    de uma versao verde em construcao (inclusive "verde: True" quando esta
    vazio, porque all([]) e True).
    """
    anteriores = deps.estado.atribuicoes(deps.repo, versao)
    return VersionStatus(
        verde=all(a.estado == "aplicado" for a in anteriores),
        estado_integro=True,
        liberada_em=liberada_em,
        chamados=sorted(a.chamado for a in anteriores),
    )
