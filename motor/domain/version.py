"""Compatibilidade: delega aos esquemas ate os consumidores migrarem."""

from __future__ import annotations

import datetime

from motor.domain.types import VersionType
from motor.esquemas import _xyz
from motor.esquemas.vendabem import VendaBem


def inferir_tipo(numero: str) -> VersionType:
    return VersionType[(VendaBem().tipo(numero) or "").upper()]


def inferir_base(numero: str, versoes_existentes: list[str]) -> str:
    """Base de uma versao (docs/decisoes/009-inferencia-de-base.md)."""
    return VendaBem().base(numero, versoes_existentes, "master")


def chave(numero: str) -> tuple[int, int, int]:
    return _xyz.parse(numero)


def validar_versao(valor: str) -> str:
    """Numero X.Y.Z, como o motor ordena versoes."""
    return _xyz.validar(valor)


def versoes_abertas(todas: list[str], tags: list[str]) -> list[str]:
    """Em construcao = existe como versao e nao tem tag homonima.

    `todas` vem de GitRepo.list_version_branches(), que ja devolve
    refs/heads/ UNIAO refs/tags/ filtrado por X.Y.Z; `tags` vem de
    list_version_tags(). A diferenca e o conjunto aberto.
    """
    return sorted(set(todas) - set(tags), key=chave)


def fontes_de_alvo(
    alvo: str, candidatas: list[str], piso: str | None = None
) -> list[str]:
    """Versoes cujas tarefas caem no alvo: candidatas entre o piso e o alvo.

    E a regra de distribuicao vista pelo lado da versao
    (docs/decisoes/005-alvo-distribuicao-entre-versoes.md). Quem monta
    `candidatas` e o chamador — abertas mais o que `liberadas_no_alvo` devolve.
    O piso vem da config do projeto (`[versao] piso`): descarta branch legada sem
    tag, que o Tickio nao conhece e responderia 404. Sem piso, nada e cortado.
    """
    k = chave(alvo)
    if piso is None:
        return [v for v in candidatas if chave(v) <= k]
    corte = chave(piso)
    return [v for v in candidatas if corte <= chave(v) <= k]


def liberadas_no_alvo(
    alvo: str,
    datas_das_tags: dict[str, datetime.datetime],
    corte: datetime.datetime,
) -> list[str]:
    """Liberadas que continuam sendo fonte de alvo de `alvo`
    (docs/decisoes/005-alvo-distribuicao-entre-versoes.md).

    A liberada sai do conjunto aberto, e a premissa era que o conteudo dela
    chegava por ancestralidade da base. Isso vale para `X.Y.0` sobre
    `X.(Y-1).0`, e **nao** vale para `X.0.0`, cuja base e o master no ponto de
    corte: entrega que virou tag depois desse corte nunca foi herdada. Uma
    liberada nessas condicoes volta a ser fonte, e o oraculo de presenca decide
    commit por commit o que ainda falta.

    `corte` e a data do commit-base de `alvo` — o estado ja a guarda, entao nao
    ha ponto de corte a recomputar. Tag exatamente no corte fica fora: e o caso
    da ajustada cortada da anterior ja liberada, cujo conteudo e ancestral.
    """
    k = chave(alvo)
    return sorted(
        (n for n, data in datas_das_tags.items() if chave(n) <= k and data > corte),
        key=chave,
    )


def worktrees_a_remover(
    existentes: list[str], *, mru: list[str], manter: int, atual: str
) -> list[str]:
    """Worktrees de versao a descartar, para o GC do adapter de git.

    `existentes` sao numeros X.Y.Z — o adapter filtra o que nao for versao
    antes de chamar, para nunca propor remover worktree que o operador criou
    na mao. `mru` e a lista de uso recente (mais recente primeiro) lida do
    arquivo local; nome que nao aparece nela cai atras dos que aparecem, entre
    si por semver desc. Arquivo ausente ou ilegivel viram `mru=[]`, e a ordem
    degrada para semver puro.

    `atual` sobrevive sempre que `manter >= 1`: e a worktree que a operacao em
    curso acabou de usar, e evicta-la faria o proximo run pagar o checkout de
    novo. Com `manter == 0` nada sobrevive — e o comportamento historico de
    remover a worktree no fim de cada run.
    """
    presentes = set(existentes)
    # dict.fromkeys: mru repetido (arquivo editado na mao) emitiria o mesmo
    # nome duas vezes na lista de remocao, e a segunda remocao falharia.
    conhecidas = list(dict.fromkeys(v for v in mru if v in presentes))
    desconhecidas = sorted(presentes - set(conhecidas), key=chave, reverse=True)
    ordem = conhecidas + desconhecidas
    if manter <= 0:
        return ordem
    sobrevivem = {atual} & presentes
    for v in ordem:
        if len(sobrevivem) >= manter:
            break
        sobrevivem.add(v)
    return [v for v in ordem if v not in sobrevivem]
