from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pytest

from motor import agendador, config, servico
from motor.__main__ import COMANDO_DESINSTALAR
from motor.agendador import Sistema
from motor.cli_instalacao import COMANDO_ATUALIZAR_MOTOR, COMANDO_PLUGIN, AcaoPlugin
from motor.errors import CodigoSaida
from motor.instalacao import PACOTE_MOTOR
from tests.plataforma import PLATAFORMA_WINDOWS

pytestmark = pytest.mark.skipif(
    sys.platform == PLATAFORMA_WINDOWS, reason="install.sh é sh POSIX"
)

SCRIPT = Path(__file__).resolve().parent.parent / "install.sh"
URL_REPO = "https://github.com/EduardoBllc/monitor-versoes"
URL_WINDOWS = f"{URL_REPO}#windows"
URL_INSTALADOR_UV = "https://astral.sh/uv/install.sh"
ULTIMA_TAG = "v0.10.0"
VERSAO_ANTIGA = "v0.2.0"
TAGS_REMOTAS = (VERSAO_ANTIGA, "v0.9.0", ULTIMA_TAG, "v1.0.0-rc1", "latest")
SUBPASTA_JIRA = "#subdirectory=plugins/jira"
PLUGIN_GIT = (
    "git+https://github.com/exemplo/monitor-versoes-plugin"
    "@99ffe18fdf9f7268abfaf2c611f87e4b10db50c5"
)
FLAG_SEM_CONFIGURAR = "--sem-configurar"
FLAG_DESINSTALAR = "--desinstalar"
FLAG_HELP = "--help"
MARCA_OK = "✔"
MARCA_FALHA = "✖"
MARCA_TTY = "stdin-tty"
DICA_PATH = "uv tool update-shell"
AVISO_BANCO = "DATABASE_SQLITE_PATH"
FRASE_UV_FICOU = "O uv continua instalado"
SAIDA_UV_NAO_INSTALADO = 2
UTILITARIOS = (
    "sh", "cat", "sed", "grep", "sort", "tail", "head",
    "mkdir", "rm", "id", "tr", "cp", "chmod", "basename", "dirname",
)  # fmt: skip


class Var(StrEnum):
    LOG = "FALSO_LOG"
    TAGS = "FALSO_TAGS"
    UNAME = "FALSO_UNAME"
    LINHA_UV = "FALSO_LINHA_UV"
    MOTOR = "FALSO_MOTOR"
    SAIDA_SONDA = "FALSO_SAIDA_SONDA"
    SAIDA_ATUALIZAR = "FALSO_SAIDA_ATUALIZAR"
    SAIDA_DESINSTALAR = "FALSO_SAIDA_DESINSTALAR"


class Uname(StrEnum):
    LINUX = "Linux"
    DARWIN = "Darwin"
    WINDOWS = "MINGW64_NT-10.0"


SISTEMA = {Uname.LINUX: Sistema.LINUX, Uname.DARWIN: Sistema.MACOS}


class Gerenciador(StrEnum):
    APT = "apt-get"
    DNF = "dnf"
    PACMAN = "pacman"


class Caminho(StrEnum):
    NOVA = "instalação nova"
    REINSTALACAO = "reinstalação"


_REGISTRA = f'printf \'%s\\n\' "$(basename "$0") $*" >> "${Var.LOG}"\n'

_UV = f"""#!/bin/sh
{_REGISTRA}case "$1 $2" in
  "tool dir") printf '%s\\n' "$UV_TOOL_BIN_DIR" ;;
  "tool install") cp "${Var.MOTOR}" "$UV_TOOL_BIN_DIR/" ;;
  "tool list") [ -x "$UV_TOOL_BIN_DIR/{servico.EXECUTAVEL}" ] && printf '%s\\n' "${Var.LINHA_UV}" ;;
  "tool uninstall")
    rm "$UV_TOOL_BIN_DIR/{servico.EXECUTAVEL}" 2>/dev/null || exit {SAIDA_UV_NAO_INSTALADO} ;;
esac
"""

