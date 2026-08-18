"""Cruzamento das tres fontes: Tickio (alvo) x estado x git."""

from __future__ import annotations

from dataclasses import replace

from motor.domain.types import (
    Alvo,
    Atribuicao,
    CommitRef,
    Exclusion,
    Presence,
    TargetSet,
    VersionStatus,
)


def filtrar_excluidos(
    alvo: TargetSet, excluidos: list[Exclusion], versao: str
) -> TargetSet:
    """Tira do alvo os commits marcados como excluidos.

    `versao_numero` None vale para todo o repo (ex.: commit revertido); com
    valor, so para aquela versao. Sem isso, todo verificar reportaria o mesmo
    falso-positivo para sempre.
    """
    fora = {
        e.hash_origem
        for e in excluidos
        if e.versao_numero is None or e.versao_numero == versao
    }
    return {
        chamado: replace(
            tt, commits=[c for c in tt.commits if c.hash_origem not in fora]
        )
        for chamado, tt in alvo.items()
    }


def diff_tasks(
    alvo: TargetSet, anteriores: list[Atribuicao]
) -> tuple[list[str], list[str]]:
    """Diferenca simetrica entre o alvo de agora e o estado gravado no run
    anterior. E o que detecta tarefa desmarcada no Tickio — comparar depois de
    sobrescrever apagaria a propria evidencia.
    """
    antes = {a.chamado for a in anteriores}
    novas = [ch for ch, tt in alvo.items() if ch not in antes and tt.commits]
    removidas = [ch for ch in antes if ch not in alvo]
    return sorted(novas), sorted(removidas)


def atribuicoes_de(
    alvo: TargetSet, presentes: dict[str, Presence]
) -> list[Atribuicao]:
    """Projeta o alvo resolvido no formato que vai para o estado."""
    return [
        Atribuicao(
            chamado=tt.chamado,
            marcada=tt.marcada,
            estado=(
                "aplicado"
                if tt.commits
                and all(
                    presentes.get(c.hash_origem, Presence.AUSENTE) != Presence.AUSENTE
                    for c in tt.commits
                )
                else "pendente"
            ),
            commits=[c.hash_origem for c in tt.commits],
        )
        for tt in alvo.values()
    ]


def reconciliar(
    alvo: Alvo,
    anteriores: list[Atribuicao],
    sem_entrega: dict[str, str],
    presentes: dict[str, Presence],
    conflitantes: list[CommitRef],
    suspeitos_conteudo: list[CommitRef] = (),
) -> VersionStatus:
    """Produz o VersionStatus. Funcao pura: `presentes`, `conflitantes` e
    `suspeitos_conteudo` chegam pre-computados pelo chamador.
    """
    novas, removidas = diff_tasks(alvo.tasks, anteriores)

    faltantes: list[CommitRef] = []
    ancestrais: list[CommitRef] = []
    for tt in alvo.tasks.values():
        for c in tt.commits:
            if presentes.get(c.hash_origem, Presence.AUSENTE) == Presence.AUSENTE:
                faltantes.append(c)
            else:
                ancestrais.append(c)

    # So atribuicao aplicada pode ter commit "sumido": pendente e commit que
    # ainda nao foi cherry-pickado, entao estar ausente do alvo e o normal —
    # contar isso diria "estado divergente do git" (estado corrompido) numa
    # versao recem-criada, mandando o operador investigar o que nao existe.
    sumidos = sorted(
        {
            h
            for a in anteriores
            if a.estado == "aplicado"
            for h in a.commits
            if presentes.get(h, Presence.AUSENTE) == Presence.AUSENTE
        }
    )
    estado_integro = not sumidos

    # Tarefa marcada sem nenhum commit achado nao pode passar despercebida
    # (falso-verde). So sai da lista se reconhecida em sem_entrega.
    sem_commits = sorted(
        ch for ch, tt in alvo.tasks.items() if not tt.commits and ch not in sem_entrega
    )

    verde = (
        not novas
        and not removidas
        and estado_integro
        and not faltantes
        and not sem_commits
        and not alvo.ambiguas
    )

    return VersionStatus(
        verde=verde,
        tasks_novas=novas,
        tasks_removidas=removidas,
        tasks_ambiguas=list(alvo.ambiguas),
        estado_integro=estado_integro,
        commits_sumidos=sumidos,
        faltantes=faltantes,
        ancestrais=ancestrais,
        conflitantes=conflitantes,
        suspeitos_conteudo=list(suspeitos_conteudo),
        tasks_sem_commits=sem_commits,
    )
