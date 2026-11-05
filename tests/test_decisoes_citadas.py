"""Toda decisão citada no código existe: decisão renumerada deixaria link para
outra decisão ou para lugar nenhum."""

from __future__ import annotations

import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_DECISAO = re.compile(r"docs/decisoes/\d{3}-[\w-]+\.md")


def test_decisoes_citadas_no_codigo_existem():
    quebradas = [
        f"{caminho.relative_to(_RAIZ)}:{numero}: {citada}"
        for pasta in (_RAIZ / "motor", _RAIZ / "tests")
        for caminho in sorted(pasta.rglob("*.py"))
        for numero, linha in enumerate(caminho.read_text().splitlines(), start=1)
        for citada in _DECISAO.findall(linha)
        if not (_RAIZ / citada).is_file()
    ]

    assert quebradas == [], "\n".join(quebradas)
