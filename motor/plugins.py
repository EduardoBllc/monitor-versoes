"""Carregador de plugins: entry points instalados ou import direto."""

from __future__ import annotations

import importlib
from importlib.metadata import entry_points
from typing import Literal

from motor.errors import ErroDeEntrada

Origem = Literal["central", "repo"]


def carregar_plugin(grupo: str, nome: str, origem: Origem) -> type:
    """Resolve `nome` para uma classe.

    Sem `:`, e o nome de um entry point do `grupo`. Com `:` (`modulo:Classe`), e
    import direto, aceito so se a config veio do arquivo central: o repo-alvo nao
    escolhe codigo a executar.
    """
    if ":" in nome:
        if origem != "central":
            raise ErroDeEntrada(
                f"plugin {nome!r}: import direto so vale no config.toml central; "
                "o repo nao escolhe codigo a executar (use o nome de um plugin instalado)"
            )
        return _importar(nome)
    pontos = {ep.name: ep for ep in entry_points(group=grupo)}
    if nome not in pontos:
        instalados = ", ".join(sorted(pontos)) or "nenhum"
        raise ErroDeEntrada(
            f"plugin {nome!r} nao encontrado no grupo {grupo} (instalados: {instalados})"
        )
    try:
        alvo = pontos[nome].load()
    except Exception as e:
        raise ErroDeEntrada(f"plugin {nome!r}: falha ao carregar ({e})") from e
    return _exigir_classe(alvo, nome)


def _importar(caminho: str) -> type:
    modulo, _, classe = caminho.partition(":")
    if not modulo or not classe:
        raise ErroDeEntrada(f"plugin {caminho!r}: esperado modulo:Classe")
    try:
        mod = importlib.import_module(modulo)
    except ImportError as e:
        raise ErroDeEntrada(
            f"plugin {caminho!r}: modulo {modulo!r} nao importa ({e})"
        ) from e
    try:
        alvo = getattr(mod, classe)
    except AttributeError:
        raise ErroDeEntrada(
            f"plugin {caminho!r}: {classe!r} nao existe em {modulo!r}"
        ) from None
    return _exigir_classe(alvo, caminho)


def _exigir_classe(alvo: object, nome: str) -> type:
    if not isinstance(alvo, type):
        raise ErroDeEntrada(f"plugin {nome!r}: o alvo carregado nao e uma classe")
    return alvo
