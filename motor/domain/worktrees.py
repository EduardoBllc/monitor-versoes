"""Politica do GC de worktrees: quem morre, na ordem em que morre."""

from __future__ import annotations


def worktrees_a_remover(
    existentes: list[str], *, mru: list[str], manter: int, atual: str
) -> list[str]:
    """Worktrees de versao a descartar, para o GC do adapter de git.

    `existentes` sao as branches de versao com worktree em disco, da mais
    recente para a mais antiga pelo esquema — o adapter filtra o que nao e
    branch de versao antes de chamar, para nunca propor remover worktree que o
    operador criou na mao. `mru` e a lista de uso recente (mais recente
    primeiro) lida do arquivo local; nome que nao aparece nela cai atras dos
    que aparecem, entre si na ordem recebida. Arquivo ausente ou ilegivel vira
    `mru=[]`, e a ordem degrada para a recebida.

    `atual` sobrevive sempre que `manter >= 1`: e a worktree que a operacao em
    curso acabou de usar, e evicta-la faria o proximo run pagar o checkout de
    novo. Com `manter == 0` nada sobrevive — e o comportamento historico de
    remover a worktree no fim de cada run.
    """
    presentes = list(dict.fromkeys(existentes))
    # dict.fromkeys: mru repetido (arquivo editado na mao) emitiria o mesmo
    # nome duas vezes na lista de remocao, e a segunda remocao falharia.
    conhecidas = list(dict.fromkeys(v for v in mru if v in presentes))
    desconhecidas = [v for v in presentes if v not in conhecidas]
    ordem = conhecidas + desconhecidas
    if manter <= 0:
        return ordem
    sobrevivem = {atual} & set(presentes)
    for v in ordem:
        if len(sobrevivem) >= manter:
            break
        sobrevivem.add(v)
    return [v for v in ordem if v not in sobrevivem]
