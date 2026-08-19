"""Porte de internal/services/base_resolver.go."""

from __future__ import annotations

from dataclasses import dataclass

from motor.domain.types import BaseRef
from motor.domain.version import inferir_base
from motor.errors import MotorError
from motor.ports import GitRepo


@dataclass
class BaseResolver:
    git: GitRepo

    def resolve(self, numero: str) -> BaseRef:
        existentes = self.git.list_version_branches()
        ref = inferir_base(numero, existentes)
        # ref pode existir como branch E tag (versao fechada cuja branch nao
        # foi apagada) - nome puro fica ambiguo pro git. Tag e o estado
        # publicado e definitivo, entao desempata pra ela quando presente.
        #
        # Sem tag, duas tentativas: o nome puro (head local) e, so depois, a ref
        # de rastreamento. `list_version_branches` enxerga refs/remotes/, entao
        # uma base cortada em outra maquina e escolhida por `inferir_base` — mas
        # `git rev-parse X` nunca consulta refs/remotes/<remoto>/X, e sem esta
        # segunda tentativa a base correta viraria erro (antes de enxergar
        # refs/remotes/ o efeito era pior: uma base mais antiga entrava calada e
        # ficava definitiva em versao.base_commit).
        if self.git.tag_exists(ref):
            candidatos = [f"refs/tags/{ref}"]
        else:
            candidatos = [ref, f"refs/remotes/origin/{ref}"]
        ultimo: Exception | None = None
        for candidato in candidatos:
            try:
                return BaseRef(ref=ref, commit=self.git.resolve_ref(candidato))
            except Exception as e:
                ultimo = e
        raise MotorError(f"resolvendo ref {ref}: {ultimo}") from ultimo
