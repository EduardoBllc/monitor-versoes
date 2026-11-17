from __future__ import annotations

import pytest
from desktop_notifier import DesktopNotifierSync

from motor.adapters.notificador.desktop import NotificadorDesktop
from motor.errors import BackendIndisponivel

TITULO = "titulo"
CORPO = "corpo"


def test_desktop_traduz_falha_da_biblioteca(monkeypatch: pytest.MonkeyPatch):
    def quebra(*_a: object, **_k: object) -> None:
        raise RuntimeError("sem dbus")

    monkeypatch.setattr(DesktopNotifierSync, "send", quebra)

    with pytest.raises(BackendIndisponivel):
        NotificadorDesktop().notificar(TITULO, CORPO)


def test_desktop_traduz_falha_do_construtor(monkeypatch: pytest.MonkeyPatch):
    def quebra(*_a: object, **_k: object) -> None:
        raise RuntimeError("sem backend")

    monkeypatch.setattr(DesktopNotifierSync, "__init__", quebra)

    with pytest.raises(BackendIndisponivel):
        NotificadorDesktop().notificar(TITULO, CORPO)


def test_desktop_repassa_titulo_e_corpo(monkeypatch: pytest.MonkeyPatch):
    recebido: dict[str, object] = {}

    def grava(_self: object, **kwargs: object) -> None:
        recebido.update(kwargs)

    monkeypatch.setattr(DesktopNotifierSync, "send", grava)

    NotificadorDesktop().notificar(TITULO, CORPO)

    assert recebido == {"title": TITULO, "message": CORPO}
