"""Porte de internal/services/publication_gate.go."""

from __future__ import annotations

from dataclasses import dataclass

from motor.ports import GitRepo


@dataclass
class PublicationGate:
    git: GitRepo

    def publicada(self, versao: str) -> bool:
        """Implementa a trava de rebuild (§6): tag local OU branch remota."""
        if self.git.tag_exists(versao):
            return True
        return self.git.remote_branch_exists("origin", versao)
