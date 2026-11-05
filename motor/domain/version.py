"""Compatibilidade: delega aos esquemas ate os consumidores migrarem."""

from __future__ import annotations

import datetime

from motor.atribuicoes import ate_o_alvo, liberadas_apos_corte
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
    return ate_o_alvo(_xyz.ordenar, candidatas, alvo, piso)


def liberadas_no_alvo(
    alvo: str,
    datas_das_tags: dict[str, datetime.datetime],
    corte: datetime.datetime,
) -> list[str]:
    return liberadas_apos_corte(_xyz.ordenar, alvo, datas_das_tags, corte)


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
