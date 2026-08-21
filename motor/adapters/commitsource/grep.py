"""GrepCommitSource: descobre commits varrendo mensagens de master.

Move a lógica que vivia no TargetResolver — uma chamada só de `git log`
com o --grep de todos os chamados juntos (git faz OR entre --grep),
depois match exato por word-boundary (search_commits só traz candidatos
brutos). Frágil por natureza: depende do dev ter escrito o ID certo na
mensagem. É a fonte de fallback; o Bitbucket (PR) é a primária.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from motor.domain.commits import match_exato, ordenar_por_data
from motor.domain.types import CommitRef
from motor.ports import GitRepo
from motor.progresso import Progresso, RelatorProgresso, silencioso


@dataclass
class GrepCommitSource:
    git: GitRepo
    ref: str = "origin/master"
    progresso: RelatorProgresso = silencioso

    def resolve(self, chamados: list[str]) -> dict[str, list[CommitRef]]:
        if not chamados:
            return {}

        # Varredura unica: nao ha o que contar, so avisar que comecou.
        self.progresso(Progresso("commits dos chamados no hist\u00f3rico"))
        candidatos = self.git.search_commits(["ch" + c for c in chamados], self.ref)

        resultado: dict[str, list[CommitRef]] = {}
        for chamado in chamados:
            commits = ordenar_por_data(match_exato(candidatos, chamado))
            if not commits:
                continue
            # search_commits nao sabe de chamado — carimba aqui.
            resultado[chamado] = [replace(c, chamado=chamado) for c in commits]
        return resultado
