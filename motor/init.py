"""`motor init`: escreve `compose.yml` a partir do modelo do pacote."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

MODELO_COMPOSE = "compose.yml"


def iniciar(destino: Path, config_em: str) -> list[str]:
    """Copia o modelo para `destino` sem sobrescrever; devolve as mensagens."""
    alvo = destino / MODELO_COMPOSE
    if alvo.exists():
        mensagens = [f"{MODELO_COMPOSE} já existe; mantido"]
    else:
        modelo = files("motor") / "modelos" / MODELO_COMPOSE
        alvo.write_text(modelo.read_text(encoding="utf-8"), encoding="utf-8")
        mensagens = [f"criado {MODELO_COMPOSE}"]
    mensagens.append(
        f"o motor se configura pelo [ambiente] de {config_em}; o README explica as chaves"
    )
    return mensagens
