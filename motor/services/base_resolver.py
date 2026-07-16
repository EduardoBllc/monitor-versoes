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
        ref_qualificado = f"refs/tags/{ref}" if self.git.tag_exists(ref) else ref
        try:
            commit = self.git.resolve_ref(ref_qualificado)
        except Exception as e:
            raise MotorError(f"resolvendo ref {ref_qualificado}: {e}") from e
        return BaseRef(ref=ref, commit=commit)
