"""Travas de publicacao (spec §2, §6)."""

from __future__ import annotations

from dataclasses import dataclass

from motor.ports import GitRepo


@dataclass
class PublicationGate:
    git: GitRepo

    def liberada(self, versao: str) -> bool:
        """Tag existe = versao liberada = congelada.

        So a tag conta. Branch remota e trabalho compartilhado, nao liberacao —
        confundir os dois travaria uma versao ainda em construcao.
        """
        return self.git.tag_exists(versao)

    def publicada(self, versao: str) -> bool:
        """Tag OU branch remota: proibe rebuild, que reescreveria historia que
        outra maquina ja tem."""
        if self.git.tag_exists(versao):
            return True
        return self.git.remote_branch_exists("origin", versao)
