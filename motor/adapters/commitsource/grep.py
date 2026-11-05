"""GrepCommitSource: descobre commits varrendo mensagens da branch principal.

Move a lógica que vivia no TargetResolver — uma chamada só de `git log`
com o --grep de todos os chamados juntos (git faz OR entre --grep),
depois match exato por word-boundary (search_commits só traz candidatos
brutos). Frágil por natureza: depende do dev ter escrito o ID certo na
mensagem. É a fonte de fallback; o Bitbucket (PR) é a primária.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from motor.domain.commits import match_exato
from motor.domain.referencia import FonteReferencia, formatar_referencia
from motor.domain.types import CommitRef
from motor.ports import GitRepo
from motor.progresso import Progresso, RelatorProgresso, silencioso


@dataclass
class GrepCommitSource:
    git: GitRepo
    progresso: RelatorProgresso = silencioso
    referencia: FonteReferencia = field(kw_only=True)
    # `origin/<principal>`. Fonte, nao valor: a principal sai do esquema, que
    # so se resolve na primeira busca — montar nao e usar.
    ref_principal: Callable[[], str] = field(kw_only=True)

    def resolve(self, chamados: list[str], /) -> dict[str, list[CommitRef]]:
        if not chamados:
            return {}

        # Varredura unica: nao ha o que contar, so avisar que comecou.
        self.progresso(Progresso("commits dos chamados no hist\u00f3rico"))
        # Resolvida so aqui, com chamado a buscar: lote vazio nao exige padrao.
        ref = self.referencia()
        candidatos = self.git.search_commits(
            [formatar_referencia(ref, c) for c in chamados], self.ref_principal()
        )

        resultado: dict[str, list[CommitRef]] = {}
        for chamado in chamados:
            commits = match_exato(candidatos, chamado, ref)
            if not commits:
                continue
            # search_commits nao sabe de chamado — carimba aqui.
            resultado[chamado] = [replace(c, chamado=chamado) for c in commits]
        return resultado
