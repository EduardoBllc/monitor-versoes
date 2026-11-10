"""O wheel precisa levar migrações e modelos, ou `motor migrar` nasce quebrado."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
_SINAIS_SEM_REDE = ("failed to fetch", "dns error", "connect", "network", "offline")


def test_wheel_contem_migracoes_e_modelos(tmp_path: Path):
    if shutil.which("uv") is None:
        pytest.skip("uv fora do PATH")
    build_existia = (RAIZ / "build").exists()
    try:
        resultado = subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
            cwd=RAIZ,
            check=False,
            capture_output=True,
            text=True,
        )
    finally:
        # O setuptools deixa build/ na raiz; não polua o clone.
        if not build_existia:
            shutil.rmtree(RAIZ / "build", ignore_errors=True)
    if resultado.returncode != 0:
        # O build isolado baixa o setuptools: sem rede, não há o que verificar.
        if any(t in resultado.stderr.lower() for t in _SINAIS_SEM_REDE):
            pytest.skip("uv build precisa de rede para o setuptools")
        pytest.fail(resultado.stderr)
    wheel = next(tmp_path.glob("*.whl"))
    assert wheel.name.startswith("monitor_versoes-")
    with zipfile.ZipFile(wheel) as z:
        nomes = set(z.namelist())

    esperados = {
        "motor/migracoes/env.py",
        "motor/migracoes/script.py.mako",
        "motor/modelos/compose.yml",
        "motor/modelos/env.example",
        "motor/daemon/static/index.html",
    }
    versions = RAIZ / "motor" / "migracoes" / "versions"
    esperados |= {f"motor/migracoes/versions/{f.name}" for f in versions.glob("*.py")}
    assert esperados <= nomes
    assert any(
        n.startswith("motor/daemon/static/assets/") and n.endswith(".js") for n in nomes
    )
