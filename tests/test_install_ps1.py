from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pytest

from motor import ajudante, config, servico
from motor.__main__ import COMANDO_DESINSTALAR
from motor.agendador import (
    FLAG_FORCAR_SCHTASKS,
    FLAG_TAREFA,
    NOME_TAREFA_INSCRICOES,
    SCHTASKS,
    AcaoSchtasks,
)
from motor.ajudante import (
    ARQUIVO_RESULTADO,
    PASTA_REINSTALACAO,
    POLITICA_BYPASS,
    POWERSHELL,
    VAR_ESTADO,
    ArgPowershell,
)
from motor.cli_instalacao import COMANDO_ATUALIZAR_MOTOR, COMANDO_PLUGIN, AcaoPlugin
from motor.errors import CodigoSaida
from motor.instalacao import PACOTE_MOTOR, UV, ArgUv
from motor.servico import NOME_TAREFA_SERVE
from tests.plataforma import PLATAFORMA_WINDOWS

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "install.ps1"
AJUDANTE = RAIZ / "motor" / ajudante.ARQUIVO_SCRIPT
BOM_UTF8 = b"\xef\xbb\xbf"
PWSH = "pwsh"
URL_REPO = "https://github.com/EduardoBllc/monitor-versoes"
URL_INSTALL_SH = (
    "https://raw.githubusercontent.com/EduardoBllc/monitor-versoes/main/install.sh"
)
URL_GIT_WINDOWS = "https://git-scm.com/download/win"
INSTALAR_GIT_WINGET = "winget install --id Git.Git -e"
VAR_URL_INSTALADOR_UV = "MONITOR_VERSOES_URL_INSTALADOR_UV"
# Onde o instalador da Astral põe o uv, sem XDG_BIN_HOME.
PASTA_BIN_INSTALADOR_UV = Path(".local", "bin")
VARS_HERDADAS_FORA = (
    "XDG_BIN_HOME",
    "UV_INSTALL_DIR",
    VAR_ESTADO,
    VAR_URL_INSTALADOR_UV,
)
ULTIMA_TAG = "v0.10.0"
VERSAO_ANTIGA = "v0.2.0"
TAGS_REMOTAS = (VERSAO_ANTIGA, "v0.9.0", ULTIMA_TAG, "v1.0.0-rc1", "latest")
SUBPASTA_JIRA = "#subdirectory=plugins/jira"
PLUGIN_GIT = (
    "git+https://github.com/exemplo/monitor-versoes-plugin"
    "@99ffe18fdf9f7268abfaf2c611f87e4b10db50c5"
)
NOME_PLUGIN_GIT = "monitor-versoes-plugin"
NOME_PLUGIN_LOCAL = "plugum"
NOME_PLUGIN_JIRA = "monitor-versoes-jira"
EXTRAS_UV = "[extras: anthropic]"
PREFIXO_TAG_LS_REMOTE = "0000\\trefs/tags/"
ARG_PYTHON_CODIGO = "-c"
CODIFICACAO = "utf-8"
MARCA_OK = "✔"
MARCA_FALHA = "✖"
MARCA_CONSOLE = "stdin-console"
MARCA_INSTALADOR = "instalador-uv"
VIVO = "VIVO"
DICA_PATH = "uv tool update-shell"
AVISO_BANCO = "DATABASE_SQLITE_PATH"
FRASE_UV_FICOU = "O uv continua instalado"
FRASE_SEM_GIT = "git não encontrado"
FRASE_ULTIMA_RELEASE = f"última release: {ULTIMA_TAG}"
SAIDA_UV_NAO_INSTALADO = 2
PAGINA_OEM = 437
RESULTADO_OK = "0"
RESULTADO_FALHA = "1"
ESPERA_DO_AJUDANTE_S = 2
ESPERA_DO_PROCESSO_S = 3
PROCESSO_LONGO_S = 60
PRAZO_CURTO_S = 1
MARCA_PROCESSO_FIM = "processo do ambiente encerrado"
PYTHON_DO_VENV = Path("Scripts", "python.exe")
VAR_PRAZO_PROCESSOS = "MONITOR_VERSOES_PRAZO_PROCESSOS_S"
LIMITE_TESTE_S = 180
SUFIXO_CMD = ".cmd"
FLAG_HELP = "--help"
FLAG_BIN = "--bin"
ARQUIVO_FALSO = "falso.py"
ARQUIVO_INSTALADOR = "instalador.ps1"
VAR_PATH = "PATH"
VAR_SYSTEMROOT = "SystemRoot"
VAR_USERPROFILE = "USERPROFILE"
VAR_UV_TOOL_BIN_DIR = "UV_TOOL_BIN_DIR"
VAR_UV_TOOL_DIR = "UV_TOOL_DIR"
VAR_LOCALAPPDATA = config.VAR_LOCALAPPDATA
VAR_APPDATA = config.VAR_APPDATA
PASTA_SYSTEM32 = "System32"
ARQUIVO_LOG = "log"


