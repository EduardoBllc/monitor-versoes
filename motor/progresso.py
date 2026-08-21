"""Canal de progresso: o motor conta em que fase esta, quem chamou desenha.

Nao vive em `ports.py` de proposito — aquele arquivo se declara transcricao
1-pra-1 de `internal/ports/ports.go`, e conceito que nao existe no original
mentiria pro proximo leitor.

Um relator e uma funcao, nao um Protocol: `relatos.append` e uma barra de
progresso satisfazem os dois o mesmo contrato, e nada no motor precisa de mais
que "me avise". Nenhuma porta de `ports.py` muda por causa disto — services e
adapters recebem o relator por construtor, entao os fakes seguem sem saber que
progresso existe.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Progresso:
    """Onde o comando esta agora.

    `total == 0` significa fase sem contagem (spinner, nao barra): e o caso de
    quase toda borda de I/O — um `fetch` nao sabe dizer quanto falta.
    """

    fase: str
    feito: int = 0
    total: int = 0


RelatorProgresso = Callable[[Progresso], None]


def silencioso(_: Progresso) -> None:
    """Relator default. Existe para que ninguem precise checar `if progresso`
    antes de relatar, e para que quem nao quer progresso nao pague nada.
    """


@dataclass
class SlotProgresso:
    """Amostragem em vez de entrega: o motor escreve, quem desenha le quando
    quiser.

    Existe por causa de uma armadilha concreta: na TUI o motor roda em thread e
    a unica forma sancionada de tocar a interface de lá é `call_from_thread`,
    que **bloqueia** até o loop principal processar. Chamado uma vez por commit
    num lote de centenas, ele serializa o motor no frame rate da interface — o
    progresso deixaria o comando mais lento do que ele era sem progresso.

    Aqui o motor so faz uma atribuicao e segue. Nao ha lock: rebind de atributo
    e atomico sob o GIL e a semantica desejada e exatamente last-writer-wins —
    evento perdido entre duas amostragens e evento que ninguem precisava ver.
    """

    ultimo: Progresso | None = None

    def relatar(self, progresso: Progresso) -> None:
        self.ultimo = progresso

    def limpar(self) -> None:
        """Chamado ao iniciar um comando: sem isto a fase final do comando
        anterior ("gravando estado") pisca antes da primeira do novo.
        """
        self.ultimo = None
