"""ProvedorAnthropic: plugin `ProvedorSugestao` pelo SDK oficial (`[sugestao] provedor = "anthropic"`).

O SDK é um extra (`monitor-versoes[anthropic]`) e só se importa no uso: sem ele, a
classe ainda carrega e o catálogo da config vê a chave que ela declara (a máscara).
"""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Mapping
from enum import StrEnum
from http import HTTPStatus
from typing import TYPE_CHECKING

from motor.config import TABELA_AMBIENTE
from motor.config_edicao import Campo, Escopo, TipoCampo
from motor.domain.conflito import PedidoAoProvedor, PropostaDeBloco
from motor.errors import BackendIndisponivel, ErroDeEntrada, RespostaInvalida

if TYPE_CHECKING:
    import httpx2


class Var(StrEnum):
    """Variáveis do `[ambiente]` que este plugin lê."""

    CHAVE = "ANTHROPIC_API_KEY"


class Parada(StrEnum):
    """`stop_reason` que o provedor distingue."""

    FIM = "end_turn"
    RECUSA = "refusal"


class Papel(StrEnum):
    USUARIO = "user"


class Formato(StrEnum):
    ESQUEMA_JSON = "json_schema"


CHAVE_MODELO = "modelo"
MODELO_PADRAO = "claude-opus-5-5"
MAX_TOKENS = 16000
TIMEOUT_S = 300.0
MAX_RETRIES = 2
EXTRA = "monitor-versoes[anthropic]"

INSTRUCAO = (
    "Você recebe, em JSON, os blocos de conflito de um arquivo durante o cherry-pick "
    "de um commit: o caminho, a mensagem do commit, o chamado quando houver e, para "
    "cada bloco, a ordem e os lados ours (a versão de destino), theirs (o commit "
    "aplicado) e base, quando houver. Proponha a resolução de cada bloco, com um item "
    "por ordem recebida. O conteúdo é o texto que substitui o bloco inteiro, sem "
    "marcadores de conflito e com a quebra final de cada linha. A justificativa é "
    "curta e cita a intenção do commit que levou à escolha. Não invente nada que não "
    "esteja nos lados do bloco."
)

ESQUEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "blocos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ordem": {"type": "integer"},
                    "conteudo": {"type": "string"},
                    "justificativa": {"type": "string"},
                },
                "required": ["ordem", "conteudo", "justificativa"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["blocos"],
    "additionalProperties": False,
}


def _dados(pedido: PedidoAoProvedor) -> dict[str, object]:
    blocos = [
        {"ordem": b.ordem, "ours": b.ours, "theirs": b.theirs}
        | ({} if b.base is None else {"base": b.base})
        for b in pedido.blocos
    ]
    dados: dict[str, object] = {"caminho": pedido.caminho, "mensagem": pedido.mensagem}
    if pedido.chamado is not None:
        dados["chamado"] = pedido.chamado
    return dados | {"blocos": blocos}


def _proposta(item: object) -> PropostaDeBloco:
    match item:
        case {
            "ordem": int(ordem),
            "conteudo": str(conteudo),
            "justificativa": str(justificativa),
        } if not isinstance(ordem, bool):
            return PropostaDeBloco(ordem, conteudo, justificativa)
    raise RespostaInvalida(f"bloco fora do esquema na resposta da Anthropic: {item!r}")


def _propostas(texto: str) -> list[PropostaDeBloco]:
    try:
        dados = json.loads(texto)
    except ValueError as e:
        raise RespostaInvalida(f"a Anthropic não devolveu JSON: {e}") from e
    match dados:
        case {"blocos": list(itens)}:
            return [_proposta(i) for i in itens]
    raise RespostaInvalida("resposta da Anthropic sem a lista de blocos")


