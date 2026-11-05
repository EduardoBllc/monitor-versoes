"""Composicao de uma versao nova: branch, VERSAO e registro no estado."""

from __future__ import annotations

from motor.domain.types import VersaoInfo
from motor.domain.version import inferir_tipo
from motor.engine.atualizar import AtualizarResult, atualizar
from motor.engine.deps import Deps
from motor.errors import RecusaDeInvariante
from motor.services.base_resolver import BaseResolver
from motor.services.catalogo import Catalogo
from motor.services.publication_gate import PublicationGate


def criar(deps: Deps, versao: str) -> AtualizarResult:
    """Monta uma versao do zero. Branch nova e nao publicada
    (docs/decisoes/010-travas-publicada-e-liberada.md).

    So cria: recriar do zero e responsabilidade do chamador, que precisa remover
    a worktree e a branch antes de chamar de novo — `worktree_add` recusa branch
    existente, entao um retry apos lote BLOCKED cai aqui, nao no atualizar.
    """
    versionamento = deps.versionamento()
    versionamento.esquema.validar(versao)
    # A trava e a base saem do ref store local (o `Catalogo`): sem buscar
    # primeiro, uma versao liberada em outra maquina passaria pela trava e
    # ganharia branch nova aqui.
    deps.git.fetch("origin")

    catalogo = Catalogo(deps.git, versionamento)
    gate = PublicationGate(deps.git, catalogo)
    if gate.publicada(versao):
        raise RecusaDeInvariante(f"versao {versao} ja publicada - use atualizar")

    base = BaseResolver(deps.git, catalogo).resolve(versao)

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
