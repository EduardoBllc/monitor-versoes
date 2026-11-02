"""`motor init`: escreve `compose.yml` e `.env` a partir dos modelos do pacote."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

# (modelo no pacote, arquivo escrito no destino)
_ARQUIVOS = (("compose.yml", "compose.yml"), ("env.example", ".env"))


def iniciar(destino: Path) -> list[str]:
    """Copia os modelos para `destino` sem sobrescrever; devolve as mensagens."""
    modelos = files("motor") / "modelos"
    mensagens: list[str] = []
    for modelo, nome in _ARQUIVOS:
        alvo = destino / nome
        if alvo.exists():
            mensagens.append(f"{nome} já existe; mantido")
            continue
        alvo.write_text(
            (modelos / modelo).read_text(encoding="utf-8"), encoding="utf-8"
        )
        mensagens.append(f"criado {nome}")
    return mensagens
