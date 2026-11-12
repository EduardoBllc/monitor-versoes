"""Reconstrucao do estado a partir dos trailers de cherry-pick no git.

O trailer `-x` e o backbone duravel: o estado no banco e uma projecao rapida
por cima dele. Se o banco for perdido, isto regenera as atribuicoes.
"""

from __future__ import annotations

from collections.abc import Mapping

from motor.domain.commits import extrair_chamado
from motor.domain.referencia import Referencia
from motor.domain.types import Atribuicao, CommitRef
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


def varrer(
    git: GitRepo, base_commit: str, branch: str, referencia: Referencia
) -> tuple[dict[str, list[str]], list[CommitRef]]:
    """Varre base..branch e separa os hashes de origem por chamado dos orfaos.

    Orfao e commit cuja mensagem de origem nao tem referencia de tarefa: nao e
    atribuivel a tarefa nenhuma sem julgamento humano. Os dois lados saem sem
    repeticao e em ordem de hash. Os orfaos vem com os metadados do commit de
    ORIGEM, lidos num `commits_meta` so: o `commits_in_range` nao traz o
    `parent` e a data dele e a do autor, nao a do committer.
    """
    try:
        commits = git.commits_in_range(base_commit, branch)
    except MotorError as e:
        e.add_note("varrendo commits")
        raise

    por_chamado: dict[str, set[str]] = {}
    orfaos: dict[str, CommitRef] = {}

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

        chamado = extrair_chamado(meta.msg, referencia)
        if chamado is None:
            orfaos.setdefault(origem, meta)
            continue
        por_chamado.setdefault(chamado, set()).add(origem)

    hashes = sorted(orfaos)
    metas = git.commits_meta(hashes) if hashes else {}
    return (
        {chamado: sorted(h) for chamado, h in por_chamado.items()},
        [metas.get(h, orfaos[h]) for h in hashes],
    )


def reconstruir_atribuicoes(
    git: GitRepo,
    base_commit: str,
    branch: str,
    referencia: Referencia,
    julgamentos: Mapping[str, str | None] | None = None,
) -> tuple[list[Atribuicao], list[str]]:
    """Varre base..branch e reagrupa por chamado, aplicando os julgamentos.

    `julgamentos` e hash de origem -> chamado (None = nao pertence a nenhum),
    so da versao varrida. Devolve (atribuicoes, pendentes): orfao julgado com
    chamado entra na atribuicao dele, julgado "nenhum" sai, e so o que nao foi
    julgado fica pendente.
    """
    julgados = julgamentos or {}
    por_chamado, orfaos = varrer(git, base_commit, branch, referencia)
    agrupados = {chamado: set(h) for chamado, h in por_chamado.items()}
    pendentes: list[str] = []
    for o in orfaos:
        if o.hash_origem not in julgados:
            pendentes.append(o.hash_origem)
            continue
        chamado = julgados[o.hash_origem]
        if chamado is not None:
            agrupados.setdefault(chamado, set()).add(o.hash_origem)

    atribuicoes = [
        Atribuicao(
            chamado=chamado, marcada="", estado="aplicado", commits=sorted(hashes)
        )
        for chamado, hashes in sorted(agrupados.items())
    ]
    return atribuicoes, pendentes
