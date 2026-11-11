"""Listar e julgar os commits órfãos de uma versão.

Órfão é o commit de `base..branch` sem referência de tarefa na mensagem de
origem. O motor não pergunta ao humano
(docs/decisoes/021-motor-nao-interativo.md): estas duas operações são o que o
front-end usa para mostrar os órfãos e gravar a resposta, que o
`reconstruir-estado` e o `verificar` aplicam depois
(docs/decisoes/032-julgamento-de-orfao.md).

Nenhuma das duas regrava atribuições nem registra a versão: a listagem é
leitura, e o julgamento só escreve o próprio registro.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from motor.domain.referencia import Referencia, id_no_alfabeto
from motor.domain.types import CommitRef, JulgamentoOrfao, VersaoInfo
from motor.engine.deps import Deps
from motor.errors import ErroDeEntrada
from motor.progresso import Progresso
from motor.services.reconstrutor import varrer
from motor.services.versionamento import Versionamento


@dataclass(frozen=True)
class OrfaoDaVersao:
    hash_origem: str
    assunto: str  # primeira linha da mensagem de origem
    data: datetime.datetime
    julgamento: JulgamentoOrfao | None  # None = pendente


def rotulo_do_julgamento(j: JulgamentoOrfao | None) -> str:
    """O julgamento como a CLI e a TUI o mostram."""
    if j is None:
        return "pendente"
    destino = "nenhum" if j.chamado is None else f"pertence a {j.chamado}"
    return f"{destino}: {j.motivo}"


def linha_do_orfao(o: OrfaoDaVersao) -> str:
    """Hash curto, data, assunto e julgamento: uma linha da CLI e da TUI."""
    return (
        f"{o.hash_origem[:8]} {o.data:%Y-%m-%d} {o.assunto} "
        f"[{rotulo_do_julgamento(o.julgamento)}]"
    )


def listar_orfaos(deps: Deps, versao: str) -> list[OrfaoDaVersao]:
    referencia = deps.referencia()
    versionamento = deps.versionamento()
    versionamento.esquema.validar(versao)
    orfaos = _orfaos_atuais(deps, versionamento, referencia, versao)
    julgados = {
        j.hash_origem: j
        for j in deps.estado.julgamentos_orfao(deps.repo)
        if j.versao_numero == versao
    }
    return [
        OrfaoDaVersao(
            hash_origem=o.hash_origem,
            assunto=o.msg.splitlines()[0] if o.msg else "",
            data=o.commit_date,
            julgamento=julgados.get(o.hash_origem),
        )
        for o in orfaos
    ]


def julgar_orfao(
    deps: Deps, versao: str, hash_: str, chamado: str | None, motivo: str
) -> JulgamentoOrfao:
    """Grava o julgamento com o hash completo e o motivo aparado.

    `chamado=None` é "não pertence a chamado nenhum". O hash pode vir
    abreviado, desde que identifique um só órfão atual da versão.
    """
    # O que não lê o git vem antes do fetch: erro de digitação não paga rede.
    referencia = deps.referencia()
    if not motivo.strip():
        raise ErroDeEntrada("o motivo do julgamento é obrigatório")
    if chamado is not None and not id_no_alfabeto(chamado, referencia.alfabeto):
        raise ErroDeEntrada(
            f"chamado {chamado!r} fora do alfabeto da referência "
            f"([{referencia.alfabeto}])"
        )
    prefixo = hash_.strip().lower()
    if not prefixo:
        raise ErroDeEntrada("informe o hash do órfão")
    versionamento = deps.versionamento()
    versionamento.esquema.validar(versao)

    orfaos = _orfaos_atuais(deps, versionamento, referencia, versao)
    # O prefixo é procurado só entre os órfãos: um commit com referência que
    # comece igual não torna o prefixo ambíguo.
    achados = [o.hash_origem for o in orfaos if o.hash_origem.startswith(prefixo)]
    if not achados:
        raise ErroDeEntrada(f"{hash_} não é órfão da versão {versao}")
    if len(achados) > 1:
        raise ErroDeEntrada(
            f"{hash_} é ambíguo entre os órfãos da versão {versao}: "
            + ", ".join(h[:12] for h in achados)
        )

    julgamento = JulgamentoOrfao(
        hash_origem=achados[0],
        versao_numero=versao,
        chamado=chamado,
        motivo=motivo.strip(),
    )
    deps.estado.julgar_orfao(deps.repo, julgamento)
    return julgamento


def _orfaos_atuais(
    deps: Deps, versionamento: Versionamento, referencia: Referencia, versao: str
) -> list[CommitRef]:
    # Fetch antes de ler o estado e a branch
    # (docs/decisoes/022-fetch-origin-em-todo-entry-point.md): a validação do
    # hash lê a branch, e um pick empurrado por outra máquina seria recusado.
    deps.progresso(Progresso("buscando refs do origin"))
    deps.git.fetch("origin")
    info = _versao_registrada(deps, versao)
    deps.progresso(Progresso("varrendo os commits da versão"))
    _, orfaos = varrer(
        deps.git, info.base_commit, versionamento.branch(versao), referencia
    )
    return orfaos


def _versao_registrada(deps: Deps, versao: str) -> VersaoInfo:
    info = deps.estado.versao(deps.repo, versao)
    if info is None:
        raise ErroDeEntrada(
            f"versão {versao} não registrada no estado: rode "
            "`reconstruir-estado` ou `verificar` antes"
        )
    return info
