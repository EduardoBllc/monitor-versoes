"""Fonte de tarefas das jornadas da web: um JSON `{versao: [chamado, ...]}`."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

#: Chave do `[tarefas]` com o caminho do JSON.
CHAVE_MAPA = "mapa"


class TarefasDoArquivo:
    # Relê o arquivo a cada busca: a jornada muda o rastreador editando o JSON.
    def __init__(self, tarefas: Mapping[str, object], arquivos: object) -> None:
        self.mapa = Path(str(tarefas[CHAVE_MAPA]))

    def fetch(self, versao: str, /) -> list[str]:
        mapa: dict[str, list[str]] = json.loads(self.mapa.read_text())
        return mapa.get(versao, [])
