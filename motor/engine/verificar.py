"""Porte de internal/engine/verificar.go."""

from __future__ import annotations

import datetime
import logging
import time
from dataclasses import dataclass, replace

from motor.domain.commits import extrair_chamado, ordenar_por_grafo
from motor.domain.reconcile import (
    FatosDoGit,
    atribuicoes_de,
    filtrar_excluidos,
    incluir_julgados,
    reconciliar,
)
from motor.domain.referencia import Referencia
from motor.domain.types import (
    Atribuicao,
    CommitRef,
    ContextoAtribuicao,
    JulgamentoOrfao,
    Presence,
    TargetSet,
    Verificacao,
    VersaoInfo,
    VersionStatus,
)
from motor.engine.deps import Deps
from motor.engine.vigencia import impressao_da_verificacao
from motor.errors import ErroDeEntrada, MotorError
from motor.progresso import Progresso
from motor.services.base_resolver import BaseResolver
from motor.services.catalogo import Catalogo
from motor.services.presence_oracle import PresenceOracle
from motor.services.reconstrutor import varrer
from motor.services.target_resolver import TargetResolver

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextoDoAlvo:
    """O que as passadas de presenca e de conflito consultam: o oraculo do
    run (um so, pelo cache) e o par (base gravada, ref do alvo) que ele cruza.
    """

    deps: Deps
    oracle: PresenceOracle
    base_commit: str
    ref_alvo: str


def culpados_do_conflito(
    ctx: ContextoDoAlvo,
    commit: str,
    parent: str,
    arquivos: list[str],
    ja_aplicados: set[str],
) -> list[str]:
    """Chamados que tocaram as mesmas linhas antes do commit conflitante e que
    nao estao nesta versao — a resposta a "de que alteracao esse cherry-pick
    depende". Atribuicao por *linha*: em arquivo de milhares de linhas, "quem
    mexeu no arquivo" e todo mundo, e a resposta nao informa nada.
    """
    if not arquivos:
        return []
    try:
        por_arquivo = ctx.deps.git.culpados_por_linha(
            ctx.base_commit, parent, commit, arquivos
        )
    except MotorError as e:
        # Mesma politica do oraculo de presenca ("senao -> ausente",
        # docs/decisoes/003-definicao-de-presente.md): o que
        # nao da pra confirmar nao derruba o resto. Atribuicao e diagnostico em
        # cima do conflito — perde-la nao pode custar o proprio conflito.
        logger.debug("atribuicao do conflito em %s falhou: %s", commit, e)
        return []
    chamados: set[str] = set()
    # Resolvida no primeiro culpado candidato, nao antes: conflito sem culpado
    # fora da versao nao passa a exigir padrao de referencia.
    referencia: Referencia | None = None
    for commits in por_arquivo.values():
        for c in commits:
            # Ja dobrado no tip simulado: o `atualizar` aplica esse antes, entao
            # culpa-lo mandaria o operador buscar o que o proprio lote resolve.
            # So a simulacao precisa disto; no `atualizar` o pick ja aplicado
            # leva o trailer -x e sai como presente no oraculo abaixo.
            if c.hash_origem in ja_aplicados:
                continue
            # Culpado que ja esta no alvo nao pode ser a causa da divergencia.
            if (
                ctx.oracle.presente(c.hash_origem, ctx.base_commit, ctx.ref_alvo)
                != Presence.AUSENTE
            ):
                continue
            if referencia is None:
                referencia = ctx.deps.referencia()
            ch = extrair_chamado(c.msg, referencia)
            if ch is not None:
                chamados.add(ch)
    return sorted(chamados)


def ordem_de_aplicacao(deps: Deps, commits: list[CommitRef]) -> list[CommitRef]:
    """A ordem do lote, uma so para o `verificar` simular e o `atualizar`
    aplicar — se divergirem, a previsao de conflito e de outro lote.
    """
    return ordenar_por_grafo(
        commits, deps.git.ordem_topologica([c.hash_origem for c in commits])
    )


@dataclass(frozen=True)
class Situacao:
    """O que o run sabe das versoes do repo depois de conferir as liberadas."""

    #: data de liberacao de cada liberada que o motor ja operou
    datas: dict[str, datetime.datetime]
    #: liberadas pelo criterio em uso ou com `liberada_em` gravada
    liberadas: frozenset[str]
    #: com branch e nao liberadas, em ordem crescente
    abertas: list[str]


