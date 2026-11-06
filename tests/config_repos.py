"""Texto das seções `[repos.<nome>]` do config.toml central, para os testes."""

from __future__ import annotations

import re
from pathlib import Path

from motor.config import CHAVE_CAMINHO, SECAO_REPOS


def secao_repo(nome: str, caminho: str | Path | None, relativo: str = "") -> str:
    """`[repos.<nome>]` com o caminho. `relativo` usa cabeçalhos relativos à
    seção: `[tarefas]` vira `[repos.<nome>.tarefas]`."""
    relativo = re.sub(r"^\[", f"[{SECAO_REPOS}.{nome}.", relativo, flags=re.M)
    linha_caminho = "" if caminho is None else f'{CHAVE_CAMINHO} = "{caminho}"\n'
    return f"[{SECAO_REPOS}.{nome}]\n{linha_caminho}{relativo}"


def rotulo_secao(central: str | Path, nome: str) -> str:
    """O rótulo que `ConfigProjeto.arquivos` e `Escolhido.arquivo` usam."""
    return f"{central} [{SECAO_REPOS}.{nome}]"
