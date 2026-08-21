"""Porte de internal/engine/verificar.go."""

from __future__ import annotations

import datetime
import logging
import time
from dataclasses import replace

from motor.domain.commits import extrair_chamado, ordenar_por_data
from motor.domain.reconcile import atribuicoes_de, filtrar_excluidos, reconciliar
from motor.domain.types import CommitRef, Presence, VersaoInfo, VersionStatus
from motor.domain.version import chave, inferir_tipo, versoes_abertas
from motor.engine.deps import Deps
from motor.errors import MotorError
from motor.progresso import Progresso
from motor.services.base_resolver import BaseResolver
from motor.services.presence_oracle import PresenceOracle
from motor.services.target_resolver import TargetResolver

logger = logging.getLogger(__name__)


def _culpados_do_conflito(
    deps: Deps,
    oracle: PresenceOracle,
    base_commit: str,
    ref_alvo: str,
    meta: CommitRef,
    arquivos: list[str],
    ja_simulados: set[str],
) -> list[str]:
    """Chamados que tocaram as mesmas linhas antes do commit conflitante e que
    nao estao nesta versao — a resposta a "de que alteracao esse cherry-pick
    depende". Atribuicao por *linha*: em arquivo de milhares de linhas, "quem
    mexeu no arquivo" e todo mundo, e a resposta nao informa nada.
    """
    if not arquivos:
        return []
    try:
        por_arquivo = deps.git.culpados_por_linha(
            base_commit, meta.parent, meta.hash_origem, arquivos
        )
    except MotorError as e:
        # Mesma politica do oraculo de presenca (§2 "senao -> ausente"): o que
        # nao da pra confirmar nao derruba o resto. Atribuicao e diagnostico em
        # cima do conflito — perde-la nao pode custar o proprio conflito.
        logger.debug("atribuicao do conflito em %s falhou: %s", meta.hash_origem, e)
        return []
    chamados: set[str] = set()
    for commits in por_arquivo.values():
        for c in commits:
            # Ja dobrado no tip simulado: o `atualizar` aplica esse antes, entao
            # culpa-lo mandaria o operador buscar o que o proprio lote resolve.
            if c.hash_origem in ja_simulados:
                continue
            # Culpado que ja esta no alvo nao pode ser a causa da divergencia.
            if oracle.presente(c.hash_origem, base_commit, ref_alvo) != Presence.AUSENTE:
                continue
            ch = extrair_chamado(c.msg)
            if ch is not None:
                chamados.add(ch)
    return sorted(chamados)


def verificar(
    deps: Deps,
    versao: str,
    *,
    manter_worktree: bool = False,
    auditar: bool = False,
) -> VersionStatus:
    """Cruza Tickio x estado x git e devolve o VersionStatus.

    Por padrao, versao com tag devolve o snapshot congelado. Com ``auditar``,
    recalcula contra a tag sem alterar o snapshot nem criar worktree.
    """
    inicio = time.monotonic()

    deps.progresso(Progresso("buscando refs do origin"))

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

    if auditar:
        info = deps.estado.versao(deps.repo, versao)
        if versao not in tags:
            raise MotorError("--auditar exige uma versao liberada")
        if info is None:
            raise MotorError("--auditar exige uma versao registrada no estado")
        ref_alvo = deps.git.resolve_ref(f"refs/tags/{versao}")
    else:
        # Congela o que ganhou tag desde o ultimo run. A data e a do commit
        # apontado pela tag, nao a de agora: senao registraria quando o comando
        # rodou, nao quando a versao foi liberada.
        liberadas: dict[str, datetime.datetime] = {}
        for indice, numero in enumerate(tags, start=1):
            deps.progresso(
                Progresso("conferindo tags liberadas", indice, len(tags))
            )
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

        deps.progresso(Progresso("preparando worktree"))
        deps.git.use_worktree(versao)
        if deps.git.remote_branch_exists("origin", versao):
            deps.git.pull_branch("origin", versao)
        ref_alvo = versao

    if info is None:
        # Primeira vez que o motor ve esta versao: resolve e grava a base.
        deps.progresso(Progresso("resolvendo a base da vers\u00e3o"))
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

    if deps.commit_source is None:
        # Bug de montagem, nao erro do operador: o front-end tem de montar a
        # fonte (motor.montagem.montar_commit_source). Nomear isso aqui e mais
        # barato que um AttributeError vindo de dentro do TargetResolver.
        raise MotorError("Deps.commit_source nao montado")
    resolver = TargetResolver(
        tasks=deps.tasks, commits=deps.commit_source, progresso=deps.progresso
    )
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
    t = time.monotonic()
    presentes: dict[str, Presence] = {}
    suspeitos_conteudo: list[CommitRef] = []
    for indice, (hash_, c) in enumerate(todos_os_hashes.items(), start=1):
        deps.progresso(
            Progresso("presen\u00e7a dos commits", indice, len(todos_os_hashes))
        )
        p = oracle.presente(hash_, base_commit, ref_alvo)
        presentes[hash_] = p
        # predict_merge e a suspeita por conteudo so fazem sentido para commit
        # que e candidato real de cherry-pick (lado alvo): conflitantes e
        # suspeitos_conteudo sao subconjunto de faltantes (VersionStatus),
        # nunca de commit que so o estado conhecia e sumiu do git.
        if p == Presence.AUSENTE and hash_ in candidatos_conflito:
            if oracle.suspeita_por_conteudo(hash_, base_commit, ref_alvo) is not None:
                suspeitos_conteudo.append(c)

    # Simula o mesmo lote ordenado que `atualizar` executa. Usar sempre o tip
    # original faz um commit dependente parecer modify/delete quando o pai
    # tambem esta faltando, embora o pai seja aplicado antes dele.
    tip = deps.git.resolve_ref(ref_alvo)
    candidatos = ordenar_por_data(
        [c for hash_, c in todos_os_hashes.items() if hash_ in candidatos_conflito]
    )
    conflitantes: list[CommitRef] = []
    conflito_causado_por: dict[str, list[str]] = {}
    ja_simulados: set[str] = set()
    for indice, c in enumerate(candidatos, start=1):
        deps.progresso(
            Progresso("simulando conflitos", indice, len(candidatos))
        )
        if presentes[c.hash_origem] != Presence.AUSENTE:
            continue
        meta = deps.git.commit_meta(c.hash_origem)
        pred = deps.git.predict_merge(meta.parent, tip, c.hash_origem)
        if pred.conflita:
            conflitantes.append(c)
            culpados = _culpados_do_conflito(
                deps,
                oracle,
                base_commit,
                ref_alvo,
                meta,
                pred.arquivos_conflito,
                ja_simulados,
            )
            if culpados:
                conflito_causado_por[c.hash_origem] = culpados
            break
        ja_simulados.add(c.hash_origem)
        tip = pred.arvore_resultante
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
        conflito_causado_por,
    )

    if not auditar:
        deps.progresso(Progresso("gravando estado"))
        deps.estado.substituir_atribuicoes(
            deps.repo, versao, atribuicoes_de(alvo, presentes)
        )

    if not manter_worktree and not auditar:
        deps.git.worktree_gc(deps.worktrees_mantidas, versao)
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