def situacao_das_versoes(deps: Deps, catalogo: Catalogo, *, congelar: bool) -> Situacao:
    """Data de liberacao de cada versao que interessa, congelando de passagem o
    que o criterio passou a dar por liberado desde o ultimo run.

    A data vem do repositorio (`Catalogo.data_liberacao`), nao de agora: senao
    registraria quando o comando rodou, nao quando a versao saiu. Ela serve a
    dois donos — o congelamento (docs/decisoes/011-congelamento-no-banco.md) e a
    politica de atribuicao (docs/decisoes/005-alvo-distribuicao-entre-versoes.md),
    que precisa saber se a liberada saiu depois do corte do alvo.

    `liberada_em` gravada vence o criterio: versao com data no estado e liberada
    mesmo que o criterio atual nao a reconheca mais, e a data nunca e
    reescrita (docs/decisoes/026-esquema-e-atribuicao-plugaveis.md). Ja
    congelada, nao paga leitura no git.

    Versao que o motor nunca operou fica fora das datas — nao tem snapshot a
    proteger e nao tem base gravada, logo nao e fonte de alvo. A guarda tambem e
    o que impede uma tag que nao resolve (branch apagada, tag anotada solta) de
    matar um run que nem tem essa versao como alvo.
    """
    pelo_criterio = catalogo.liberadas()
    ordenar = catalogo.versionamento.esquema.ordenar
    datas: dict[str, datetime.datetime] = {}
    novas: dict[str, datetime.datetime] = {}
    candidatas = ordenar(list(pelo_criterio))
    for indice, numero in enumerate(candidatas, start=1):
        deps.progresso(
            Progresso("conferindo versões liberadas", indice, len(candidatas))
        )
        conhecida = deps.estado.versao(deps.repo, numero)
        if conhecida is None:
            continue
        if conhecida.liberada_em is not None:
            datas[numero] = conhecida.liberada_em
            continue
        data = catalogo.data_liberacao(numero)
        datas[numero] = data
        novas[numero] = data
    # O criterio pode ter mudado e deixado de reconhecer uma versao que ja
    # congelou: ela continua liberada, com a data gravada.
    gravadas: set[str] = set()
    for numero in catalogo.com_branch():
        if numero in pelo_criterio:
            continue
        conhecida = deps.estado.versao(deps.repo, numero)
        if conhecida is not None and conhecida.liberada_em is not None:
            datas[numero] = conhecida.liberada_em
            gravadas.add(numero)
    if congelar and novas:
        deps.estado.marcar_liberadas(deps.repo, novas)
    liberadas = frozenset(pelo_criterio | gravadas)
    abertas = [v for v in catalogo.com_branch() if v not in liberadas]
    return Situacao(datas=datas, liberadas=liberadas, abertas=abertas)


def verificar(
    deps: Deps,
    versao: str,
    *,
    manter_worktree: bool = False,
    auditar: bool = False,
) -> VersionStatus:
    """Cruza fonte de tarefas x estado x git e devolve o VersionStatus.

    Por padrao, versao com tag devolve o snapshot congelado. Com ``auditar``,
    recalcula contra a tag sem alterar o snapshot nem criar worktree.
    """
    deps.progresso(Progresso("buscando refs do origin"))

    # Antes de ler as refs, nao depois: `fetch` e o unico ponto em que tag
    # criada em outra maquina entra. Lendo primeiro, o motor decidiria sobre um
    # ref store velho — a versao liberada la fora apareceria como aberta, com
    # `liberada_em` ainda NULL, e o congelamento abaixo seria pulado. O
    # substituir_atribuicoes do fim reescreveria o registro de uma versao que
    # ja saiu, que e exatamente a perda que o congelamento existe para evitar.
    deps.git.fetch("origin")
    return verificar_sem_fetch(
        deps,
        versao,
        manter_worktree=manter_worktree,
        auditar=auditar,
        com_worktree=True,
    )


