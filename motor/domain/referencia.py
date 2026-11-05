"""Referência de tarefa: como o ID de uma tarefa aparece na mensagem de commit.

O padrão é um template com `{id}` (`ch{id}` num rastreador, `{id}` num Jira); o resto
é texto literal. O alfabeto diz que caracteres um ID pode ter. O tracker propõe
os dois; a config sobrescreve só o padrão. Domínio, grep e host de PR recebem a
`Referencia` já resolvida e não conhecem o tracker.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from motor.errors import ErroDeEntrada

#: Letras, dígitos, `_` e `-`: cobre `PAY-123` e o número puro de `ch{id}`.
ALFABETO_PADRAO: Final = "A-Za-z0-9_-"

_MARCA = "{id}"


@dataclass(frozen=True)
class Referencia:
    padrao: str
    # Conteúdo de classe de caracteres de regex (`0-9`, `A-Za-z0-9_-`).
    alfabeto: str = ALFABETO_PADRAO


#: Resolve a referência sob demanda. Quem só monta não paga: a falta de padrão
#: aparece no comando que usa a referência, não em `atualizar --abort`.
FonteReferencia = Callable[[], Referencia]


def validar_padrao(valor: object, origem: str) -> str:
    """Devolve o padrão se for texto com exatamente um `{id}`."""
    if not isinstance(valor, str):
        motivo = "esperado texto com {id}"
    elif valor.count(_MARCA) != 1:
        motivo = "esperado exatamente um {id}"
    else:
        return valor
    raise ErroDeEntrada(f"{origem}: [referencia] padrao invalido: {valor!r} ({motivo})")


def resolver_referencia(
    proposta: Referencia | None, padrao_config: str | None, arquivos: tuple[str, ...]
) -> Referencia:
    """Precedência: config (já validada e mesclada) > proposta do adapter.

    O alfabeto vem sempre da proposta, quando há uma: a config não o muda, e
    sobrescrever só o padrão de uma proposta `ch{id}` com alfabeto `0-9` não pode fazer `ch254473-fix` extrair
    `254473-fix`.
    """
    alfabeto = ALFABETO_PADRAO if proposta is None else proposta.alfabeto
    if padrao_config is not None:
        return Referencia(padrao_config, alfabeto)
    if proposta is not None:
        return Referencia(
            validar_padrao(proposta.padrao, "padrao proposto pelo adapter"), alfabeto
        )
    onde = " e ".join(arquivos) or "a config"
    raise ErroDeEntrada(f"faltando [referencia] padrao em {onde}")


def formatar_referencia(ref: Referencia, chamado: str) -> str:
    """O texto que cita `chamado` numa mensagem (como `ch123`)."""
    return ref.padrao.replace(_MARCA, chamado)


def id_no_alfabeto(texto: str, alfabeto: str = ALFABETO_PADRAO) -> bool:
    return re.fullmatch(_regex_do_id(alfabeto), texto, re.IGNORECASE) is not None


def _regex_do_id(alfabeto: str) -> str:
    # Começa por letra ou dígito: um ID não abre com `-` nem `_`.
    return f"(?=[A-Za-z0-9])[{alfabeto}]+"


def _conjunto(ref: Referencia, so_alfabeto: bool) -> str:
    """O conjunto *S* da fronteira (006), como classe de regex.

    No domínio, caracteres de palavra mais o alfabeto: com `ch{id}`, é o `\\b`
    de sempre. No Bitbucket, só o alfabeto: `ch` colado a uma letra no começo
    da branch casa, como sempre casou.
    """
    return f"[{ref.alfabeto}]" if so_alfabeto else f"[\\w{ref.alfabeto}]"


def _no_conjunto(caractere: str, conjunto: str) -> bool:
    return re.fullmatch(conjunto, caractere, re.IGNORECASE) is not None


def _cercar(miolo: str, esquerda: bool, direita: bool, conjunto: str) -> str:
    """Põe a fronteira só no lado cuja ponta é caractere de *S*."""
    antes = f"(?<!{conjunto})" if esquerda else ""
    depois = f"(?!{conjunto})" if direita else ""
    return antes + miolo + depois


def regex_do_chamado(
    ref: Referencia, chamado: str, *, so_alfabeto: bool = False
) -> re.Pattern[str]:
    """Casa a referência de um chamado conhecido, com o ID literal."""
    texto = formatar_referencia(ref, chamado)
    conjunto = _conjunto(ref, so_alfabeto)
    miolo = re.escape(texto)
    if not texto:
        return re.compile(miolo, re.IGNORECASE)
    return re.compile(
        _cercar(
            miolo,
            _no_conjunto(texto[0], conjunto),
            _no_conjunto(texto[-1], conjunto),
            conjunto,
        ),
        re.IGNORECASE,
    )


def regex_de_extracao(ref: Referencia) -> re.Pattern[str]:
    """Acha uma referência qualquer; o ID fica no grupo `id`.

    O `{id}` casa o alfabeto, guloso, e a fronteira faz o resto: com `ch{id}` e alfabeto `0-9`,
    `ch254473-fix` dá `254473` porque `-` não é dígito nem caractere de palavra.
    """
    prefixo, sufixo = ref.padrao.split(_MARCA)
    conjunto = _conjunto(ref, so_alfabeto=False)
    # Ponta vazia é o próprio ID, que sempre começa e termina em caractere de S.
    esquerda = not prefixo or _no_conjunto(prefixo[0], conjunto)
    direita = not sufixo or _no_conjunto(sufixo[-1], conjunto)
    miolo = (
        re.escape(prefixo) + f"(?P<id>{_regex_do_id(ref.alfabeto)})" + re.escape(sufixo)
    )
    return re.compile(_cercar(miolo, esquerda, direita, conjunto), re.IGNORECASE)
