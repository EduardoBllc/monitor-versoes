"""Carregador de plugins: entry points instalados ou import direto."""

from __future__ import annotations

import functools
import importlib
import os
import sys
from importlib.metadata import EntryPoint, entry_points

from motor.errors import ErroDeEntrada

#: Separa `modulo:Classe`; sem ele, o nome é de um entry point.
MARCADOR_IMPORT = ":"


def pontos_instalados(grupo: str) -> tuple[EntryPoint, ...]:
    """Entry points do `grupo`; só relê os pacotes quando uma pasta do `sys.path` muda.

    Ler custa milissegundos (abre o `entry_points.txt` de cada pacote), e o
    catálogo da configuração consulta dezenas de vezes por operação.
    """
    return _pontos_em_cache(grupo, _assinatura_dos_pacotes())


#: Grupos x estados dos pacotes guardados; o estado antigo sai do cache sozinho.
MAXIMO_EM_CACHE = 32


# Editar só o `entry_points.txt` de um dist-info existente não muda a pasta e não
# invalida; aceito porque instalar, atualizar ou remover pacote cria ou apaga dist-info.
def _assinatura_dos_pacotes() -> tuple[tuple[str, int | None], ...]:
    return tuple((p, _mtime(p)) for p in sys.path)


# Sem `isdir` antes: a pasta pode sumir entre a checagem e o `stat` (reinstalação
# com o daemon no ar), e o `entry_points()` também tolera entrada ausente.
def _mtime(caminho: str) -> int | None:
    try:
        return os.stat(caminho).st_mtime_ns
    except OSError:
        return None


@functools.lru_cache(maxsize=MAXIMO_EM_CACHE)
def _pontos_em_cache(
    grupo: str, _assinatura: tuple[tuple[str, int | None], ...]
) -> tuple[EntryPoint, ...]:
    return tuple(entry_points(group=grupo))


def nomes_instalados(grupo: str) -> list[str]:
    """Nomes dos entry points instalados no `grupo`, em ordem."""
    return sorted(ep.name for ep in pontos_instalados(grupo))


def carregar_plugin(grupo: str, nome: str) -> type:
    """Resolve `nome` para uma classe.

    Sem `:`, e o nome de um entry point do `grupo`. Com `:` (`modulo:Classe`), e
    import direto.
    """
    if MARCADOR_IMPORT in nome:
        return _importar(nome)
    pontos = {ep.name: ep for ep in pontos_instalados(grupo)}
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
    modulo, _, classe = caminho.partition(MARCADOR_IMPORT)
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