def verificar_sem_fetch(
    deps: Deps,
    versao: str,
    *,
    manter_worktree: bool,
    auditar: bool,
    com_worktree: bool,
) -> VersionStatus:
    """O `verificar` sem o fetch inicial, para quem já buscou as refs."""
    inicio = time.monotonic()
    # Hora de antes das leituras externas: a validade conta da idade dos dados.
    verificado_em = deps.agora()
    versionamento = deps.versionamento()
    versao = versionamento.esquema.validar(versao)
    catalogo = Catalogo(deps.git, versionamento)

    info: VersaoInfo | None
    if auditar:
        info, situacao = _preparar_auditoria(deps, catalogo, versao)
        ref_alvo = BaseResolver(git=deps.git, catalogo=catalogo).commit_da_versao(
            versao
        )
    else:
        situacao = situacao_das_versoes(deps, catalogo, congelar=True)

        info = deps.estado.versao(deps.repo, versao)
        if info is not None and info.liberada_em is not None:
            return _snapshot_congelado(deps, versao, info.liberada_em)

        if com_worktree:
            preparar_worktree(deps, versao)
        ref_alvo = versionamento.branch(versao)

    base_commit = _base_commit(deps, catalogo, versao, info)
    resolver = _target_resolver(deps)
    # A politica decide de quais versoes vem as tarefas do alvo
    # (docs/decisoes/026-esquema-e-atribuicao-plugaveis.md). `corte` e a data
    # do commit-base gravado — o mesmo que nao se recomputa acima, pelo mesmo
    # motivo.
    corte = deps.git.commit_meta(base_commit).commit_date
    fontes = versionamento.politica.fontes(
        versao,
        ContextoAtribuicao(
            ordenar=versionamento.esquema.ordenar,
            abertas=situacao.abertas,
            liberadas=situacao.datas,
            corte=corte,
            piso=versionamento.piso,
        ),
    )
    resultado = resolver.resolve(versao, fontes, liberadas=situacao.liberadas)
    logger.debug("resolver.resolve: %.3fs", time.monotonic() - inicio)

    exclusoes = deps.estado.exclusoes(deps.repo)
    sem_entrega = deps.estado.sem_entrega(deps.repo)
    julgamentos = deps.estado.julgamentos_orfao(deps.repo)
    ctx = ContextoDoAlvo(deps, PresenceOracle(git=deps.git), base_commit, ref_alvo)
    # A exclusao roda depois e vence o julgamento.
    alvo = filtrar_excluidos(
        incluir_julgados(
            resultado.tasks,
            _orfaos_julgados(ctx, versao, julgamentos, resultado.tasks),
        ),
        exclusoes,
        versao,
    )

    # ANTES de sobrescrever: e o que detecta tarefa desmarcada no rastreador.
    anteriores = deps.estado.atribuicoes(deps.repo, versao)

    todos_os_hashes, candidatos_conflito = _hashes_do_lote(alvo, anteriores)

    t = time.monotonic()
    presentes, suspeitos_conteudo = _presenca(ctx, todos_os_hashes, candidatos_conflito)
    tip, ordem, conflitantes, conflito_causado_por = _simular_conflitos(
        ctx,
        [c for hash_, c in todos_os_hashes.items() if hash_ in candidatos_conflito],
        presentes,
    )
    logger.debug(
        "oraculo de presenca: %.3fs (%d commits)",
        time.monotonic() - t,
        len(todos_os_hashes),
    )

    status = reconciliar(
        replace(resultado, tasks=alvo),
        anteriores,
        sem_entrega,
        FatosDoGit(presentes, conflitantes, suspeitos_conteudo, conflito_causado_por),
    )
    posicao = {c.hash_origem: i for i, c in enumerate(ordem)}
    status.faltantes.sort(key=lambda c: posicao.get(c.hash_origem, len(posicao)))

    if not auditar:
        deps.progresso(Progresso("gravando estado"))
        deps.estado.substituir_atribuicoes(
            deps.repo, versao, atribuicoes_de(alvo, presentes)
        )
        deps.estado.gravar_verificacao(
            deps.repo,
            versao,
            Verificacao(
                tip=tip,
                impressao=impressao_da_verificacao(
                    exclusoes,
                    sem_entrega,
                    julgamentos,
                    deps.identidade_das_entradas(),
                ),
                verificado_em=verificado_em,
                status=status,
            ),
        )

    if not manter_worktree and not auditar:
        descartar_worktrees(deps, versao)
    logger.debug("verificar total: %.3fs", time.monotonic() - inicio)
    return status