class Pasta(StrEnum):
    HOME = "home"
    FALSOS = "falsos"
    PACOTES = "pacotes"
    TOOLBIN = "toolbin"
    TOOLDIR = "tooldir"
    LOCAL = "localappdata"
    ROAMING = "appdata"


class Var(StrEnum):
    LOG = "FALSO_LOG"
    TAGS = "FALSO_TAGS"
    LINHA_UV = "FALSO_LINHA_UV"
    MOTOR = "FALSO_MOTOR"
    SAIDA_UV = "FALSO_SAIDA_UV"
    SAIDA_QUERY = "FALSO_SAIDA_QUERY"
    SAIDA_SONDA = "FALSO_SAIDA_SONDA"
    SAIDA_ATUALIZAR = "FALSO_SAIDA_ATUALIZAR"
    SAIDA_DESINSTALAR = "FALSO_SAIDA_DESINSTALAR"
    RESULTADO = "FALSO_RESULTADO"
    ARQUIVO_RESULTADO = "FALSO_ARQUIVO_RESULTADO"


class Falso(StrEnum):
    GIT = "git"
    UV = UV
    WINGET = "winget"
    SCHTASKS = SCHTASKS
    MOTOR = servico.EXECUTAVEL


class AcaoUv(StrEnum):
    DIR = "dir"
    INSTALL = ArgUv.INSTALL
    LIST = "list"
    UNINSTALL = "uninstall"


class ArgScript(StrEnum):
    COMMAND = "-Command"
    SEM_CONFIGURAR = "-SemConfigurar"
    DESINSTALAR = "-Desinstalar"
    DESCONHECIDO = "-Foo"


class Caminho(StrEnum):
    NOVA = "instalação nova"
    REINSTALACAO = "reinstalação"


