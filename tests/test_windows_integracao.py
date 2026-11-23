"""Serviço e reinstalação de verdade no Windows, com o motor que o job do CI instala do commit.

Os testes rodam em ordem sobre a tarefa que `servico_ligado` cria e apaga.
O `LOCALAPPDATA` é o `tmp_path` do `conftest`, não o do job: o motor roda como
filho do teste, e o `resultado` é lido no mesmo ambiente que ele herda.
"""

from __future__ import annotations

import os
import subprocess
import sysconfig
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from motor import servico

# Pelo nome, na coleta: o `conftest` troca os do módulo por falsos em cada teste.
from motor.agendador import (
    FLAG_TAREFA,
    SCHTASKS,
    AcaoSchtasks,
    Sistema,
    rodar_comando_do_sistema,
)
from motor.ajudante import (
    ARQUIVO_RESULTADO,
    POWERSHELL,
    ArgPowershell,
    pasta_reinstalacao,
)
from motor.cli_instalacao import COMANDO_PLUGIN, AcaoPlugin
from motor.daemon import PORTA_PADRAO
from motor.errors import CodigoSaida
from motor.instalacao import (
    GIT,
    PACOTE_MOTOR,
    PARAMETRO_SUBDIRETORIO,
    PASTA_PLUGINS,
    PREFIXO_GIT,
)
from motor.servico import NOME_TAREFA_PROCESSO, consultar_do_sistema

VAR_INTEGRACAO_WINDOWS = "MONITOR_VERSOES_INTEGRACAO_WINDOWS"
VAR_UV_TOOL_DIR = "UV_TOOL_DIR"
VAR_UV_TOOL_BIN_DIR = "UV_TOOL_BIN_DIR"
VAR_PATH = "PATH"
PASTA_SCRIPTS = "Scripts"
ARG_COMMAND = "-Command"
ARG_VERSION = "--version"
REV_PARSE = ("rev-parse", "HEAD")
PLUGIN = "jira"
RESULTADO_OK = "0"
CODIFICACAO = "utf-8"
PRAZO_SERVE_SUBIR_S = 60
PRAZO_SERVE_VOLTAR_S = 120
PRAZO_SERVE_CAIR_S = 30
PRAZO_REINSTALACAO_S = 600
INTERVALO_S = 1
RAIZ = Path(__file__).resolve().parent.parent
NS_TAREFA = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
# Caminho no XML da tarefa e o valor que o `servico` grava nele.
VALORES_DA_TAREFA = {
    "t:Triggers/t:TimeTrigger/t:Repetition/t:Interval": "PT1M",
    "t:Principals/t:Principal/t:LogonType": "InteractiveToken",
    "t:Settings/t:MultipleInstancesPolicy": "IgnoreNew",
    "t:Settings/t:DisallowStartIfOnBatteries": "false",
    "t:Settings/t:StopIfGoingOnBatteries": "false",
    "t:Settings/t:ExecutionTimeLimit": "PT0S",
}
CAMINHO_COMANDO = "t:Actions/t:Exec/t:Command"
CAMINHO_LOGON = "t:Triggers/t:LogonTrigger"
CAMINHO_RUN_LEVEL = "t:Principals/t:Principal/t:RunLevel"
RUN_LEVEL_SEM_ELEVACAO = "LeastPrivilege"
PS_SAIDA_UTF8 = "[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false"
PS_EXPORTAR_TAREFA = (
    f"{PS_SAIDA_UTF8}; Export-ScheduledTask -TaskName '{NOME_TAREFA_PROCESSO}'"
)
# Filtrar em vez de `-Name`: sem processo, o `-Name` erra e o `-Command` sai com 1.
PS_MATAR_SERVE = (
    f"Get-Process | Where-Object {{ $_.Name -eq '{servico.EXECUTAVEL_SERVE}' }}"
    " | Stop-Process -Force"
)

pytestmark = pytest.mark.skipif(
    not os.environ.get(VAR_INTEGRACAO_WINDOWS),
    reason=f"só no job do CI do Windows, com {VAR_INTEGRACAO_WINDOWS}",
)


def _exe(pasta: Path, nome: str) -> str:
    return str(pasta / f"{nome}{sysconfig.get_config_var('EXE') or ''}")


def _serve_instalado() -> str:
    pasta = Path(os.environ[VAR_UV_TOOL_DIR]) / PACOTE_MOTOR / PASTA_SCRIPTS
    return _exe(pasta, servico.EXECUTAVEL_SERVE)


def _motor_instalado() -> str:
    return _exe(Path(os.environ[VAR_UV_TOOL_BIN_DIR]), servico.EXECUTAVEL)


