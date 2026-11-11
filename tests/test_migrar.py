"""`motor migrar`: erros do motor ao abrir o estado."""

from __future__ import annotations

import pytest

import motor.__main__ as cli


def test_migrar_com_banco_fora_do_ar_e_erro_do_motor(monkeypatch, tmp_path, caplog):
    # Um diretório no lugar do arquivo: o SQLite não consegue abrir o estado.
    monkeypatch.setenv("DATABASE_SQLITE_PATH", str(tmp_path))

    with pytest.raises(SystemExit) as saida:
        cli.main(["migrar"])

    assert saida.value.code == 1
    assert "Erro interno fatal" not in caplog.text
    assert "DATABASE_SQLITE_PATH" in caplog.text
