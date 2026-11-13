"""Double em memória de ProvedorSugestao, para testes e conferência manual."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from motor.domain.conflito import PedidoAoProvedor, PropostaDeBloco


class FakeProvedorSugestao:
    """Aceita os argumentos do contrato do plugin, para servir como `modulo:Classe`."""

    def __init__(
        self,
        *,
        sugestao: Mapping[str, object] | None = None,
        arquivos: tuple[str, ...] = (),
        responder: Callable[[PedidoAoProvedor], list[PropostaDeBloco]] | None = None,
    ) -> None:
        self.pedidos: list[PedidoAoProvedor] = []
        self._responder = responder

    def propor(self, pedido: PedidoAoProvedor, /) -> list[PropostaDeBloco]:
        self.pedidos.append(pedido)
        if self._responder is not None:
            return self._responder(pedido)
        return [
            PropostaDeBloco(
                ordem=b.ordem,
                conteudo=b.ours + b.theirs,
                justificativa="proposta falsa: junta os dois lados",
            )
            for b in pedido.blocos
        ]
