"""O núcleo não carrega premissas do esquema `vendabem`: nome da principal e
tipos de versão vivem só no esquema que os define."""

from __future__ import annotations

import re
from pathlib import Path

_MOTOR = Path(__file__).resolve().parent.parent / "motor"
_PREMISSAS = re.compile(r"master|VersionType|inferir_tipo|fechada|ajustada", re.I)
# O esquema que define as premissas e as migrações, que recriam o check antigo
# no downgrade.
_EXCLUIDOS = (_MOTOR / "esquemas" / "vendabem.py", _MOTOR / "migracoes" / "versions")


def _excluido(caminho: Path) -> bool:
    return any(caminho == e or e in caminho.parents for e in _EXCLUIDOS)


def test_nucleo_nao_cita_premissas_do_esquema_vendabem():
    ocorrencias = [
        f"{caminho.relative_to(_MOTOR.parent)}:{numero}: {linha.strip()}"
        for caminho in sorted(_MOTOR.rglob("*.py"))
        if not _excluido(caminho)
        for numero, linha in enumerate(caminho.read_text().splitlines(), start=1)
        if _PREMISSAS.search(linha)
    ]

    assert ocorrencias == [], "\n".join(ocorrencias)
