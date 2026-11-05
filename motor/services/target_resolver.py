"""Resolucao do alvo: busca as tarefas das fontes que a politica de
atribuicao decidiu (docs/decisoes/026-esquema-e-atribuicao-plugaveis.md) e
casa cada uma com seus commits."""

from __future__ import annotations

from dataclasses import dataclass

from motor.domain.types import Alvo, TaskTarget
from motor.errors import MotorError
from motor.ports import CommitSource, TaskSource
from motor.progresso import Progresso, RelatorProgresso, silencioso


@dataclass
class TargetResolver:
    tasks: TaskSource
    commits: CommitSource
    progresso: RelatorProgresso = silencioso

    def resolve(
        self,
        alvo: str,
        fontes: list[str],
        liberadas: frozenset[str] = frozenset(),
    ) -> Alvo:
        """Une as tarefas das `fontes` e casa cada uma com seus commits.

        `fontes` sao as versoes que a politica de atribuicao decidiu para o
        alvo, em ordem crescente; `liberadas` diz quais delas sao liberadas, e
        serve so ao invariante de ambiguidade.

        Toda tarefa buscada aparece no resultado mesmo sem commit — e o que
        permite o `verificar` pintar de vermelho a tarefa sem entrega em vez
        de dar falso-verde.
        """
        marcada_de: dict[str, str] = {}
        ambiguas: list[str] = []

        for indice, v in enumerate(fontes, start=1):
            self.progresso(
                Progresso("chamados marcados no rastreador", indice, len(fontes))
            )
            try:
                chamados = self.tasks.fetch(v)
            except MotorError as e:
                # add_note em vez de embrulhar: o tipo do adapter tem de sobreviver a
                # esta fronteira, senao BackendIndisponivel chega no chamador como
                # MotorError puro e a taxonomia nao serve para nada.
                e.add_note(f"buscando tasks da versao {v}")
                raise
            for ch in chamados:
                # `get(ch, v) != v` so acusa quando a versao anterior e OUTRA:
                # repeticao dentro da mesma fetch e dedup, nao ambiguidade.
                #
                # E so acusa entre duas ABERTAS: o invariante e sobre versoes que
                # competem pelo mesmo chamado, e liberada nao compete — ja saiu.
                # Sem esse recorte, todo chamado remarcado a mao para contornar
                # uma liberada passaria a pintar a versao de vermelho.
                anterior = marcada_de.get(ch, v)
                if anterior != v and anterior not in liberadas and v not in liberadas:
                    ambiguas.append(ch)
                # last-writer-wins: se o chamado e ambiguo, este valor nao
                # significa nada — a versao ja vai reprovar por causa da
                # ambiguidade, entao ninguem deve confiar em qual "venceu".
                marcada_de[ch] = v

        if not marcada_de:
            return Alvo()

        try:
            achados = self.commits.resolve(list(marcada_de))
        except MotorError as e:
            e.add_note("buscando commits das tasks")
            raise

        return Alvo(
            tasks={
                ch: TaskTarget(chamado=ch, marcada=v, commits=achados.get(ch, []))
                for ch, v in marcada_de.items()
            },
            ambiguas=sorted(set(ambiguas)),
        )
