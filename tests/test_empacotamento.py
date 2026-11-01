"""O wheel precisa levar migrações e modelos, ou `motor migrar` nasce quebrado."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def test_wheel_contem_migracoes_e_modelos(tmp_path: Path):
    if shutil.which("uv") is None:
        pytest.skip("uv fora do PATH")
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=RAIZ,
        check=True,
        capture_output=True,
    )
    wheel = next(tmp_path.glob("*.whl"))
    assert wheel.name.startswith("monitor_versoes-")
    with zipfile.ZipFile(wheel) as z:
        nomes = set(z.namelist())

    esperados = {
        "motor/migracoes/env.py",
        "motor/migracoes/script.py.mako",
        "motor/modelos/compose.yml",
        "motor/modelos/env.example",
    }
    versions = RAIZ / "motor" / "migracoes" / "versions"
    esperados |= {f"motor/migracoes/versions/{f.name}" for f in versions.glob("*.py")}
    assert esperados <= nomes
