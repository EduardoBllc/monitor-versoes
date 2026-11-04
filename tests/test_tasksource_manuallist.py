from __future__ import annotations

import pytest

from motor.adapters.tasksource.manuallist import ManualList
from motor.errors import ErroDeEntrada


def test_manuallist_le_um_chamado_por_linha(tmp_path):
    arquivo = tmp_path / "lista.txt"
    arquivo.write_text("# comentario\n123456\n\nPAY-123\n", encoding="utf-8")

    assert ManualList(caminho=str(arquivo)).fetch("13.34.0") == ["123456", "PAY-123"]


@pytest.mark.parametrize("linha", ["PAY 123", "PAY/1", "-1"])
def test_manuallist_recusa_linha_que_nao_e_id(tmp_path, linha):
    arquivo = tmp_path / "lista.txt"
    arquivo.write_text(f"{linha}\n", encoding="utf-8")

    with pytest.raises(ErroDeEntrada):
        ManualList(caminho=str(arquivo)).fetch("13.34.0")
