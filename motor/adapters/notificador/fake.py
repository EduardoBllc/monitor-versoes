from __future__ import annotations

from motor.errors import BackendIndisponivel


class FakeNotificador:
    def __init__(self, falhar: bool = False) -> None:
        self.falhar = falhar
        self.enviadas: list[tuple[str, str]] = []

    def notificar(self, titulo: str, corpo: str, /) -> None:
        if self.falhar:
            raise BackendIndisponivel("notificador fake configurado para falhar")
        self.enviadas.append((titulo, corpo))