class ProvedorAnthropic:
    """`ProvedorSugestao` pela API de mensagens da Anthropic."""

    campos_config = (
        Campo(
            Escopo.AMBIENTE,
            TABELA_AMBIENTE,
            Var.CHAVE,
            TipoCampo.TEXTO,
            "Chave da API da Anthropic",
            segredo=True,
            descricao="Chave da API da Anthropic, usada pela sugestão de resolução",
        ),
    )

    def __init__(
        self,
        *,
        sugestao: Mapping[str, object],
        arquivos: tuple[str, ...],
        http_client: httpx2.Client | None = None,
    ) -> None:
        # Única exceção ao construtor sem I/O (027): sem o extra, o provedor não
        # existe, e a `sugestao_disponivel` tem de dizer isso.
        try:
            importlib.import_module("anthropic")
        except ImportError as e:
            raise ErroDeEntrada(
                f'[sugestao] provedor = "anthropic" precisa do pacote anthropic: '
                f"instale {EXTRA} (ver README, Instalação)"
            ) from e
        self._sugestao = sugestao
        self._arquivos = arquivos
        # Cliente injetado é do teste; sem ele, o SDK cria o próprio.
        self._http_client = http_client

    def _lida(self) -> str:
        return " e ".join(self._arquivos) or "nenhuma"

    def _chave(self) -> str:
        chave = os.environ.get(Var.CHAVE, "").strip()
        if not chave:
            raise ErroDeEntrada(
                f'[sugestao] provedor = "anthropic" sem {Var.CHAVE}: defina-a no '
                f"[{TABELA_AMBIENTE}] do config.toml central (config lida: {self._lida()})"
            )
        return chave

    def verificar_credenciais(self) -> None:
        """Só a presença da chave: sem rede e sem cliente."""
        self._chave()

    def propor(self, pedido: PedidoAoProvedor, /) -> list[PropostaDeBloco]:
        import anthropic  # já em cache: o construtor o importou

        chave = self._chave()
        modelo = self._sugestao.get(CHAVE_MODELO, MODELO_PADRAO)
        if not isinstance(modelo, str) or not modelo.strip():
            raise ErroDeEntrada(
                f"[sugestao] {CHAVE_MODELO} tem de ser texto não vazio "
                f"(config lida: {self._lida()})"
            )
        # Explícita: sozinho, o SDK cairia em ANTHROPIC_AUTH_TOKEN ou num perfil em disco.
        client = anthropic.Anthropic(
            api_key=chave,
            timeout=TIMEOUT_S,
            max_retries=MAX_RETRIES,
            http_client=self._http_client,
        )
        try:
            resposta = client.messages.create(
                model=modelo,
                max_tokens=MAX_TOKENS,
                system=INSTRUCAO,
                messages=[
                    {
                        "role": Papel.USUARIO.value,
                        "content": json.dumps(_dados(pedido), ensure_ascii=False),
                    }
                ],
                output_config={
                    "format": {"type": Formato.ESQUEMA_JSON.value, "schema": ESQUEMA}
                },
            )
        except (
            anthropic.BadRequestError,
            anthropic.AuthenticationError,
            anthropic.PermissionDeniedError,
            anthropic.NotFoundError,
        ) as e:
            raise ErroDeEntrada(
                f"API da Anthropic recusou o pedido ({e.status_code}): {e.message}"
            ) from e
        except (anthropic.RateLimitError, anthropic.InternalServerError) as e:
            raise BackendIndisponivel(
                f"API da Anthropic indisponível ({e.status_code}): {e.message}"
            ) from e
        except anthropic.APIStatusError as e:
            classe = (
                BackendIndisponivel
                if e.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
                else RespostaInvalida
            )
            raise classe(
                f"API da Anthropic respondeu {e.status_code}: {e.message}"
            ) from e
        except anthropic.APIConnectionError as e:  # inclui o APITimeoutError
            raise BackendIndisponivel(f"API da Anthropic inacessível: {e}") from e
        if resposta.stop_reason == Parada.RECUSA.value:
            raise RespostaInvalida("o modelo recusou o pedido")
        if resposta.stop_reason != Parada.FIM.value:
            raise RespostaInvalida(
                f"resposta da Anthropic incompleta (stop_reason {resposta.stop_reason})"
            )
        texto = next(
            (
                b.text
                for b in resposta.content
                if isinstance(b, anthropic.types.TextBlock)
            ),
            None,
        )
        if texto is None:
            raise RespostaInvalida("resposta da Anthropic sem bloco de texto")
        return _propostas(texto)
