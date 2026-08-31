"""Porte de internal/services/base_resolver.go."""

from __future__ import annotations

from dataclasses import dataclass

from motor.domain.types import BaseRef
from motor.domain.version import inferir_base
from motor.errors import MotorError, NaoEncontrado
from motor.ports import GitRepo


@dataclass
class BaseResolver:
    git: GitRepo

    def resolve(self, numero: str) -> BaseRef:
        existentes = self.git.list_version_branches()
        ref = inferir_base(numero, existentes)
        commit = self._resolver(ref)

        # A base e o PONTO DE CORTE, nao o tip da ref-base. Para versao que ja
        # existe, o corte e o merge-base entre as duas: o master anda todo dia,
        # e resolver so a ref-base gravava o tip do dia em que o motor viu a
        # versao pela primeira vez. Na 15.0.0 do vendabemweb isso deu 20 dias de
        # erro, e com eles dez liberadas 14.x fora do alvo (§2) — silenciosas,
        # porque tarefa que nao esta no alvo nao e cobrada por ninguem.
        #
        # Versao que ainda nao resolve e o caso do `criar`: nao ha com o que
        # cruzar, e o tip E o corte, porque a branch nasce dele agora.
        try:
            desta_versao = self._resolver(numero)
        except NaoEncontrado:
            return BaseRef(ref=ref, commit=commit)
        # merge-base que falha NAO cai para o tip: historico sem ancestral comum
        # diz que a ref-base esta errada, e base errada envenena o oraculo em
        # silencio pela vida inteira da versao. Erro na cara e o barato aqui.
        return BaseRef(ref=ref, commit=self.git.merge_base(commit, desta_versao))

    def _resolver(self, nome: str) -> str:
        """Commit de uma versao pelo numero, tentando os lugares onde ela pode
        estar. `NaoEncontrado` quando nao esta em nenhum.
        """
        # nome pode existir como branch E tag (versao fechada cuja branch nao
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
        if self.git.tag_exists(nome):
            candidatos = [f"refs/tags/{nome}"]
        else:
            candidatos = [nome, f"refs/remotes/origin/{nome}"]
        ultimo: MotorError | None = None
        for candidato in candidatos:
            try:
                return self.git.resolve_ref(candidato)
            except MotorError as e:
                ultimo = e
        # Nao esta propagando erro de porta: as duas tentativas (nome puro e ref de
        # rastreamento) falharam, e isso e um fato novo - "nao achei a base".
        raise NaoEncontrado(f"resolvendo ref {nome}: {ultimo}") from ultimo
