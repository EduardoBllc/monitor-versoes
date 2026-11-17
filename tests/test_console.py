from __future__ import annotations

import subprocess
from datetime import timedelta
from typing import Any

import pytest

from motor import console, novidades, teste_config
from motor.adapters.git.subprocess import _rodar_git
from motor.config_edicao import ler_para_edicao
from motor.diagnostico import PecaTestavel
from motor.inscricoes import Inscricao, disparar_subprocesso

SENTINELA = 1 << 29
GIT_VERSAO = ["git", "--version"]
REPO = "repo-a"
VERSAO = "1.0"
INTERVALO = timedelta(minutes=30)


def test_sem_console_processos_nao_abrem_janela(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(console, "FLAGS_SEM_JANELA", SENTINELA)
    flags: list[int] = []

    def falso(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        flags.append(kw["creationflags"])
        if "timeout" in kw:
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", falso)
    monkeypatch.setattr(novidades, "_ssh_da_config", lambda: None)
    _rodar_git(GIT_VERSAO)
    disparar_subprocesso(Inscricao(REPO, VERSAO, INTERVALO, None), {})
    novidades.rodar_git(GIT_VERSAO, {})
    teste_config.testar([], ler_para_edicao().versao, PecaTestavel.PRS, None)
    assert flags
    assert all(f & SENTINELA for f in flags)
