"""Porte de internal/engine/criar.go."""

from __future__ import annotations

from motor.domain.types import VersaoInfo
from motor.domain.version import inferir_tipo
from motor.engine.atualizar import AtualizarResult, atualizar
from motor.engine.deps import Deps
from motor.errors import MotorError
from motor.services.base_resolver import BaseResolver
from motor.services.publication_gate import PublicationGate


def criar(deps: Deps, versao: str) -> AtualizarResult:
    """Monta uma versao do zero (spec §5). Branch nova e nao publicada."""
    # A trava e a base saem do ref store local (`git tag -l`,
    # `list_version_branches`): sem buscar primeiro, uma versao liberada em
    # outra maquina passaria pela trava e ganharia branch nova aqui.
    deps.git.fetch("origin")

    gate = PublicationGate(git=deps.git)
    if gate.publicada(versao):
        raise MotorError(f"versao {versao} ja publicada - use atualizar")

    base = BaseResolver(git=deps.git).resolve(versao)

    deps.git.worktree_add(versao, base.commit)
    deps.git.write_file(
        versao, "VERSAO", f"{versao}\n".encode(), f"Atualiza VERSAO para {versao}"
    )

    # A versao entra no estado aqui; o verificar dentro do atualizar preenche
    # as atribuicoes.
    deps.estado.registrar_versao(
        deps.repo,
        VersaoInfo(
            numero=versao,
            tipo=inferir_tipo(versao),
            base_ref=base.ref,
            base_commit=base.commit,
        ),
    )

    return atualizar(deps, versao)
