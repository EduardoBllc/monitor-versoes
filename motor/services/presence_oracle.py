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
    _changed_files_cache: dict[str, frozenset[str] | None] = field(
        default_factory=dict, repr=False, compare=False
    )
    # (base, branch) -> chave (msg, arquivos) -> fila de candidatos do alvo ainda
    # nao consumidos. Consumo (pop) evita que 2 commits de origem com msg+arquivos
    # identicos (comum dentro da mesma PR) colidam no mesmo candidato do alvo.
    _por_msg_arquivos_cache: dict[tuple[str, str], dict[tuple[str, frozenset[str]], list[CommitRef]]] = field(
        default_factory=dict, repr=False, compare=False
    )

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

    def suspeita_por_conteudo(self, hash_origem: str, base: str, branch: str) -> CommitRef | None:
        """Nivel 4 (fora do oraculo de presenca formal - so alerta, nao conta
        como presente): cherry-pick manual sem -x cujo conteudo foi alterado na
        resolucao do conflito muda o patch-id, entao o nivel 3 nao pega. Aqui
        procura no alvo um commit com a mesma mensagem E os mesmos arquivos
        alterados - a mensagem sozinha colide demais quando o time repete a
        mesma msg em commits distintos da mesma PR.
        """
        meta = self.git.commit_meta(hash_origem)
        arquivos_origem = self._changed_files(hash_origem)
        if arquivos_origem is None:
            return None
        chave = (meta.msg.strip(), arquivos_origem)
        candidatos = self._por_msg_arquivos(base, branch).get(chave)
        if not candidatos:
            return None
        return candidatos.pop(0)

    def _por_msg_arquivos(
        self, base: str, branch: str
    ) -> dict[tuple[str, frozenset[str]], list[CommitRef]]:
        chave = (base, branch)
        if chave not in self._por_msg_arquivos_cache:
            agrupado: dict[tuple[str, frozenset[str]], list[CommitRef]] = {}
            for c in self._commits_in_range(base, branch) or []:
                arquivos = self._changed_files(c.hash_origem)
                if arquivos is None:
                    continue
                agrupado.setdefault((c.msg.strip(), arquivos), []).append(c)
            self._por_msg_arquivos_cache[chave] = agrupado
        return self._por_msg_arquivos_cache[chave]

    def _changed_files(self, hash_: str) -> frozenset[str] | None:
        if hash_ not in self._changed_files_cache:
            try:
                self._changed_files_cache[hash_] = self.git.changed_files(hash_)
            except Exception:
                self._changed_files_cache[hash_] = None
        return self._changed_files_cache[hash_]

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
