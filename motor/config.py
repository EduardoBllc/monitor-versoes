"""Configuracao lida do ambiente selecionado pelo CLI."""

from __future__ import annotations

import os
from urllib.parse import quote

from motor.errors import MotorError

_CAMPOS_BANCO = ("HOST", "PORT", "NAME", "USER", "PASSWORD")

#: Worktrees de versao que ficam em disco depois de cada operacao.
_WORKTREES_MANTIDAS_PADRAO = 3


def database_url() -> str:
    """Monta a URL do Postgres a partir das partes.

    As partes existem separadas porque o compose.yml le as mesmas variaveis do
    mesmo .env — uma fonte so para aplicacao e container.
    """
    v = {c: os.environ.get(f"DATABASE_{c}", "") for c in _CAMPOS_BANCO}
    if faltando := [f"DATABASE_{c}" for c, valor in v.items() if not valor]:
        raise MotorError(f"faltando no .env: {', '.join(faltando)}")
    # create_engine converte a porta na hora: um typo aqui viraria ValueError,
    # que o __main__ trata como bug (traceback) em vez de erro do operador.
    if not v["PORT"].isdigit():
        raise MotorError(f"DATABASE_PORT invalido: {v['PORT']!r} (esperado numero)")

    # quote em usuario e senha: um '@' na senha monta uma URL sintaticamente
    # valida apontando para outro host, e o erro que aparece e "conexao
    # recusada", nao "senha invalida".
    return (
        f"postgresql+psycopg://{quote(v['USER'], safe='')}:"
        f"{quote(v['PASSWORD'], safe='')}@{v['HOST']}:{v['PORT']}/{v['NAME']}"
    )


def worktrees_mantidas() -> int:
    """Quantas worktrees de versao sobrevivem a cada operacao.

    Levantar uma worktree e um checkout inteiro — depois do fetch, a espera mais
    longa do motor. Mantendo as ultimas em disco, o run seguinte na mesma versao
    so reusa o diretorio que ja esta la.

    `0` e valor valido, e significa o comportamento historico (descarta no fim
    de cada run) — por isso o default nao pode sair de um `or`. Valor nao
    numerico e erro do operador, nao default calado: `WORKTREES_MANTIDAS=tres`
    cairia em 3 e a pessoa nunca saberia que nao configurou nada.
    """
    valor = os.environ.get("WORKTREES_MANTIDAS", "").strip()
    if not valor:
        return _WORKTREES_MANTIDAS_PADRAO
    # isdigit recusa "-1", "1.5" e "3 worktrees" de uma vez; int() sozinho
    # aceitaria negativo, que nao tem significado aqui.
    if not valor.isdigit():
        raise MotorError(
            f"WORKTREES_MANTIDAS invalido: {valor!r} (esperado inteiro >= 0)"
        )
    return int(valor)
