"""Resolucao do alvo: aplica a regra de distribuicao da spec §2."""

from __future__ import annotations

from dataclasses import dataclass

from motor.domain.types import Alvo, TaskTarget
from motor.domain.version import fontes_de_alvo
from motor.errors import MotorError
from motor.ports import CommitSource, TaskSource
from motor.progresso import Progresso, RelatorProgresso, silencioso


@dataclass
class TargetResolver:
    tasks: TaskSource
    commits: CommitSource
    progresso: RelatorProgresso = silencioso

    def resolve(self, alvo: str, abertas: list[str]) -> Alvo:
        """Une as tarefas de toda versao em construcao <= alvo e casa cada uma
        com seus commits.

        Toda tarefa buscada aparece no resultado mesmo sem commit — e o que
        permite o `verificar` pintar de vermelho a tarefa sem entrega em vez
        de dar falso-verde.
        """
        marcada_de: dict[str, str] = {}
        ambiguas: list[str] = []

        fontes = fontes_de_alvo(alvo, abertas)
        for indice, v in enumerate(fontes, start=1):
            self.progresso(
                Progresso("chamados marcados no Tickio", indice, len(fontes))
            )
            try:
                chamados = self.tasks.fetch(v)
            except Exception as e:
                raise MotorError(f"buscando tasks da versao {v}: {e}") from e
            for ch in chamados:
                # `get(ch, v) != v` so acusa quando a versao anterior e OUTRA:
                # repeticao dentro da mesma fetch e dedup, nao ambiguidade.
                if marcada_de.get(ch, v) != v:
                    ambiguas.append(ch)
                # last-writer-wins: se o chamado e ambiguo, este valor nao
                # significa nada — a versao ja vai reprovar por causa da
                # ambiguidade, entao ninguem deve confiar em qual "venceu".
                marcada_de[ch] = v

        if not marcada_de:
            return Alvo()

        try:
            achados = self.commits.resolve(list(marcada_de))
        except Exception as e:
            raise MotorError(f"buscando commits das tasks: {e}") from e

        return Alvo(
            tasks={
                ch: TaskTarget(chamado=ch, marcada=v, commits=achados.get(ch, []))
                for ch, v in marcada_de.items()
            },
            ambiguas=sorted(set(ambiguas)),
        )
