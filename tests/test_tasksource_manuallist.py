from __future__ import annotations

import pytest

from motor.adapters.tasksource.manuallist import ManualList
from motor.errors import MotorError


def test_manuallist_le_um_chamado_por_linha(tmp_path):
    arquivo = tmp_path / "lista.txt"
    arquivo.write_text("# comentario\n123456\n\n999111\n", encoding="utf-8")

    assert ManualList(caminho=str(arquivo)).fetch("13.34.0") == ["123456", "999111"]


def test_manuallist_recusa_linha_que_nao_e_numero(tmp_path):
    arquivo = tmp_path / "lista.txt"
    arquivo.write_text("VB-2354\n", encoding="utf-8")

    with pytest.raises(MotorError, match="linha invalida"):
        ManualList(caminho=str(arquivo)).fetch("13.34.0")
