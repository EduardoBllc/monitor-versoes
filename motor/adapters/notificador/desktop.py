"""Notificação desktop via desktop-notifier (Linux, macOS)."""

from __future__ import annotations

from desktop_notifier import DesktopNotifierSync

from motor.errors import BackendIndisponivel

NOME_DO_APP = "monitor-versoes"


class NotificadorDesktop:
    def notificar(self, titulo: str, corpo: str, /) -> None:
        # Construir dentro do try: o backend (D-Bus etc.) pode falhar já no construtor.
        try:
            DesktopNotifierSync(app_name=NOME_DO_APP).send(title=titulo, message=corpo)
        except Exception as e:  # a lib levanta tipos variados por backend
            raise BackendIndisponivel(f"notificação desktop: {e}") from e
