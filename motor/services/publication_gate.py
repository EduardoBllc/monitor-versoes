"""Travas de publicacao (docs/decisoes/010-travas-publicada-e-liberada.md)."""

from __future__ import annotations

from dataclasses import dataclass

from motor.ports import GitRepo
from motor.services.catalogo import Catalogo


@dataclass
class PublicationGate:
    git: GitRepo
    catalogo: Catalogo

    def liberada(self, versao: str) -> bool:
        """Liberada pelo criterio em uso = congelada
        (docs/decisoes/025-esquema-e-atribuicao-plugaveis.md).

        Branch remota nao conta. Branch remota e trabalho compartilhado, nao
        liberacao — confundir os dois travaria uma versao ainda em construcao.
        """
        return versao in self.catalogo.liberadas()

    def publicada(self, versao: str) -> bool:
        """Liberada OU branch remota: proibe rebuild, que reescreveria historia
        que outra maquina ja tem."""
        if self.liberada(versao):
            return True
        return self.git.remote_branch_exists(
            "origin", self.catalogo.versionamento.branch(versao)
        )
