"""Configuracao lida do ambiente (.env carregado pelo __main__)."""

from __future__ import annotations

import os
from urllib.parse import quote

from motor.errors import MotorError

_CAMPOS_BANCO = ("HOST", "PORT", "NAME", "USER", "PASSWORD")


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
