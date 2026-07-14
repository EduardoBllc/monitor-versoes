"""Transcrição de internal/adapters/tasksource/manuallist_test.go."""

from __future__ import annotations

import pytest

from motor.adapters.tasksource.manuallist import ManualList
from motor.errors import MotorError


def test_manual_list_fetch(tmp_path):
    caminho = tmp_path / "lista.txt"
    caminho.write_text(
        "# comentario\n"
        "255514;VB-2354;Logs pedidos ecommerce\n"
        "255074;VB-2391;Uappi status pedido\n"
    )

    fonte = ManualList(caminho=str(caminho))
    tasks = fonte.fetch("13.7.0")

    assert len(tasks) == 2
    assert tasks[0].chamado == "255514"
    assert tasks[0].task == "VB-2354"


def test_manual_list_linha_invalida(tmp_path):
    caminho = tmp_path / "lista.txt"
    caminho.write_text("linha sem separador\n")

    fonte = ManualList(caminho=str(caminho))
    with pytest.raises(MotorError):
        fonte.fetch("13.7.0")
