"""Os arquivos inline do README não podem divergir dos modelos do pacote."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("modelo", ["compose.yml", "env.example"])
def test_readme_traz_o_modelo_inline(modelo: str):
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    achado = re.search(
        rf"<!-- modelo: {re.escape(modelo)} -->\n```\w*\n(.*?)\n```", readme, re.S
    )

    assert achado, f"README sem o marcador do modelo {modelo}"
    esperado = (RAIZ / "motor" / "modelos" / modelo).read_text(encoding="utf-8")
    assert achado.group(1) == esperado.rstrip("\n")