def _snapshot_congelado(
    deps: Deps, versao: str, liberada_em: datetime.datetime
) -> VersionStatus:
    """Versao liberada nao recalcula: o alvo dela congelou na tag. Se algo
    ficou de fora, a tarefa e remarcada para a proxima versao
    (docs/decisoes/010-travas-publicada-e-liberada.md).

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


def _preparar_auditoria(
    deps: Deps, catalogo: Catalogo, versao: str
) -> tuple[VersaoInfo, Situacao]:
    info = deps.estado.versao(deps.repo, versao)
    # `congelar=False`: auditoria nao escreve no estado nem na worktree.
    situacao = situacao_das_versoes(deps, catalogo, congelar=False)
    if versao not in situacao.liberadas:
        raise ErroDeEntrada("--auditar exige uma versao liberada")
    if info is None:
        raise ErroDeEntrada("--auditar exige uma versao registrada no estado")
    return info, situacao


def preparar_worktree(deps: Deps, versao: str) -> None:
    deps.progresso(Progresso("preparando worktree"))
    branch = deps.versionamento().branch(versao)
    deps.git.use_worktree(branch)
    if deps.git.remote_branch_exists("origin", branch):
        deps.git.pull_branch("origin", branch)


def descartar_worktrees(deps: Deps, versao: str) -> None:
    """GC das worktrees no fim da operacao, so entre as branches das versoes
    conhecidas (com branch ou liberadas), da mais recente para a mais antiga
    pelo esquema: worktree criada a mao fica. As liberadas entram porque a
    worktree de uma liberada sem branch nasce em detached HEAD da tag e, fora
    da lista, ficaria no disco para sempre."""
    versionamento = deps.versionamento()
    nossas = [
        versionamento.branch(v)
        for v in reversed(Catalogo(deps.git, versionamento).existentes())
    ]
    deps.git.worktree_gc(deps.worktrees_mantidas, versionamento.branch(versao), nossas)


def _base_commit(
    deps: Deps, catalogo: Catalogo, versao: str, info: VersaoInfo | None
) -> str:
    if info is not None:
        # A base gravada e a autoritativa. Recomputar faria a base de uma
        # X.0.0 seguir o tip atual da principal em vez do ponto de corte, e o
        # oraculo passaria a considerar presente tudo que entrou depois.
        return info.base_commit
    # Primeira vez que o motor ve esta versao: resolve e grava a base.
    deps.progresso(Progresso("resolvendo a base da versão"))
    resolvida = BaseResolver(git=deps.git, catalogo=catalogo).resolve(versao)
    deps.estado.registrar_versao(
        deps.repo,
        VersaoInfo(
            numero=versao,
            tipo=catalogo.versionamento.esquema.tipo(versao),
            base_ref=resolvida.ref,
            base_commit=resolvida.commit,
        ),
    )
    return resolvida.commit


def _orfaos_julgados(
    ctx: ContextoDoAlvo,
    versao: str,
    julgamentos: list[JulgamentoOrfao],
    alvo: TargetSet,
) -> dict[str, list[CommitRef]]:
    """Orfaos atuais da versao julgados "pertence a chX", com chX no alvo,
    agrupados por chamado: a outra fonte de commits das tarefas do alvo, ao
    lado da fonte de commits (docs/decisoes/034-julgamento-de-orfao.md).

    So varre quando ha o que aplicar: sem julgamento aplicavel, o `verificar`
    nao paga a varredura nem passa a exigir o padrao de referencia. Julgamento
    de hash que nao e mais orfao (saiu da branch) nao tem efeito, senao viraria
    um faltante que ninguem enxerga na lista de orfaos.
    """
    aplicaveis = {
        j.hash_origem: j.chamado
        for j in julgamentos
        if j.versao_numero == versao and j.chamado is not None and j.chamado in alvo
    }
    if not aplicaveis:
        return {}
    ctx.deps.progresso(Progresso("varrendo órfãos julgados"))
    _, orfaos = varrer(
        ctx.deps.git, ctx.base_commit, ctx.ref_alvo, ctx.deps.referencia()
    )
    julgados: dict[str, list[CommitRef]] = {}
    for o in orfaos:
        chamado = aplicaveis.get(o.hash_origem)
        if chamado is not None:
            julgados.setdefault(chamado, []).append(replace(o, chamado=chamado))
    return julgados


def _target_resolver(deps: Deps) -> TargetResolver:
    if deps.commit_source is None:
        # Bug de montagem, nao erro do operador: o front-end tem de montar a
        # fonte (motor.montagem.montar_commit_source). AssertionError em vez de
        # MotorError porque o main() ja roteia nao-MotorError para traceback, e
        # e traceback que o autor deste bug precisa ver.
        raise AssertionError("Deps.commit_source nao montado")
    return TargetResolver(
        tasks=deps.tasks,
        commits=deps.commit_source,
        progresso=deps.progresso,
    )


def _hashes_do_lote(
    alvo: TargetSet, anteriores: list[Atribuicao]
) -> tuple[dict[str, CommitRef], set[str]]:
    """Todo hash que o run olha, e o subconjunto que e candidato de
    cherry-pick (lado alvo). Hash que so o estado conhecia entra para ter
    presenca apurada, nunca como candidato.
    """
    todos_os_hashes: dict[str, CommitRef] = {}
    candidatos_conflito: set[str] = set()
    for tt in alvo.values():
        for c in tt.commits:
            todos_os_hashes[c.hash_origem] = c
            candidatos_conflito.add(c.hash_origem)
    for a in anteriores:
        for h in a.commits:
            todos_os_hashes.setdefault(h, CommitRef(hash_origem=h))
    return todos_os_hashes, candidatos_conflito


def _presenca(
    ctx: ContextoDoAlvo,
    todos_os_hashes: dict[str, CommitRef],
    candidatos_conflito: set[str],
) -> tuple[dict[str, Presence], list[CommitRef]]:
    presentes: dict[str, Presence] = {}
    suspeitos_conteudo: list[CommitRef] = []
    for indice, (hash_, c) in enumerate(todos_os_hashes.items(), start=1):
        ctx.deps.progresso(
            Progresso("presença dos commits", indice, len(todos_os_hashes))
        )
        p = ctx.oracle.presente(hash_, ctx.base_commit, ctx.ref_alvo)
        presentes[hash_] = p
        # predict_merge e a suspeita por conteudo so fazem sentido para commit
        # que e candidato real de cherry-pick (lado alvo): conflitantes e
        # suspeitos_conteudo sao subconjunto de faltantes (VersionStatus),
        # nunca de commit que so o estado conhecia e sumiu do git.
        if (
            p == Presence.AUSENTE
            and hash_ in candidatos_conflito
            and ctx.oracle.suspeita_por_conteudo(hash_, ctx.base_commit, ctx.ref_alvo)
            is not None
        ):
            suspeitos_conteudo.append(c)

    # Segunda passada, agora com o lote todo resolvido: candidato ausente cujo
    # patch e identico ao de um candidato presente ja teve o conteudo aplicado
    # sob outro hash de origem — cobra-lo mandaria o operador aplicar o que nao
    # tem mais o que aplicar (o pick sairia vazio). O gemeo aparece quando a
    # branch da PR foi rebasada e depois mergeada de volta.
    ja_presentes = {h: p for h, p in presentes.items() if p != Presence.AUSENTE}
    for hash_ in [h for h, p in presentes.items() if p == Presence.AUSENTE]:
        if ctx.oracle.duplicata_de_presente(hash_, ja_presentes):
            presentes[hash_] = Presence.PATCH_ID
    suspeitos_conteudo = [
        c for c in suspeitos_conteudo if presentes[c.hash_origem] == Presence.AUSENTE
    ]
    return presentes, suspeitos_conteudo


def _simular_conflitos(
    ctx: ContextoDoAlvo, candidatos: list[CommitRef], presentes: dict[str, Presence]
) -> tuple[str, list[CommitRef], list[CommitRef], dict[str, list[str]]]:
    git = ctx.deps.git
    # Simula o mesmo lote ordenado que `atualizar` executa. Usar sempre o tip
    # original faz um commit dependente parecer modify/delete quando o pai
    # tambem esta faltando, embora o pai seja aplicado antes dele.
    tip_inicial = tip = git.resolve_ref(ctx.ref_alvo)
    candidatos = ordem_de_aplicacao(ctx.deps, candidatos)
    conflitantes: list[CommitRef] = []
    conflito_causado_por: dict[str, list[str]] = {}
    ja_simulados: set[str] = set()
    for indice, c in enumerate(candidatos, start=1):
        ctx.deps.progresso(Progresso("simulando conflitos", indice, len(candidatos)))
        if presentes[c.hash_origem] != Presence.AUSENTE:
            continue
        meta = git.commit_meta(c.hash_origem)
        pred = git.predict_merge(meta.parent, tip, c.hash_origem)
        if pred.conflita:
            conflitantes.append(c)
            culpados = culpados_do_conflito(
                ctx, meta.hash_origem, meta.parent, pred.arquivos_conflito, ja_simulados
            )
            if culpados:
                conflito_causado_por[c.hash_origem] = culpados
            break
        ja_simulados.add(c.hash_origem)
        tip = pred.arvore_resultante
    return tip_inicial, candidatos, conflitantes, conflito_causado_por
