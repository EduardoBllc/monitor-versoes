"""Porte de internal/services/presence_oracle.go."""

from __future__ import annotations

from dataclasses import dataclass

from motor.ports import GitRepo


@dataclass
class PresenceOracle:
    git: GitRepo

    def presente(self, hash_origem: str, base: str, branch: str) -> bool:
        """Implementa o oraculo de 3 niveis (§2): ancestral direto, trailer de
        cherry-pick, e por ultimo patch-id (fallback legado). base delimita o
        intervalo varrido para os niveis 2 e 3 (desvio 8 do topo deste plano).
        """
        if self.git.is_ancestor(hash_origem, branch):
            return True

        try:
            commits = self.git.commits_in_range(base, branch)
        except Exception:
            # nao deu pra confirmar (ex.: objeto sumiu do historico) - trata
            # como ausente em vez de propagar, per §2 "senao -> ausente".
            return False

        trailer = "cherry picked from commit " + hash_origem
        for c in commits:
            if trailer in c.msg:
                return True

        patch_id_origem = self.git.patch_id(hash_origem)
        for c in commits:
            try:
                pid = self.git.patch_id(c.hash_origem)
            except Exception:
                continue
            if pid == patch_id_origem:
                return True
        return False