# Um só programa para todos os `.cmd` falsos: o primeiro argumento é o nome do falso.
_FALSO = f"""
import os, shutil, subprocess, sys
from pathlib import Path

nome, args = sys.argv[1], sys.argv[2:]
env = os.environ
with open(env["{Var.LOG}"], "a", encoding="utf-8") as log:
    log.write(" ".join([nome, *args]) + "\\n")
bin_uv = Path(env["{VAR_UV_TOOL_BIN_DIR}"])
dir_uv = Path(env["{VAR_UV_TOOL_DIR}"])
motor = bin_uv / "{Falso.MOTOR}{SUFIXO_CMD}"
codigo = 0
if nome == "{Falso.GIT}":
    for tag in env["{Var.TAGS}"].split():
        print("{PREFIXO_TAG_LS_REMOTE}" + tag)
elif nome == "{Falso.UV}" and args[:1] == ["{ArgUv.TOOL}"]:
    acao = args[1]
    if acao == "{AcaoUv.DIR}":
        print(bin_uv if args[2:] == ["{FLAG_BIN}"] else dir_uv)
    elif acao == "{AcaoUv.INSTALL}":
        shutil.copy(env["{Var.MOTOR}"], bin_uv)
        codigo = int(env["{Var.SAIDA_UV}"])
    elif acao == "{AcaoUv.LIST}" and motor.exists():
        print(env["{Var.LINHA_UV}"])
    elif acao == "{AcaoUv.UNINSTALL}":
        if motor.exists():
            motor.unlink()
        else:
            codigo = {SAIDA_UV_NAO_INSTALADO}
elif nome == "{Falso.SCHTASKS}" and args[:1] == ["{AcaoSchtasks.QUERY}"]:
    codigo = int(env["{Var.SAIDA_QUERY}"])
elif nome == "{Falso.MOTOR}":
    if args == ["{COMANDO_ATUALIZAR_MOTOR}", "{FLAG_HELP}"]:
        codigo = int(env["{Var.SAIDA_SONDA}"])
    elif args == ["{COMANDO_ATUALIZAR_MOTOR}"]:
        codigo = int(env["{Var.SAIDA_ATUALIZAR}"])
        if "{Var.RESULTADO}" in env:
            # O ajudante falso: dorme e depois grava o resultado.
            filho = subprocess.Popen(
                [
                    sys.executable,
                    "{ARG_PYTHON_CODIGO}",
                    "import pathlib, sys, time; time.sleep({ESPERA_DO_AJUDANTE_S}); "
                    "p = pathlib.Path(sys.argv[1]); p.parent.mkdir(parents=True, exist_ok=True); "
                    "p.write_text(sys.argv[2])",
                    env["{Var.ARQUIVO_RESULTADO}"],
                    env["{Var.RESULTADO}"],
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            Path(env["{VAR_ESTADO}"]).write_text(str(filho.pid))
    elif args == ["{servico.COMANDO_CONFIGURAR}"] and sys.stdin.isatty():
        with open(env["{Var.LOG}"], "a", encoding="utf-8") as log:
            log.write("{MARCA_CONSOLE}\\n")
    elif args == ["{COMANDO_DESINSTALAR}"]:
        codigo = int(env["{Var.SAIDA_DESINSTALAR}"])
sys.exit(codigo)
"""


def _cascas() -> list[object]:
    return [
        pytest.param(POWERSHELL, id="5.1"),
        pytest.param(
            PWSH,
            id="7",
            marks=pytest.mark.skipif(shutil.which(PWSH) is None, reason="sem pwsh"),
        ),
    ]