_GIT = f"""#!/bin/sh
{_REGISTRA}for t in ${Var.TAGS}; do printf '0000\\trefs/tags/%s\\n' "$t"; done
"""

_UNAME = f"""#!/bin/sh
{_REGISTRA}printf '%s\\n' "${Var.UNAME}"
"""

_MOTOR = f"""#!/bin/sh
{_REGISTRA}case "$1" in
  {COMANDO_ATUALIZAR_MOTOR})
    [ "${{2:-}}" = {FLAG_HELP} ] && exit "${Var.SAIDA_SONDA}"
    exit "${Var.SAIDA_ATUALIZAR}" ;;
  {servico.COMANDO_CONFIGURAR}) [ -t 0 ] && echo {MARCA_TTY} >> "${Var.LOG}" ;;
  {COMANDO_DESINSTALAR}) exit "${Var.SAIDA_DESINSTALAR}" ;;
esac
exit 0
"""


def _executavel(caminho: Path, conteudo: str) -> None:
    caminho.write_text(conteudo)
    caminho.chmod(0o755)


@dataclass
class Maquina:
    raiz: Path
    home: Path
    falsos: Path
    sistema: Path
    toolbin: Path
    log: Path
    env: dict[str, str]

    def com(self, nome: str, conteudo: str = f"#!/bin/sh\n{_REGISTRA}") -> None:
        _executavel(self.falsos / nome, conteudo)

    def sem(self, nome: str) -> None:
        (self.falsos / nome).unlink()

    def instalar_motor(self) -> None:
        shutil.copy(self.env[Var.MOTOR], self.toolbin)

    @property
    def motor(self) -> Path:
        return self.toolbin / servico.EXECUTAVEL

    def chamadas(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def rodar(self, *args: str) -> subprocess.CompletedProcess[str]:
        # Sessão nova: sem terminal de controle, o /dev/tty não abre.
        return subprocess.run(
            [str(self.sistema / "sh"), str(SCRIPT), *args],
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            start_new_session=True,
            check=False,
        )


@pytest.fixture
def maquina(tmp_path: Path) -> Iterator[Maquina]:
    home, falsos, sistema, toolbin, pacotes = (
        tmp_path / nome for nome in ("home", "falsos", "sistema", "toolbin", "pacotes")
    )
    for pasta in (home, falsos, sistema, toolbin, pacotes):
        pasta.mkdir()
    for util in UTILITARIOS:
        real = shutil.which(util)
        assert real is not None, util
        (sistema / util).symlink_to(real)
    _executavel(pacotes / "uv", _UV)
    _executavel(pacotes / servico.EXECUTAVEL, _MOTOR)
    env = {
        "HOME": str(home),
        "PATH": f"{falsos}:{sistema}",
        "UV_TOOL_BIN_DIR": str(toolbin),
        Var.LOG: str(tmp_path / "log"),
        Var.TAGS: " ".join(TAGS_REMOTAS),
        Var.UNAME: Uname.LINUX,
        Var.LINHA_UV: f"{PACOTE_MOTOR} {VERSAO_ANTIGA}",
        Var.MOTOR: str(pacotes / servico.EXECUTAVEL),
        Var.SAIDA_SONDA: str(CodigoSaida.OK),
        Var.SAIDA_ATUALIZAR: str(CodigoSaida.OK),
        Var.SAIDA_DESINSTALAR: str(CodigoSaida.OK),
    }
    m = Maquina(tmp_path, home, falsos, sistema, toolbin, tmp_path / "log", env)
    m.com("uv", _UV)
    m.com("git", _GIT)
    m.com("uname", _UNAME)
    m.com("curl", f"#!/bin/sh\n{_REGISTRA}")
    for comando in (agendador.SYSTEMCTL[0], agendador.LAUNCHCTL):
        m.com(comando)
    yield m


def _instalacao(tag: str, *, reinstalar: bool = False) -> str:
    flag = " --reinstall" if reinstalar else ""
    return f"uv tool install{flag} {PACOTE_MOTOR} @ git+{URL_REPO}@{tag}"


def test_sem_uv_instala_uv_e_a_ultima_release(maquina):
    maquina.sem("uv")
    uv = maquina.raiz / "pacotes" / "uv"
    instalador = f'mkdir -p "$HOME/.local/bin" && cp {uv} "$HOME/.local/bin/uv"'
    maquina.com("curl", f"#!/bin/sh\n{_REGISTRA}echo '{instalador}'\n")

    r = maquina.rodar()

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    chamadas = maquina.chamadas()
    assert any(URL_INSTALADOR_UV in c for c in chamadas if c.startswith("curl"))
    assert _instalacao(ULTIMA_TAG) in chamadas
    assert MARCA_OK in r.stdout
    assert f"{servico.EXECUTAVEL} {servico.COMANDO_CONFIGURAR}" in r.stdout


@pytest.mark.parametrize(
    ("uname", "gerenciador", "comando"),
    [
        (Uname.LINUX, Gerenciador.APT, "sudo apt install git"),
        (Uname.LINUX, Gerenciador.DNF, "sudo dnf install git"),
        (Uname.LINUX, Gerenciador.PACMAN, "sudo pacman -S git"),
        (Uname.DARWIN, None, "xcode-select --install"),
    ],
)
def test_sem_git_para_antes_de_instalar(maquina, uname, gerenciador, comando):
    maquina.sem("git")
    maquina.env[Var.UNAME] = uname
    if gerenciador is not None:
        maquina.com(gerenciador)

    r = maquina.rodar()

    assert r.returncode != CodigoSaida.OK
    assert comando in r.stdout
    assert not [c for c in maquina.chamadas() if c.startswith(("uv ", "curl "))]


def test_sistema_nao_suportado_aponta_o_windows(maquina):
    maquina.env[Var.UNAME] = Uname.WINDOWS

    r = maquina.rodar()

    assert r.returncode != CodigoSaida.OK
    assert URL_WINDOWS in r.stdout
    assert not [c for c in maquina.chamadas() if c.startswith(("uv ", "curl "))]


def test_ja_instalado_roda_atualizar_motor(maquina):
    maquina.instalar_motor()

    r = maquina.rodar(FLAG_SEM_CONFIGURAR)

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    assert f"{servico.EXECUTAVEL} {COMANDO_ATUALIZAR_MOTOR}" in maquina.chamadas()
    assert not [c for c in maquina.chamadas() if c.startswith("uv tool install")]


@pytest.mark.parametrize("sufixo_repo", ["", ".git"])
@pytest.mark.parametrize(
    ("sonda", "atualizar"),
    [
        (CodigoSaida.USO, CodigoSaida.OK),
        (CodigoSaida.OK, CodigoSaida.ORIGEM_RECUSADA),
    ],
)
def test_instalacao_que_o_atualizar_motor_nao_atende_reinstala_e_lista_plugins(
    maquina, sonda, atualizar, sufixo_repo
):
    jira = f"git+{URL_REPO}{sufixo_repo}@{VERSAO_ANTIGA}{SUBPASTA_JIRA}"
    pasta = maquina.raiz / "plugum"
    linha = (
        f"{PACOTE_MOTOR} {VERSAO_ANTIGA} [extras: anthropic] "
        f"[with: monitor-versoes-plugin {PLUGIN_GIT}, plugumfile://{pasta}, "
        f"monitor-versoes-jira {jira}]"
    )
    maquina.env |= {
        Var.SAIDA_SONDA: str(sonda),
        Var.SAIDA_ATUALIZAR: str(atualizar),
        Var.LINHA_UV: linha,
    }
    maquina.instalar_motor()

    r = maquina.rodar(FLAG_SEM_CONFIGURAR)

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    assert _instalacao(ULTIMA_TAG, reinstalar=True) in maquina.chamadas()
    assert linha in r.stdout
    instalar = f"{servico.EXECUTAVEL} {COMANDO_PLUGIN} {AcaoPlugin.INSTALAR}"
    assert f"{instalar} '{PLUGIN_GIT}'" in r.stdout
    assert f"{instalar} '{pasta}'" in r.stdout
    assert f"{instalar} 'git+{URL_REPO}{sufixo_repo}{SUBPASTA_JIRA}'" in r.stdout


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

    r = maquina.rodar(FLAG_SEM_CONFIGURAR)

    assert r.returncode != CodigoSaida.OK
    assert MARCA_FALHA in r.stdout
    assert not [c for c in maquina.chamadas() if "--reinstall" in c]


FLAG_KICKSTART_FORCAR = "-k"
ACAO_TRY_RESTART = "try-restart"
VAR_CARREGADOS = "FALSO_CARREGADOS"
# `launchctl print` só acha o que está carregado, e carregado com KeepAlive é rodando.
_LAUNCHCTL = f"""#!/bin/sh
{_REGISTRA}[ "$1" = {agendador.Acao.PRINT} ] || exit 0
for rotulo in ${VAR_CARREGADOS}; do
  [ "$2" = "gui/$(id -u)/$rotulo" ] && exit 0
done
exit 1
"""


def _arquivos_do_servico(sistema: Sistema, home: Path) -> list[Path]:
    if sistema is Sistema.MACOS:
        agentes = home / "Library" / "LaunchAgents"
        return [
            servico.caminho(sistema, home),
            agentes / f"{servico.ROTULO_LOGIN}.plist",
            agentes / f"{servico.ROTULO_LEGADO}.plist",
        ]
    return [servico.caminho(sistema, home)]


def _rodar_no_caminho(maquina: Maquina, caminho: Caminho) -> None:
    if caminho is Caminho.REINSTALACAO:
        maquina.env[Var.SAIDA_SONDA] = str(CodigoSaida.USO)
        maquina.instalar_motor()
    r = maquina.rodar(FLAG_SEM_CONFIGURAR)
    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr


@pytest.mark.parametrize("com_unit", [True, False])
@pytest.mark.parametrize("caminho", list(Caminho))
def test_linux_reinicia_so_o_daemon_rodando_depois_de_instalar(
    maquina, caminho, com_unit
):
    if com_unit:
        unit = servico.caminho(Sistema.LINUX, maquina.home)
        unit.parent.mkdir(parents=True)
        unit.touch()

    _rodar_no_caminho(maquina, caminho)

    reinicio = (
        f"{' '.join(agendador.SYSTEMCTL)} {ACAO_TRY_RESTART} {servico.ARQUIVO_SERVICE}"
    )
    assert (reinicio in maquina.chamadas()) is com_unit


@pytest.mark.parametrize(
    "carregados",
    [(servico.ROTULO_PROCESSO,), (servico.ROTULO_LEGADO,), ()],
    ids=["daemon", "servico-antigo", "parado"],
)
@pytest.mark.parametrize("caminho", list(Caminho))
def test_macos_reinicia_so_o_daemon_rodando_depois_de_instalar(
    maquina, caminho, carregados
):
    maquina.env[Var.UNAME] = Uname.DARWIN
    maquina.env[VAR_CARREGADOS] = " ".join(carregados)
    maquina.com(agendador.LAUNCHCTL, _LAUNCHCTL)

    _rodar_no_caminho(maquina, caminho)

    prefixo = f"{agendador.LAUNCHCTL} {agendador.Acao.KICKSTART} {FLAG_KICKSTART_FORCAR} gui/{os.getuid()}/"
    reiniciados = [
        c.removeprefix(prefixo) for c in maquina.chamadas() if c.startswith(prefixo)
    ]
    assert reiniciados == list(carregados)


@pytest.mark.parametrize("no_path", [True, False])
def test_aviso_de_path(maquina, no_path):
    if no_path:
        maquina.env["PATH"] += f":{maquina.toolbin}"

    r = maquina.rodar(FLAG_SEM_CONFIGURAR)

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    assert (DICA_PATH in r.stdout) is not no_path


@pytest.mark.parametrize("args", [(), (FLAG_SEM_CONFIGURAR,)])
def test_sem_terminal_ou_sem_configurar_nao_abre_o_configurar(maquina, args):
    r = maquina.rodar(*args)

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    configurar = f"{servico.EXECUTAVEL} {servico.COMANDO_CONFIGURAR}"
    assert configurar not in maquina.chamadas()
    assert configurar in r.stdout


def test_com_terminal_roda_o_configurar_no_tty(maquina):
    import pty

    sh = str(maquina.sistema / "sh")
    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - filho, com o pty como terminal de controle
        os.execve(sh, [sh, str(SCRIPT)], maquina.env)
    saida = b""
    while True:
        try:
            pedaco = os.read(fd, 4096)
        except OSError:
            break
        if not pedaco:
            break
        saida += pedaco
    _, status = os.waitpid(pid, 0)

    assert os.waitstatus_to_exitcode(status) == CodigoSaida.OK, saida.decode()
    chamadas = maquina.chamadas()
    assert f"{servico.EXECUTAVEL} {servico.COMANDO_CONFIGURAR}" in chamadas
    assert MARCA_TTY in chamadas


def test_desinstalar_pelo_motor(maquina):
    maquina.instalar_motor()

    r = maquina.rodar(FLAG_DESINSTALAR)

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    chamadas = maquina.chamadas()
    desinstalar = chamadas.index(f"{servico.EXECUTAVEL} {COMANDO_DESINSTALAR}")
    assert desinstalar < chamadas.index(f"uv tool uninstall {PACOTE_MOTOR}")
    assert FRASE_UV_FICOU in r.stdout


def test_desinstalar_interrompido_nao_remove_nada(maquina):
    maquina.env[Var.SAIDA_DESINSTALAR] = str(CodigoSaida.INTERROMPIDO)
    maquina.instalar_motor()

    r = maquina.rodar(FLAG_DESINSTALAR)

    assert r.returncode == CodigoSaida.INTERROMPIDO
    assert not [c for c in maquina.chamadas() if c.startswith("uv tool uninstall")]
    assert maquina.motor.exists()


@pytest.mark.parametrize("motor_quebrado", [True, False])
@pytest.mark.parametrize("uname", list(SISTEMA))
def test_desinstalar_sem_motor_remove_servicos_e_mantem_dados(
    maquina, monkeypatch, uname, motor_quebrado
):
    sistema = SISTEMA[uname]
    maquina.env[Var.UNAME] = uname
    if motor_quebrado:
        maquina.env[Var.SAIDA_DESINSTALAR] = str(CodigoSaida.ERRO)
        maquina.instalar_motor()
    monkeypatch.setenv("HOME", str(maquina.home))
    arquivos = [
        *_arquivos_do_servico(sistema, maquina.home),
        *agendador.caminhos(sistema, maquina.home),
    ]
    for arquivo in arquivos:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.touch()
    for var in (config.VAR_XDG_CONFIG_HOME, config.VAR_XDG_CACHE_HOME):
        monkeypatch.setenv(var, "")
    dados = [
        Path(config.caminho_config_global()).parent,
        Path(config.diretorio_dados()),
        Path(config.diretorio_cache()),
    ]
    for pasta in dados:
        pasta.mkdir(parents=True, exist_ok=True)

    r = maquina.rodar(FLAG_DESINSTALAR)

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    assert not [a for a in arquivos if a.exists()]
    desativar = (
        f"{agendador.LAUNCHCTL} {agendador.Acao.UNLOAD}"
        if sistema is Sistema.MACOS
        else f"{' '.join(agendador.SYSTEMCTL)} {agendador.Acao.DISABLE} {agendador.FLAG_AGORA}"
    )
    assert any(c.startswith(desativar) for c in maquina.chamadas())
    assert all(pasta.is_dir() for pasta in dados)
    for pasta in dados:
        assert str(pasta) in r.stdout
    assert AVISO_BANCO in r.stdout


def test_desinstalar_sem_uv_nao_diz_que_o_uv_ficou(maquina):
    maquina.sem("uv")

    r = maquina.rodar(FLAG_DESINSTALAR)

    assert r.returncode == CodigoSaida.OK, r.stdout + r.stderr
    assert FRASE_UV_FICOU not in r.stdout
