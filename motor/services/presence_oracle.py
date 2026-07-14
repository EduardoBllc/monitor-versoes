"""Porte de internal/services/presence_oracle.go."""

from __future__ import annotations

from dataclasses import dataclass, field

from motor.domain.types import CommitRef, Presence
from motor.ports import GitRepo


@dataclass
class PresenceOracle:
    git: GitRepo
    # memoizacao por instancia: verificar() cria um oraculo e o reusa pro lote
    # inteiro de commits, mas (base, branch) e o hash de cada candidato se
    # repetem entre chamadas - sem cache, commits_in_range(base, branch) era
    # refeito identico a cada commit (mesmo resultado sempre) e patch_id(hash)
    # era recalculado a cada comparacao em vez de uma vez por hash unico.
    _commits_in_range_cache: dict[tuple[str, str], list[CommitRef] | None] = field(
        default_factory=dict, repr=False, compare=False
    )
    _patch_id_cache: dict[str, str | None] = field(default_factory=dict, repr=False, compare=False)

    def presente(self, hash_origem: str, base: str, branch: str) -> Presence:
        """Implementa o oraculo de 3 niveis (§2): ancestral direto, trailer de
        cherry-pick, e por ultimo patch-id (fallback legado). base delimita o
        intervalo varrido para os niveis 2 e 3 (desvio 8 do topo deste plano).
        """
        if self.git.is_ancestor(hash_origem, branch):
            return Presence.ANCESTRAL

        commits = self._commits_in_range(base, branch)
        if commits is None:
            # nao deu pra confirmar (ex.: objeto sumiu do historico) - trata
            # como ausente em vez de propagar, per §2 "senao -> ausente".
            return Presence.AUSENTE

        trailer = "cherry picked from commit " + hash_origem
        for c in commits:
            if trailer in c.msg:
                return Presence.TRAILER

        patch_id_origem = self._patch_id(hash_origem)
        if patch_id_origem is None:
            # merge commit "limpo" tem diff vazio no `git show` default, git
            # patch-id nao retorna nada - nao da pra confirmar via nivel 3,
            # trata como ausente per §2 "senao -> ausente" (simetrico ao
            # fallback ja aplicado ao patch-id dos candidatos abaixo).
            return Presence.AUSENTE
        for c in commits:
            pid = self._patch_id(c.hash_origem)
            if pid is not None and pid == patch_id_origem:
                return Presence.PATCH_ID
        return Presence.AUSENTE

    def _commits_in_range(self, base: str, branch: str) -> list[CommitRef] | None:
        chave = (base, branch)
        if chave not in self._commits_in_range_cache:
            try:
                self._commits_in_range_cache[chave] = self.git.commits_in_range(base, branch)
            except Exception:
                self._commits_in_range_cache[chave] = None
        return self._commits_in_range_cache[chave]

    def _patch_id(self, hash_: str) -> str | None:
        if hash_ not in self._patch_id_cache:
            try:
                self._patch_id_cache[hash_] = self.git.patch_id(hash_)
            except Exception:
                self._patch_id_cache[hash_] = None
        return self._patch_id_cache[hash_]
