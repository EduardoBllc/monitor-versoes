"""Porte de internal/domain/version.go."""

from __future__ import annotations

from motor.domain.types import VersionType
from motor.errors import ErroDeEntrada, NaoEncontrado


def _parse_versao(numero: str) -> tuple[int, int, int]:
    partes = numero.split(".")
    if len(partes) != 3:
        raise ErroDeEntrada(f'versao "{numero}": esperado formato X.Y.Z')
    nums = []
    for p in partes:
        try:
            n = int(p)
        except ValueError as e:
            raise ErroDeEntrada(f'versao "{numero}": componente "{p}" invalido') from e
        if n < 0:
            raise ErroDeEntrada(f'versao "{numero}": componente "{p}" invalido')
        nums.append(n)
    return nums[0], nums[1], nums[2]


def inferir_tipo(numero: str) -> VersionType:
    _, y, z = _parse_versao(numero)
    if y == 0 and z == 0:
        return VersionType.FECHADA
    if z == 0:
        return VersionType.AJUSTADA
    return VersionType.CLIENTE


def inferir_base(numero: str, versoes_existentes: list[str]) -> str:
    """Resolve a base de uma versao (§7). versoes_existentes e a lista de
    branches de versao ja existentes (ex.: vindas de GitRepo.list_version_branches).
    """
    x, y, z = _parse_versao(numero)
    if y == 0 and z == 0:
        return "master"
    if z == 0:
        for cand in range(y - 1, -1, -1):
            candidato = f"{x}.{cand}.0"
            if candidato in versoes_existentes:
                return candidato
        raise NaoEncontrado(f"nenhuma base X.Y.0 encontrada abaixo de {numero}")
    candidato = f"{x}.{y}.{z - 1}"
    if candidato in versoes_existentes:
        return candidato
    return f"{x}.{y}.0"


def chave(numero: str) -> tuple[int, int, int]:
    """Ordem semver. Existe porque ordenacao textual erra em '13.9.0' vs
    '13.10.0' — o unico bug de ordenacao que nao aparece nos testes de
    fixture pequeno e aparece em producao no mes seguinte.
    """
    return _parse_versao(numero)


def versoes_abertas(todas: list[str], tags: list[str]) -> list[str]:
    """Em construcao = existe como versao e nao tem tag homonima.

    `todas` vem de GitRepo.list_version_branches(), que ja devolve
    refs/heads/ UNIAO refs/tags/ filtrado por X.Y.Z; `tags` vem de
    list_version_tags(). A diferenca e o conjunto aberto.
    """
    return sorted(set(todas) - set(tags), key=chave)


def fontes_de_alvo(alvo: str, abertas: list[str]) -> list[str]:
    """Versoes cujas tarefas caem no alvo: abertas entre 13.0.0 e o alvo.

    E a regra de distribuicao vista pelo lado da versao (spec §2).
    """
    corte = chave("13.0.0")
    k = chave(alvo)
    return [v for v in abertas if corte <= chave(v) <= k]


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
