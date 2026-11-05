"""Notificação desktop via desktop-notifier (Linux, macOS)."""

from __future__ import annotations

from desktop_notifier import DesktopNotifierSync

from motor.errors import BackendIndisponivel


class NotificadorDesktop:
    def __init__(self) -> None:
        self._notifier = DesktopNotifierSync(app_name="monitor-versoes")

    def notificar(self, titulo: str, corpo: str, /) -> None:
        try:
            self._notifier.send(title=titulo, message=corpo)
        except Exception as e:  # a lib levanta tipos variados por backend
            raise BackendIndisponivel(f"notificação desktop: {e}") from e
