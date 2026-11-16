"""Reinstalação no Windows: um PowerShell destacado troca o ambiente depois que o motor sai (decisão 043)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from motor import servico
from motor.config import diretorio_dados
from motor.errors import ErroDeEntrada, RepoOcupado
from motor.inscricoes import NOME_TRAVA_INSCRICOES
from motor.instalacao import (
    PACOTE_MOTOR,
    Registro,
    registro_de_json,
    registro_para_json,
)
from motor.trava import caminho_trava_inscricoes, travar_arquivo

PASTA_REINSTALACAO = "reinstalacao"
ARQUIVO_ANTES = "antes.json"
ARQUIVO_COMANDO = "comando.json"
ARQUIVO_RESULTADO = "resultado"
ARQUIVO_SCRIPT = "ajudante_windows.ps1"
PRAZO_PROCESSOS_S = 60
VAR_ESTADO = "MONITOR_VERSOES_AJUDANTE_ESTADO"
POWERSHELL = "powershell.exe"
POLITICA_BYPASS = "Bypass"
CODIFICACAO = "utf-8"


class ArgPowershell(StrEnum):
    NO_PROFILE = "-NoProfile"
    EXECUTION_POLICY = "-ExecutionPolicy"
    FILE = "-File"
    PASTA = "-Pasta"
    MOTOR = "-Motor"
    AMBIENTE = "-Ambiente"
    BIN = "-Bin"
    PIDS = "-Pids"
    PRAZO_PROCESSOS = "-PrazoProcessos"


def pasta_reinstalacao() -> Path:
    return Path(diretorio_dados()) / PASTA_REINSTALACAO


def ler_antes() -> Registro:
    arquivo = pasta_reinstalacao() / ARQUIVO_ANTES
    return registro_de_json(arquivo.read_text(encoding=CODIFICACAO))


def _disparar(cmd: list[str]) -> int:
    # Ramo literal: as flags só existem no Windows (ver `trava.py`).
    if sys.platform != "win32":
        return subprocess.Popen(cmd).pid
    # Sem CREATE_NO_WINDOW: o ajudante escreve no console de quem chamou.
    grupo = subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        # Fora do job do terminal, para não morrer junto com o trampolim.
        return subprocess.Popen(
            cmd, creationflags=grupo | subprocess.CREATE_BREAKAWAY_FROM_JOB
        ).pid
    except OSError:
        # Job que não deixa sair: o ajudante fica nele e torce.
        return subprocess.Popen(cmd, creationflags=grupo).pid


def entregar(
    antes: Registro, cmd: list[str], disparar: Callable[[list[str]], int] = _disparar
) -> None:
    try:
        travar_arquivo(NOME_TRAVA_INSCRICOES, caminho_trava_inscricoes()).soltar()
    except RepoOcupado:
        raise ErroDeEntrada(
            "há uma inscrição em andamento; espere ela terminar e rode de novo"
        ) from None
    pasta = pasta_reinstalacao()
    shutil.rmtree(pasta, ignore_errors=True)
    pasta.mkdir(parents=True)
    (pasta / ARQUIVO_ANTES).write_text(registro_para_json(antes), encoding=CODIFICACAO)
    (pasta / ARQUIVO_COMANDO).write_text(json.dumps(cmd), encoding=CODIFICACAO)
    # O original mora no ambiente que o `uv` vai trocar.
    script = pasta / ARQUIVO_SCRIPT
    shutil.copyfile(Path(__file__).with_name(ARQUIVO_SCRIPT), script)
    # O `uv tool install` também sobrescreve os `monitor-versoes*.exe` desta pasta.
    bin_uv = Path(shutil.which(PACOTE_MOTOR) or servico.executavel_motor()).parent
    pid = disparar(
        [
            POWERSHELL,
            ArgPowershell.NO_PROFILE,
            ArgPowershell.EXECUTION_POLICY,
            POLITICA_BYPASS,
            ArgPowershell.FILE,
            str(script),
            ArgPowershell.PASTA,
            str(pasta),
            ArgPowershell.MOTOR,
            servico.executavel_motor(),
            ArgPowershell.AMBIENTE,
            sys.prefix,
            ArgPowershell.BIN,
            str(bin_uv),
            ArgPowershell.PIDS,
            # O pai é o trampolim `monitor-versoes.exe`, que também trava a troca.
            f"{os.getpid()},{os.getppid()}",
        ]
    )
    if estado := os.environ.get(VAR_ESTADO):
        Path(estado).write_text(str(pid), encoding=CODIFICACAO)
