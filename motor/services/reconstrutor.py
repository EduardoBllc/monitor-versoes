"""Reconstrucao do estado a partir dos trailers de cherry-pick no git.

O trailer `-x` e o backbone duravel: o estado no banco e uma projecao rapida
por cima dele. Se o banco for perdido, isto regenera as atribuicoes.
"""

from __future__ import annotations

from motor.domain.commits import extrair_chamado
from motor.domain.types import Atribuicao
from motor.errors import MotorError
from motor.ports import GitRepo

_MARCA = "(cherry picked from commit "


def extrair_trailer(msg: str) -> str | None:
    i = msg.find(_MARCA)
    if i < 0:
        return None
    resto = msg[i + len(_MARCA) :]
    fim = resto.find(")")
    return None if fim < 0 else resto[:fim]


def reconstruir_atribuicoes(
    git: GitRepo, base_commit: str, branch: str
) -> tuple[list[Atribuicao], list[str]]:
    """Varre base..branch e reagrupa por chamado.

    Devolve (atribuicoes, orfaos) — orfao e commit sem `ch<num>` na mensagem,
    que nao e atribuivel a tarefa nenhuma e precisa de julgamento humano.
    """
    try:
        commits = git.commits_in_range(base_commit, branch)
    except MotorError as e:
        e.add_note("varrendo commits")
        raise

    por_chamado: dict[str, list[str]] = {}
    orfaos: list[str] = []

    for c in commits:
        origem = extrair_trailer(c.msg)
        if origem is None:
            # commit direto na branch: ele mesmo e a origem
            origem, meta = c.hash_origem, c
        else:
            try:
                meta = git.commit_meta(origem)
            except MotorError:
                continue  # origem sumiu do historico

        chamado = extrair_chamado(meta.msg)
        if chamado is None:
            orfaos.append(origem)
            continue
        por_chamado.setdefault(chamado, []).append(origem)

    atribuicoes = [
        Atribuicao(
            chamado=chamado, marcada="", estado="aplicado", commits=sorted(hashes)
        )
        for chamado, hashes in sorted(por_chamado.items())
    ]
    return atribuicoes, sorted(set(orfaos))