def _rodar_motor(*args: str) -> subprocess.CompletedProcess[str]:
    # O `uv run` põe o .venv do projeto no PATH; o motor instalado tem de achar o próprio bin.
    caminho = f"{os.environ[VAR_UV_TOOL_BIN_DIR]}{os.pathsep}{os.environ[VAR_PATH]}"
    return subprocess.run(
        [_motor_instalado(), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding=CODIFICACAO,
        errors="replace",
        env={**os.environ, VAR_PATH: caminho},
    )


def _powershell(comando: str) -> str:
    return subprocess.run(
        [POWERSHELL, ArgPowershell.NO_PROFILE, ARG_COMMAND, comando],
        capture_output=True,
        text=True,
        encoding=CODIFICACAO,
        errors="replace",
        check=True,
    ).stdout


def _esperar(condicao: Callable[[], bool], prazo_s: float) -> bool:
    limite = time.monotonic() + prazo_s
    while not condicao():
        if time.monotonic() >= limite:
            return False
        time.sleep(INTERVALO_S)
    return True


def _serve_de_pe(prazo_s: float) -> bool:
    return _esperar(
        lambda: servico.serve_responde(PORTA_PADRAO, esperar=False), prazo_s
    )


def _serve_caiu() -> bool:
    return _esperar(
        lambda: not servico.serve_responde(PORTA_PADRAO, esperar=False),
        PRAZO_SERVE_CAIR_S,
    )


def _ler(arquivo: Path) -> str:
    return arquivo.read_text(encoding=CODIFICACAO).strip() if arquivo.exists() else ""


def _tarefa_xml() -> ET.Element:
    return ET.fromstring(_powershell(PS_EXPORTAR_TAREFA).strip())


def _consultar_tarefa() -> str | None:
    return consultar_do_sistema(
        [SCHTASKS, AcaoSchtasks.QUERY, FLAG_TAREFA, NOME_TAREFA_PROCESSO]
    )


@pytest.fixture(scope="module")
def servico_ligado() -> Iterator[str]:
    serve = _serve_instalado()
    servico.subir(Sistema.WINDOWS, Path.home(), serve, rodar_comando_do_sistema)
    # Contra o schtasks de verdade: o XML do `/query` decodificado e o texto dos argumentos.
    assert servico.rodando(Sistema.WINDOWS, Path.home(), consultar_do_sistema)
    assert not servico.login_ligado(Sistema.WINDOWS, Path.home(), consultar_do_sistema)
    servico.ligar_login(Sistema.WINDOWS, Path.home(), serve, rodar_comando_do_sistema)
    assert servico.login_ligado(Sistema.WINDOWS, Path.home(), consultar_do_sistema)
    yield serve
    # O `remover` tolera a tarefa já apagada; o serve que sobrar morre aqui.
    servico.remover(Sistema.WINDOWS, Path.home(), rodar_comando_do_sistema)
    _powershell(PS_MATAR_SERVE)


def test_ligar_sobe_o_serve(servico_ligado):
    # O primeiro início no runner pode passar dos 10 s do `serve_responde(esperar=True)`.
    assert _serve_de_pe(PRAZO_SERVE_SUBIR_S)
    tarefa = _tarefa_xml()
    assert tarefa.findtext(CAMINHO_COMANDO, namespaces=NS_TAREFA) == servico_ligado
    assert tarefa.find(CAMINHO_LOGON, NS_TAREFA) is None
    for caminho, valor in VALORES_DA_TAREFA.items():
        assert tarefa.findtext(caminho, namespaces=NS_TAREFA) == valor, caminho
    # O Export omite o RunLevel quando é o padrão; o que importa é nunca elevar.
    run_level = tarefa.findtext(CAMINHO_RUN_LEVEL, namespaces=NS_TAREFA)
    assert run_level in (None, RUN_LEVEL_SEM_ELEVACAO)


def test_serve_morto_volta(servico_ligado):
    _powershell(PS_MATAR_SERVE)

    assert _serve_caiu()
    assert _serve_de_pe(PRAZO_SERVE_VOLTAR_S)


def test_plugin_instalar_com_o_servico_ligado(servico_ligado):
    sha = subprocess.run(
        [GIT, *REV_PARSE], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout.strip()
    origem = (
        f"{PREFIXO_GIT}file:///{RAIZ.as_posix()}@{sha}"
        f"#{PARAMETRO_SUBDIRETORIO}={PASTA_PLUGINS}{PLUGIN}"
    )
    resultado = pasta_reinstalacao() / ARQUIVO_RESULTADO

    entrega = _rodar_motor(COMANDO_PLUGIN, AcaoPlugin.INSTALAR, origem)

    assert entrega.returncode == CodigoSaida.OK, entrega.stdout + entrega.stderr
    assert _esperar(lambda: bool(_ler(resultado)), PRAZO_REINSTALACAO_S)
    assert _ler(resultado) == RESULTADO_OK
    versao = _rodar_motor(ARG_VERSION)
    assert versao.returncode == CodigoSaida.OK, versao.stderr
    listar = _rodar_motor(COMANDO_PLUGIN, AcaoPlugin.LISTAR)
    assert listar.returncode == CodigoSaida.OK, listar.stderr
    assert f"{PLUGIN}:" in listar.stdout
    assert _serve_de_pe(PRAZO_SERVE_SUBIR_S)


def test_desligar_apaga_a_tarefa(servico_ligado):
    servico.remover(Sistema.WINDOWS, Path.home(), rodar_comando_do_sistema)

    assert _consultar_tarefa() is None
    assert _serve_caiu()
