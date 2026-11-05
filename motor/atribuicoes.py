"""Políticas de atribuição embutidas (porta `motor.ports.PoliticaAtribuicao`).

Carregadas pelo nome, no grupo de entry points `monitor_versoes.atribuicoes`
(docs/decisoes/025-esquema-e-atribuicao-plugaveis.md). As duas só comparam
versões pela ordem que o esquema dá: nenhuma conhece o formato do número.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable

from motor.domain.types import ContextoAtribuicao

Ordenar = Callable[[list[str]], list[str]]


def ate_o_alvo(
    ordenar: Ordenar, candidatas: list[str], alvo: str, piso: str | None
) -> list[str]:
    """As `candidatas` entre o piso e o alvo, inclusive, em ordem crescente.

    O piso vem da config do projeto (`[versao] piso`): descarta branch legada
    que o tracker não conhece. Sem piso, nada é cortado por baixo.
    """
    marcos = {alvo} if piso is None else {alvo, piso}
    ordem = ordenar(list(set(candidatas) | marcos))
    de = 0 if piso is None else ordem.index(piso)
    pedidas = set(candidatas)
    return [v for v in ordem[de : ordem.index(alvo) + 1] if v in pedidas]


def liberadas_apos_corte(
    ordenar: Ordenar,
    alvo: str,
    liberadas: dict[str, datetime.datetime],
    corte: datetime.datetime,
) -> list[str]:
    """Liberadas até o alvo cuja liberação é posterior ao corte do alvo
    (docs/decisoes/005-alvo-distribuicao-entre-versoes.md).

    A liberada sai do conjunto aberto, e a premissa era que o conteúdo dela
    chegava por ancestralidade da base. Isso não vale quando a base do alvo é a
    principal no ponto de corte: entrega liberada depois desse corte nunca foi
    herdada, e volta a ser fonte; o oráculo de presença decide commit por
    commit o que ainda falta. Liberação exatamente no corte fica fora: é o caso
    da versão cortada da anterior já liberada, cujo conteúdo é ancestral.
    """
    posteriores = [n for n, data in liberadas.items() if data > corte]
    return ate_o_alvo(ordenar, posteriores, alvo, None)


class Exata:
    """A tarefa vale só na versão marcada. É o padrão sem config."""

    def fontes(self, alvo: str, contexto: ContextoAtribuicao, /) -> list[str]:
        return ate_o_alvo(contexto.ordenar, [alvo], alvo, contexto.piso)


class Composta:
    """A regra da docs/decisoes/005-alvo-distribuicao-entre-versoes.md: o alvo
    recebe as tarefas das abertas e das liberadas após o corte, entre o piso e
    ele."""

    def fontes(self, alvo: str, contexto: ContextoAtribuicao, /) -> list[str]:
        candidatas = {
            *contexto.abertas,
            *liberadas_apos_corte(
                contexto.ordenar, alvo, contexto.liberadas, contexto.corte
            ),
            alvo,
        }
        return ate_o_alvo(contexto.ordenar, list(candidatas), alvo, contexto.piso)
