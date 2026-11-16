"""Flags para que subprocessos não abram janela de console (serviço do Windows sem console)."""

from __future__ import annotations

import subprocess
import sys

# Literal `sys.platform == "win32"`: o mypy só pula o ramo do outro sistema assim.
if sys.platform == "win32":
    import ctypes

    FLAGS_SEM_JANELA: int = (
        subprocess.CREATE_NO_WINDOW
        if ctypes.windll.kernel32.GetConsoleWindow() == 0
        else 0
    )
else:
    FLAGS_SEM_JANELA = 0
