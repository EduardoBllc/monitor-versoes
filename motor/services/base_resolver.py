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
        try:
            commit = self.git.resolve_ref(ref)
        except Exception as e:
            raise MotorError(f"resolvendo ref {ref}: {e}") from e
        return BaseRef(ref=ref, commit=commit)