@dataclass
class Maquina:
    raiz: Path
    casca: str
    falsos: Path
    pacotes: Path
    toolbin: Path
    log: Path
    env: dict[str, str]

    def com(self, nome: str) -> Path:
        arquivo = self.falsos / f"{nome}{SUFIXO_CMD}"
        _falso_cmd(arquivo, nome, self.raiz / ARQUIVO_FALSO)
        return arquivo

    def sem(self, nome: str) -> None:
        (self.falsos / f"{nome}{SUFIXO_CMD}").unlink()

    def instalar_motor(self) -> None:
        shutil.copy(self.env[Var.MOTOR], self.toolbin)

    @property
    def le_utf8_pelo_file(self) -> bool:
        """Sem BOM, o 5.1 lê o `-File` como ANSI: só o 7 mostra os acentos certos."""
        return Path(self.casca).stem.lower() == PWSH

    @property
    def motor(self) -> Path:
        return self.toolbin / f"{servico.EXECUTAVEL}{SUFIXO_CMD}"

    def chamadas(self) -> list[str]:
        if not self.log.exists():
            return []
        texto = self.log.read_text(encoding=CODIFICACAO)
        return [linha.strip() for linha in texto.splitlines()]

    def comando(self, *args: str) -> list[str]:
        return [
            self.casca,
            ArgPowershell.NO_PROFILE,
            ArgPowershell.EXECUTION_POLICY,
            POLITICA_BYPASS,
            *args,
        ]

    def _capturar(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.comando(*args),
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding=CODIFICACAO,
            errors="replace",
            timeout=LIMITE_TESTE_S,
            check=False,
        )

    def rodar(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Pelo `-File`, sem console interativo."""
        return self._capturar(ArgPowershell.FILE, str(SCRIPT), *args)

    def rodar_bloco(
        self, *args: str, antes: str | None = None, depois: str
    ) -> subprocess.CompletedProcess[str]:
        """Como o `irm … | iex`: o texto baixado em UTF-8 vira um bloco na sessão."""
        carregar = (
            f"$c = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes('{SCRIPT}')); "
            f"& ([scriptblock]::Create($c)) {' '.join(args)}"
        )
        partes = [carregar, depois] if antes is None else [antes, carregar, depois]
        return self._capturar(ArgScript.COMMAND, "; ".join(partes))


def _falso_cmd(arquivo: Path, nome: str, programa: Path) -> None:
    arquivo.write_text(
        encoding=CODIFICACAO,
        data=f'@echo off\r\n"{sys.executable}" "{programa}" {nome} %*\r\n'
        "exit /b %errorlevel%\r\n",
    )


@pytest.fixture(params=_cascas())
def maquina(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Maquina]:
    if sys.platform != PLATAFORMA_WINDOWS:
        pytest.skip("install.ps1 é PowerShell do Windows")
    casca = shutil.which(request.param)
    assert casca is not None, request.param
    home, falsos, pacotes, toolbin, tooldir, local, roaming = (
        tmp_path / pasta for pasta in Pasta
    )
    for pasta in (home, falsos, pacotes, toolbin, tooldir, local, roaming):
        pasta.mkdir()
    (tmp_path / ARQUIVO_FALSO).write_text(_FALSO, encoding=CODIFICACAO)
    motor = pacotes / f"{servico.EXECUTAVEL}{SUFIXO_CMD}"
    _falso_cmd(motor, Falso.MOTOR, tmp_path / ARQUIVO_FALSO)
    system32 = Path(os.environ[VAR_SYSTEMROOT], PASTA_SYSTEM32)
    powershell = shutil.which(POWERSHELL)
    assert powershell is not None
    env = {k: v for k, v in os.environ.items() if k not in VARS_HERDADAS_FORA}
    env |= {
        # Sem o PATH do runner: o git e o uv de verdade ficam de fora.
        VAR_PATH: os.pathsep.join(
            [
                str(falsos),
                str(system32),
                os.environ[VAR_SYSTEMROOT],
                str(Path(powershell).parent),
            ]
        ),
        VAR_USERPROFILE: str(home),
        VAR_UV_TOOL_BIN_DIR: str(toolbin),
        VAR_UV_TOOL_DIR: str(tooldir),
        VAR_LOCALAPPDATA: str(local),
        VAR_APPDATA: str(roaming),
        Var.LOG: str(tmp_path / ARQUIVO_LOG),
        Var.TAGS: " ".join(TAGS_REMOTAS),
        Var.LINHA_UV: f"{PACOTE_MOTOR} {VERSAO_ANTIGA}",
        Var.MOTOR: str(motor),
        Var.SAIDA_UV: str(CodigoSaida.OK),
        Var.SAIDA_QUERY: str(CodigoSaida.ERRO),
        Var.SAIDA_SONDA: str(CodigoSaida.OK),
        Var.SAIDA_ATUALIZAR: str(CodigoSaida.OK),
        Var.SAIDA_DESINSTALAR: str(CodigoSaida.OK),
    }
    m = Maquina(tmp_path, casca, falsos, pacotes, toolbin, tmp_path / ARQUIVO_LOG, env)
    for falso in (Falso.GIT, Falso.UV, Falso.SCHTASKS):
        m.com(falso)
    yield m


def _instalacao(tag: str, *, reinstalar: bool = False) -> str:
    flag = f" {ArgUv.REINSTALL}" if reinstalar else ""
    return f"{UV} {ArgUv.TOOL} {AcaoUv.INSTALL}{flag} {PACOTE_MOTOR} @ git+{URL_REPO}@{tag}"


def _schtasks(acao: AcaoSchtasks, tarefa: str = NOME_TAREFA_SERVE) -> str:
    return f"{SCHTASKS} {acao} {FLAG_TAREFA} {tarefa}"


def _configurar() -> str:
    return f"{servico.EXECUTAVEL} {servico.COMANDO_CONFIGURAR}"


def test_sem_uv_instala_uv_e_a_ultima_release(maquina):
    uv = maquina.com(Falso.UV)
    shutil.move(uv, maquina.pacotes / uv.name)
    instalador = maquina.raiz / ARQUIVO_INSTALADOR
    # O `exit` no fim só não derruba o script se o instalador rodar num processo filho.
    instalador.write_text(
        encoding=CODIFICACAO,
        data=f"$destino = Join-Path -Path $env:{VAR_USERPROFILE} -ChildPath '{PASTA_BIN_INSTALADOR_UV}'\n"
        "New-Item -ItemType Directory -Force -Path $destino | Out-Null\n"
        f"Copy-Item -LiteralPath '{maquina.pacotes / uv.name}' -Destination $destino\n"
        f"Add-Content -LiteralPath '{maquina.log}' -Value '{MARCA_INSTALADOR}'\n"
        "exit\n",
    )
    maquina.env[VAR_URL_INSTALADOR_UV] = instalador.as_uri()

    r = maquina.rodar()

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    chamadas = maquina.chamadas()
    assert MARCA_INSTALADOR in chamadas
    assert _instalacao(ULTIMA_TAG) in chamadas
    assert MARCA_OK in r.stdout
    assert _configurar() in r.stdout


@pytest.mark.parametrize("com_winget", [True, False])
def test_sem_git_para_antes_de_instalar(maquina, com_winget):
    maquina.sem(Falso.GIT)
    if com_winget:
        maquina.com(Falso.WINGET)

    r = maquina.rodar()

    assert r.returncode != CodigoSaida.OK
    assert (INSTALAR_GIT_WINGET if com_winget else URL_GIT_WINDOWS) in r.stdout
    if maquina.le_utf8_pelo_file:
        assert FRASE_SEM_GIT in r.stdout
    assert not [c for c in maquina.chamadas() if c.startswith(Falso.UV)]


def test_falha_no_iex_nao_fecha_a_sessao(maquina):
    maquina.env[Var.SAIDA_UV] = str(CodigoSaida.ERRO)

    r = maquina.rodar_bloco(depois=f"'{VIVO}'")

    assert MARCA_FALHA in r.stdout, r.stdout + r.stderr
    assert r.stdout.splitlines()[-1] == VIVO


def test_falha_pelo_file_sai_com_codigo_diferente_de_0(maquina):
    maquina.env[Var.SAIDA_UV] = str(CodigoSaida.ERRO)

    r = maquina.rodar()

    assert r.returncode != CodigoSaida.OK
    assert MARCA_FALHA in r.stdout


@pytest.mark.parametrize(
    "args",
    [(ArgScript.SEM_CONFIGURAR, ArgScript.DESINSTALAR), (ArgScript.DESCONHECIDO,)],
)
def test_parametros_juntos_ou_desconhecidos_recusados(maquina, args):
    r = maquina.rodar(*args)

    assert r.returncode != CodigoSaida.OK
    assert maquina.chamadas() == []


@pytest.mark.parametrize("resultado", [RESULTADO_OK, RESULTADO_FALHA])
def test_ja_instalado_roda_atualizar_motor_e_espera_o_ajudante(maquina, resultado):
    maquina.env |= {
        Var.RESULTADO: resultado,
        Var.ARQUIVO_RESULTADO: str(
            Path(maquina.env[VAR_LOCALAPPDATA], config.DIRETORIO_APP)
            / PASTA_REINSTALACAO
            / ARQUIVO_RESULTADO
        ),
    }
    maquina.instalar_motor()

    r = maquina.rodar(ArgScript.SEM_CONFIGURAR)

    assert f"{servico.EXECUTAVEL} {COMANDO_ATUALIZAR_MOTOR}" in maquina.chamadas()
    assert not [
        c
        for c in maquina.chamadas()
        if c.startswith(f"{UV} {ArgUv.TOOL} {AcaoUv.INSTALL}")
    ]
    # O resultado só existe depois que o ajudante termina: o ✔ prova a espera.
    if resultado == RESULTADO_OK:
        assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
        assert MARCA_FALHA not in r.stdout
    else:
        assert r.returncode != CodigoSaida.OK
        assert MARCA_FALHA in r.stdout


@pytest.mark.parametrize(
    ("sonda", "atualizar"),
    [
        (CodigoSaida.ERRO, CodigoSaida.OK),
        (CodigoSaida.OK, CodigoSaida.ERRO),
    ],
)
def test_falha_do_motor_instalado_nao_reinstala(maquina, sonda, atualizar):
    maquina.env |= {Var.SAIDA_SONDA: str(sonda), Var.SAIDA_ATUALIZAR: str(atualizar)}
    maquina.instalar_motor()

    r = maquina.rodar(ArgScript.SEM_CONFIGURAR)

    assert r.returncode != CodigoSaida.OK
    assert MARCA_FALHA in r.stdout
    assert not [c for c in maquina.chamadas() if ArgUv.REINSTALL in c]


@pytest.mark.parametrize("sufixo_repo", ["", ".git"])
@pytest.mark.parametrize(
    ("sonda", "atualizar"),
    [
        (CodigoSaida.USO, CodigoSaida.OK),
        (CodigoSaida.OK, CodigoSaida.ORIGEM_RECUSADA),
    ],
)
def test_sonda_2_ou_3_reinstala_e_lista_plugins(maquina, sonda, atualizar, sufixo_repo):
    jira = f"git+{URL_REPO}{sufixo_repo}@{VERSAO_ANTIGA}{SUBPASTA_JIRA}"
    pasta = maquina.raiz / NOME_PLUGIN_LOCAL
    linha = (
        f"{PACOTE_MOTOR} {VERSAO_ANTIGA} {EXTRAS_UV} "
        f"[with: {NOME_PLUGIN_GIT} {PLUGIN_GIT}, {NOME_PLUGIN_LOCAL}file://{pasta}, "
        f"{NOME_PLUGIN_JIRA} {jira}]"
    )
    maquina.env |= {
        Var.SAIDA_SONDA: str(sonda),
        Var.SAIDA_ATUALIZAR: str(atualizar),
        Var.LINHA_UV: linha,
    }
    maquina.instalar_motor()

    r = maquina.rodar(ArgScript.SEM_CONFIGURAR)

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    assert _instalacao(ULTIMA_TAG, reinstalar=True) in maquina.chamadas()
    assert linha in r.stdout
    instalar = f"{servico.EXECUTAVEL} {COMANDO_PLUGIN} {AcaoPlugin.INSTALAR}"
    assert f"{instalar} '{PLUGIN_GIT}'" in r.stdout
    assert f"{instalar} '{pasta}'" in r.stdout
    assert f"{instalar} 'git+{URL_REPO}{sufixo_repo}{SUBPASTA_JIRA}'" in r.stdout


@pytest.mark.parametrize("caminho", list(Caminho))
def test_servico_ligado_encerra_antes_e_sobe_depois_do_uv(maquina, caminho):
    maquina.env[Var.SAIDA_QUERY] = str(CodigoSaida.OK)
    reinstalar = caminho is Caminho.REINSTALACAO
    if reinstalar:
        maquina.env[Var.SAIDA_SONDA] = str(CodigoSaida.USO)
        maquina.instalar_motor()

    r = maquina.rodar(ArgScript.SEM_CONFIGURAR)

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    chamadas = maquina.chamadas()
    uv = chamadas.index(_instalacao(ULTIMA_TAG, reinstalar=reinstalar))
    assert chamadas.index(_schtasks(AcaoSchtasks.END)) < uv
    assert chamadas.index(_schtasks(AcaoSchtasks.RUN)) > uv


def _processo_do_ambiente(maquina: Maquina, codigo: str) -> subprocess.Popen[bytes]:
    """Um processo vivo cujo executável mora no ambiente do motor no uv."""
    ambiente = Path(maquina.env[VAR_UV_TOOL_DIR], PACOTE_MOTOR)
    venv.create(ambiente)
    return subprocess.Popen([str(ambiente / PYTHON_DO_VENV), ARG_PYTHON_CODIGO, codigo])


def test_espera_o_ambiente_livre_antes_do_uv(maquina):
    processo = _processo_do_ambiente(
        maquina,
        f"import time; time.sleep({ESPERA_DO_PROCESSO_S}); "
        f"open({str(maquina.log)!r}, 'a').write({MARCA_PROCESSO_FIM!r} + '\\n')",
    )
    try:
        r = maquina.rodar(ArgScript.SEM_CONFIGURAR)
    finally:
        processo.wait()

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    chamadas = maquina.chamadas()
    assert chamadas.index(MARCA_PROCESSO_FIM) < chamadas.index(_instalacao(ULTIMA_TAG))


def test_ambiente_ocupado_no_prazo_nao_chama_o_uv(maquina):
    maquina.env[VAR_PRAZO_PROCESSOS] = str(PRAZO_CURTO_S)
    processo = _processo_do_ambiente(
        maquina, f"import time; time.sleep({PROCESSO_LONGO_S})"
    )
    try:
        r = maquina.rodar(ArgScript.SEM_CONFIGURAR)
    finally:
        processo.kill()
        processo.wait()

    assert r.returncode != CodigoSaida.OK
    assert MARCA_FALHA in r.stdout
    assert str(processo.pid) in r.stdout
    assert _instalacao(ULTIMA_TAG) not in maquina.chamadas()


@pytest.mark.parametrize("no_path", [True, False])
def test_aviso_de_path(maquina, no_path):
    if no_path:
        maquina.env[VAR_PATH] += f"{os.pathsep}{maquina.toolbin}"

    r = maquina.rodar(ArgScript.SEM_CONFIGURAR)

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    assert (DICA_PATH in r.stdout) is not no_path


@pytest.mark.parametrize("args", [(), (ArgScript.SEM_CONFIGURAR,)])
def test_sem_console_ou_sem_configurar_nao_abre_o_configurar(maquina, args):
    r = maquina.rodar(*args)

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    assert _configurar() not in maquina.chamadas()
    assert _configurar() in r.stdout


def test_com_console_roda_o_configurar(maquina):
    # Ramo literal para o mypy; a fixture já pulou fora do Windows.
    if sys.platform != "win32":
        return
    # Um console novo, sem redirecionar nada: a entrada e a saída são o console.
    r = subprocess.run(
        maquina.comando(ArgPowershell.FILE, str(SCRIPT)),
        env=maquina.env,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        timeout=LIMITE_TESTE_S,
        check=False,
    )

    assert r.returncode == CodigoSaida.OK
    chamadas = maquina.chamadas()
    assert _configurar() in chamadas
    assert MARCA_CONSOLE in chamadas


@pytest.mark.parametrize("falha", [True, False])
def test_codificacao_restaurada(maquina, falha):
    if falha:
        maquina.sem(Falso.GIT)

    r = maquina.rodar_bloco(
        ArgScript.SEM_CONFIGURAR,
        antes=f"[Console]::OutputEncoding = [Text.Encoding]::GetEncoding({PAGINA_OEM})",
        depois="[Console]::OutputEncoding.CodePage",
    )

    assert (MARCA_FALHA in r.stdout) is falha, r.stdout + r.stderr
    # Pelo `iex`, os acentos chegam certos no 5.1 e no 7.
    assert (FRASE_SEM_GIT if falha else FRASE_ULTIMA_RELEASE) in r.stdout
    assert r.stdout.splitlines()[-1] == str(PAGINA_OEM)


def test_desinstalar_chama_o_motor_e_remove(maquina):
    maquina.instalar_motor()

    r = maquina.rodar(ArgScript.DESINSTALAR)

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    chamadas = maquina.chamadas()
    desinstalar = chamadas.index(f"{servico.EXECUTAVEL} {COMANDO_DESINSTALAR}")
    assert desinstalar < chamadas.index(
        f"{UV} {ArgUv.TOOL} {AcaoUv.UNINSTALL} {PACOTE_MOTOR}"
    )
    assert FRASE_UV_FICOU in r.stdout


def test_desinstalar_interrompido_nao_remove_nada(maquina):
    maquina.env[Var.SAIDA_DESINSTALAR] = str(CodigoSaida.INTERROMPIDO)
    maquina.instalar_motor()

    r = maquina.rodar(ArgScript.DESINSTALAR)

    assert r.returncode == CodigoSaida.INTERROMPIDO
    assert not [c for c in maquina.chamadas() if AcaoUv.UNINSTALL in c]
    assert maquina.motor.exists()


@pytest.mark.parametrize("motor_quebrado", [True, False])
def test_desinstalar_sem_motor_encerra_e_apaga_as_tarefas(
    maquina, monkeypatch, motor_quebrado
):
    if motor_quebrado:
        maquina.env[Var.SAIDA_DESINSTALAR] = str(CodigoSaida.ERRO)
        maquina.instalar_motor()
    monkeypatch.setenv(config.VAR_XDG_CONFIG_HOME, "")
    for var in (VAR_LOCALAPPDATA, VAR_APPDATA):
        monkeypatch.setenv(var, maquina.env[var])

    r = maquina.rodar(ArgScript.DESINSTALAR)

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    chamadas = maquina.chamadas()
    for tarefa in (NOME_TAREFA_SERVE, NOME_TAREFA_INSCRICOES):
        assert _schtasks(AcaoSchtasks.END, tarefa) in chamadas
        assert (
            f"{_schtasks(AcaoSchtasks.DELETE, tarefa)} {FLAG_FORCAR_SCHTASKS}"
            in chamadas
        )
    for pasta in (
        Path(config.caminho_config_global()).parent,
        Path(config.diretorio_dados()),
        Path(config.diretorio_cache()),
    ):
        assert str(pasta) in r.stdout
    assert AVISO_BANCO in r.stdout


@pytest.mark.skipif(
    sys.platform == PLATAFORMA_WINDOWS or shutil.which(PWSH) is None,
    reason="precisa do pwsh fora do Windows",
)
def test_fora_do_windows_aponta_o_install_sh():
    pwsh = shutil.which(PWSH)
    assert pwsh is not None

    r = subprocess.run(
        [pwsh, ArgPowershell.NO_PROFILE, ArgPowershell.FILE, str(SCRIPT)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        timeout=LIMITE_TESTE_S,
        check=False,
    )

    assert r.returncode != CodigoSaida.OK
    assert URL_INSTALL_SH in r.stdout


def test_arquivo_tem_bom():
    # O ajudante roda pelo `-File`: sem BOM, o 5.1 leria os acentos como ANSI.
    assert AJUDANTE.read_bytes()[: len(BOM_UTF8)] == BOM_UTF8


def test_install_ps1_sem_bom():
    # O `irm` não remove o BOM, e o parser do PowerShell não o trata como espaço.
    assert SCRIPT.read_bytes()[: len(BOM_UTF8)] != BOM_UTF8
