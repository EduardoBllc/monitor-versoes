from __future__ import annotations

import os
import plistlib
import re
import socket
import sys
import sysconfig
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from motor import servico
from motor.__main__ import COMANDO_SERVE, main
from motor.agendador import (
    FLAG_ATIVAR_SCHTASKS,
    FLAG_DESATIVAR_SCHTASKS,
    FLAG_FORCAR_SCHTASKS,
    FLAG_TAREFA,
    FLAG_XML,
    LAUNCHCTL,
    SCHTASKS,
    SYSTEMCTL,
    Acao,
    AcaoSchtasks,
    Sistema,
)
from motor.config import diretorio_dados
from motor.errors import BackendIndisponivel, ErroDeEntrada
from motor.servico import (
    ARGUMENTOS_LEGADOS,
    ARGUMENTOS_SERVE,
    ARQUIVO_LOG_LAUNCHD,
    ARQUIVO_LOG_SERVE,
    ARQUIVO_SERVICE,
    EXECUTAVEL_SERVE,
    FLAG_PERSISTIR,
    NOME_TAREFA_LOGIN,
    NOME_TAREFA_PROCESSO,
    NOME_TAREFA_SERVE,
    ROTULO_LEGADO,
    ROTULO_LOGIN,
    ROTULO_PROCESSO,
    EstadoServico,
    Situacao,
    apos_reinstalar,
    caminho,
    desligar_login,
    executavel_motor,
    executavel_servico,
    ligar_login,
    login_ligado,
    migrar_legado,
    parar,
    regravar,
    remover,
    rodando,
    situacao,
    subir,
)
from tests.plataforma import PLATAFORMA_WINDOWS
from tests.test_agendador import MOTIVO_FALHA, Registro

EXE = "/opt/venv/bin/monitor-versoes"
ARGUMENTOS_INICIAR_LOGIN = ["daemon", "iniciar", "--sem-perguntas"]
ARGUMENTOS_PARAR_LOGIN = ["daemon", "parar", "--sem-perguntas"]
ATIVO_LINUX = "active\n"
INATIVO_LINUX = "inactive\n"
HABILITADO_LINUX = "enabled\n"
DESABILITADO_LINUX = "disabled\n"
ATIVO_MACOS = "\tstate = running\n"
INATIVO_MACOS = "\tstate = waiting\n"
VER_LOG_LINUX = f"journalctl --user -u {ARQUIVO_SERVICE}"
VER_LOG_MACOS = f"tail -f ~/Library/Logs/{ARQUIVO_LOG_LAUNCHD}"
FLAG_PORTA = "--porta"
FLAG_SEM_NAVEGADOR = ARGUMENTOS_SERVE[-1]


def _nunca_pergunta() -> bool:
    raise AssertionError("o serviço já responde por si; não se sonda a porta")


pula_mac_no_windows = pytest.mark.skipif(
    sys.platform == PLATAFORMA_WINDOWS, reason="launchctl usa o uid do POSIX"
)
SISTEMAS = [
    pytest.param(Sistema.LINUX, id="linux"),
    pytest.param(Sistema.MACOS, id="macos", marks=pula_mac_no_windows),
]


def _como(sistema: Sistema, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(servico, "sistema_atual", lambda: sistema)


def _sem_suporte() -> Sistema:
    raise ErroDeEntrada("agendador automático não suportado")


def _respondendo(
    respostas: dict[tuple[str, ...], str],
) -> Callable[[list[str]], str | None]:
    return lambda cmd: respostas.get(tuple(cmd))


def _alvo_mac(rotulo: str) -> str:
    return f"gui/{os.getuid()}/{rotulo}"


def _agente(home: Path, rotulo: str) -> Path:
    return home / "Library" / "LaunchAgents" / f"{rotulo}.plist"


def _cmd_ativo(sistema: Sistema) -> tuple[str, ...]:
    if sistema is Sistema.LINUX:
        return (*SYSTEMCTL, Acao.IS_ACTIVE, ARQUIVO_SERVICE)
    return (LAUNCHCTL, Acao.PRINT, _alvo_mac(ROTULO_PROCESSO))


def _comandos_de_subir(sistema: Sistema, home: Path) -> list[list[str]]:
    if sistema is Sistema.LINUX:
        return [
            [*SYSTEMCTL, Acao.DAEMON_RELOAD],
            [*SYSTEMCTL, Acao.RESTART, ARQUIVO_SERVICE],
        ]
    arquivo = str(caminho(sistema, home))
    return [[LAUNCHCTL, Acao.UNLOAD, arquivo], [LAUNCHCTL, Acao.LOAD, arquivo]]


@pytest.mark.parametrize("sistema", SISTEMAS)
def test_subir_grava_e_sobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sistema: Sistema
) -> None:
    _como(sistema, monkeypatch)
    registro = Registro()
    subir(sistema, tmp_path, EXE, registro)

    arquivo = caminho(sistema, tmp_path)
    assert registro.comandos == _comandos_de_subir(sistema, tmp_path)
    if sistema is Sistema.LINUX:
        texto = arquivo.read_text()
        assert f'ExecStart="{EXE}" {" ".join(ARGUMENTOS_SERVE)}' in texto
        assert "Restart=on-failure" in texto
    else:
        assert arquivo.parent == Path(diretorio_dados())
        dados = plistlib.loads(arquivo.read_bytes())
        log = str(tmp_path / "Library" / "Logs" / ARQUIVO_LOG_LAUNCHD)
        assert dados["Label"] == ROTULO_PROCESSO
        assert dados["ProgramArguments"] == [EXE, *ARGUMENTOS_SERVE]
        assert dados["RunAtLoad"] is True
        assert dados["KeepAlive"] is True
        assert dados["StandardOutPath"] == log
        assert dados["StandardErrorPath"] == log


@pula_mac_no_windows
def test_subir_no_macos_com_o_job_ja_carregado_recarrega(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _como(Sistema.MACOS, monkeypatch)
    registro = Registro(falhar_em=Acao.UNLOAD)
    subir(Sistema.MACOS, tmp_path, EXE, registro)
    assert registro.comandos[-1][1] == Acao.LOAD


@pytest.mark.parametrize("sistema", SISTEMAS)
def test_parar_so_para(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sistema: Sistema
) -> None:
    _como(sistema, monkeypatch)
    subir(sistema, tmp_path, EXE, Registro())
    registro = Registro()
    parar(sistema, tmp_path, registro)

    arquivo = caminho(sistema, tmp_path)
    esperado = (
        [*SYSTEMCTL, Acao.STOP, ARQUIVO_SERVICE]
        if sistema is Sistema.LINUX
        else [LAUNCHCTL, Acao.UNLOAD, str(arquivo)]
    )
    assert registro.comandos == [esperado]
    assert arquivo.exists()


class _Systemd(Registro):
    """Lembra o `enable`/`disable` e responde ao `is-enabled` como o systemd."""

    def __init__(self) -> None:
        super().__init__()
        self.habilitado = False

    def __call__(self, cmd: list[str]) -> None:
        super().__call__(cmd)
        if cmd[len(SYSTEMCTL)] in {Acao.ENABLE, Acao.DISABLE}:
            self.habilitado = cmd[len(SYSTEMCTL)] == Acao.ENABLE

    def consultar(self, cmd: list[str]) -> str | None:
        if cmd != [*SYSTEMCTL, Acao.IS_ENABLED, ARQUIVO_SERVICE]:
            return None
        return HABILITADO_LINUX if self.habilitado else DESABILITADO_LINUX


@pytest.mark.parametrize("sistema", SISTEMAS)
def test_login_liga_e_desliga(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sistema: Sistema
) -> None:
    _como(sistema, monkeypatch)
    sistema_falso = _Systemd()
    assert not login_ligado(sistema, tmp_path, sistema_falso.consultar)

    ligar_login(sistema, tmp_path, EXE, sistema_falso)
    assert login_ligado(sistema, tmp_path, sistema_falso.consultar)
    login = _agente(tmp_path, ROTULO_LOGIN)
    if sistema is Sistema.LINUX:
        assert caminho(sistema, tmp_path).exists()
        assert sistema_falso.comandos == [
            [*SYSTEMCTL, Acao.DAEMON_RELOAD],
            [*SYSTEMCTL, Acao.ENABLE, ARQUIVO_SERVICE],
        ]
    else:
        dados = plistlib.loads(login.read_bytes())
        assert dados["Label"] == ROTULO_LOGIN
        assert dados["ProgramArguments"] == [EXE, *ARGUMENTOS_INICIAR_LOGIN]
        assert dados["RunAtLoad"] is True
        assert "KeepAlive" not in dados
        assert not sistema_falso.comandos

    sistema_falso.comandos.clear()
    desligar_login(sistema, tmp_path, sistema_falso)
    assert not login_ligado(sistema, tmp_path, sistema_falso.consultar)
    esperado = (
        [*SYSTEMCTL, Acao.DISABLE, ARQUIVO_SERVICE]
        if sistema is Sistema.LINUX
        else [LAUNCHCTL, Acao.UNLOAD, str(login)]
    )
    assert sistema_falso.comandos == [esperado]


@pytest.mark.parametrize(
    ("sistema", "saida", "esperado"),
    [
        (Sistema.LINUX, ATIVO_LINUX, True),
        (Sistema.LINUX, INATIVO_LINUX, False),
        (Sistema.LINUX, None, False),
        pytest.param(Sistema.MACOS, ATIVO_MACOS, True, marks=pula_mac_no_windows),
        pytest.param(Sistema.MACOS, INATIVO_MACOS, False, marks=pula_mac_no_windows),
        pytest.param(Sistema.MACOS, None, False, marks=pula_mac_no_windows),
    ],
)
def test_rodando(
    tmp_path: Path, sistema: Sistema, saida: str | None, esperado: bool
) -> None:
    respostas = {} if saida is None else {_cmd_ativo(sistema): saida}
    assert rodando(sistema, tmp_path, _respondendo(respostas)) is esperado


def test_migrar_legado_linux_regrava_unit_antiga(tmp_path: Path) -> None:
    arquivo = caminho(Sistema.LINUX, tmp_path)
    arquivo.parent.mkdir(parents=True)
    arquivo.write_text(f'[Service]\nExecStart="{EXE}" {" ".join(ARGUMENTOS_LEGADOS)}\n')
    registro = Registro()

    assert migrar_legado(Sistema.LINUX, tmp_path, EXE, registro, _respondendo({}))
    assert f'ExecStart="{EXE}" {" ".join(ARGUMENTOS_SERVE)}' in arquivo.read_text()
    assert registro.comandos == [[*SYSTEMCTL, Acao.DAEMON_RELOAD]]

    assert not migrar_legado(Sistema.LINUX, tmp_path, EXE, registro, _respondendo({}))
    assert len(registro.comandos) == 1


def test_migrar_legado_linux_sem_unit_nao_age(tmp_path: Path) -> None:
    registro = Registro()
    assert not migrar_legado(Sistema.LINUX, tmp_path, EXE, registro, _respondendo({}))
    assert not registro.comandos
    assert not caminho(Sistema.LINUX, tmp_path).exists()


@pula_mac_no_windows
def test_migrar_legado_macos_troca_plist_antigo_por_processo_e_login(
    tmp_path: Path,
) -> None:
    legado = _agente(tmp_path, ROTULO_LEGADO)
    legado.parent.mkdir(parents=True)
    legado.touch()
    registro = Registro()

    assert migrar_legado(Sistema.MACOS, tmp_path, EXE, registro, _respondendo({}))
    assert not legado.exists()
    assert _agente(tmp_path, ROTULO_LOGIN).exists()
    assert registro.comandos == [
        [LAUNCHCTL, Acao.UNLOAD, FLAG_PERSISTIR, str(legado)],
        *_comandos_de_subir(Sistema.MACOS, tmp_path),
    ]

    assert not migrar_legado(Sistema.MACOS, tmp_path, EXE, Registro(), _respondendo({}))


@pytest.mark.parametrize("ligado", [True, False])
@pytest.mark.parametrize("sistema", SISTEMAS)
def test_apos_reinstalar_reinicia_so_se_rodando(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sistema: Sistema, ligado: bool
) -> None:
    _como(sistema, monkeypatch)
    regravar(sistema, tmp_path, executavel_servico(), Registro())
    saida = ATIVO_LINUX if sistema is Sistema.LINUX else ATIVO_MACOS
    respostas = {_cmd_ativo(sistema): saida} if ligado else {}
    registro = Registro()

    assert apos_reinstalar(tmp_path, registro, _respondendo(respostas)) is ligado
    assert caminho(sistema, tmp_path).exists()
    if ligado:
        assert registro.comandos == _comandos_de_subir(sistema, tmp_path)
    else:
        so_regravou = (
            [[*SYSTEMCTL, Acao.DAEMON_RELOAD]] if sistema is Sistema.LINUX else []
        )
        assert registro.comandos == so_regravou


@pytest.mark.parametrize("sistema", [Sistema.WINDOWS, None])
def test_apos_reinstalar_sem_suporte_ou_no_windows_nao_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sistema: Sistema | None
) -> None:
    if sistema is None:
        monkeypatch.setattr(servico, "sistema_atual", _sem_suporte)
    else:
        _como(sistema, monkeypatch)
    registro = Registro()
    assert not apos_reinstalar(tmp_path, registro, _respondendo({}))
    assert not registro.comandos


@pytest.mark.parametrize(
    ("sistema", "acao"),
    [
        (Sistema.LINUX, Acao.STOP),
        (Sistema.LINUX, Acao.DISABLE),
        (Sistema.LINUX, Acao.DAEMON_RELOAD),
        pytest.param(Sistema.MACOS, Acao.UNLOAD, marks=pula_mac_no_windows),
    ],
)
def test_remover_apaga_tudo_mesmo_se_o_sistema_falha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sistema: Sistema, acao: Acao
) -> None:
    _como(sistema, monkeypatch)
    ligar_login(sistema, tmp_path, EXE, Registro())
    subir(sistema, tmp_path, EXE, Registro())
    arquivos = [caminho(sistema, tmp_path)]
    if sistema is Sistema.MACOS:
        arquivos += [_agente(tmp_path, ROTULO_LOGIN), _agente(tmp_path, ROTULO_LEGADO)]
        arquivos[-1].touch()

    remover(sistema, tmp_path, Registro(falhar_em=acao))

    assert not [a for a in arquivos if a.exists()]


@pytest.mark.parametrize(
    ("sistema", "ativo", "login", "responde", "esperado"),
    [
        (
            Sistema.LINUX,
            True,
            True,
            _nunca_pergunta,
            Situacao(EstadoServico.ATIVO, login=True),
        ),
        (
            Sistema.LINUX,
            False,
            False,
            lambda: False,
            Situacao(EstadoServico.PARADO, ver_log=VER_LOG_LINUX),
        ),
        (
            Sistema.LINUX,
            False,
            True,
            lambda: True,
            Situacao(EstadoServico.NO_TERMINAL, login=True),
        ),
        pytest.param(
            Sistema.MACOS,
            True,
            False,
            _nunca_pergunta,
            Situacao(EstadoServico.ATIVO),
            marks=pula_mac_no_windows,
        ),
        pytest.param(
            Sistema.MACOS,
            False,
            True,
            lambda: False,
            Situacao(EstadoServico.PARADO, login=True, ver_log=VER_LOG_MACOS),
            marks=pula_mac_no_windows,
        ),
    ],
)
def test_situacao(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sistema: Sistema,
    ativo: bool,
    login: bool,
    responde: Callable[[], bool],
    esperado: Situacao,
) -> None:
    _como(sistema, monkeypatch)
    if sistema is Sistema.LINUX:
        respostas = {
            _cmd_ativo(sistema): ATIVO_LINUX if ativo else INATIVO_LINUX,
            (*SYSTEMCTL, Acao.IS_ENABLED, ARQUIVO_SERVICE): (
                HABILITADO_LINUX if login else DESABILITADO_LINUX
            ),
        }
    else:
        respostas = {_cmd_ativo(sistema): ATIVO_MACOS if ativo else INATIVO_MACOS}
        if login:
            ligar_login(sistema, tmp_path, EXE, Registro())
    assert situacao(tmp_path, _respondendo(respostas), responde) == esperado


def test_situacao_sem_suporte(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(servico, "sistema_atual", _sem_suporte)
    assert situacao(tmp_path, _respondendo({}), _nunca_pergunta) == Situacao(
        EstadoServico.SEM_SUPORTE
    )


def test_executavel_motor_nao_depende_do_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")
    exe = Path(executavel_motor())
    assert exe.is_absolute()
    assert exe.stem == servico.EXECUTAVEL


@pytest.mark.parametrize("sem_navegador", [False, True])
def test_serve_sem_navegador_nao_abre(
    monkeypatch: pytest.MonkeyPatch, sem_navegador: bool
) -> None:
    import threading

    import uvicorn

    import motor.__main__ as cli
    import motor.daemon.app as daemon_app

    with socket.socket() as livre:
        livre.bind(("127.0.0.1", 0))
        porta = livre.getsockname()[1]
    abertos: list[str] = []

    def timer(_atraso, funcao, args):
        return SimpleNamespace(start=lambda: funcao(*args))

    monkeypatch.setattr(cli, "checar_backend", lambda: None)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(threading, "Timer", timer)
    monkeypatch.setattr(daemon_app, "_abrir_navegador", abertos.append)

    main(
        [COMANDO_SERVE, FLAG_PORTA, str(porta), *([FLAG_SEM_NAVEGADOR] * sem_navegador)]
    )

    assert bool(abertos) is not sem_navegador


EXE_WINDOWS = r"C:\venv\Scripts\monitor-versoes-serve.exe"
SUFIXO_EXE = ".exe"
VAR_CONFIG_EXE = "EXE"
NS = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
USUARIO = ("DOMINIO", "fulano")
PADRAO_INICIO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d"
XPATH_USUARIO = "Triggers/LogonTrigger/UserId"
XPATH_INICIO = "Triggers/TimeTrigger/StartBoundary"
XPATH_ARGUMENTOS = "Actions/Exec/Arguments"
XPATH_INTERVALO = "Triggers/TimeTrigger/Repetition/Interval"
INTERVALO_REPETICAO = "PT1M"
LOGON_INTERATIVO = "InteractiveToken"
NIVEL_MINIMO = "LeastPrivilege"
POLITICA_IGNORAR = "IgnoreNew"
SEM_LIMITE = "PT0S"
FALSO = "false"
XML_ESPERADO = {
    "Principals/Principal/LogonType": LOGON_INTERATIVO,
    "Principals/Principal/RunLevel": NIVEL_MINIMO,
    "Settings/MultipleInstancesPolicy": POLITICA_IGNORAR,
    "Settings/DisallowStartIfOnBatteries": FALSO,
    "Settings/StopIfGoingOnBatteries": FALSO,
    "Settings/ExecutionTimeLimit": SEM_LIMITE,
    "Actions/Exec/Command": EXE_WINDOWS,
}
XML_CONSULTA = (
    '<?xml version="1.0" encoding="UTF-16"?>\n<Task>\n  <Triggers><TimeTrigger>'
    "<Enabled>true</Enabled></TimeTrigger></Triggers>\n"
    "  <Settings>\n    {}\n  </Settings>\n</Task>\n"
)
SETTINGS = "<Settings>"
ENABLED_FALSO = "<Enabled>false</Enabled>"
XML_ATIVADA = XML_CONSULTA.format("<Enabled>true</Enabled>")
XML_DESATIVADA = XML_CONSULTA.format(ENABLED_FALSO)


def _schtasks(tarefa: str, acao: AcaoSchtasks, *resto: str) -> list[str]:
    return [SCHTASKS, acao, FLAG_TAREFA, tarefa, *resto]


class _Agendador(Registro):
    """Lembra as tarefas criadas, ativadas e apagadas, com o XML de cada `/create`."""

    def __init__(self, falhar_em: str | None = None) -> None:
        super().__init__(falhar_em)
        self.ativadas: dict[str, bool] = {}
        self.xmls: dict[str, str] = {}

    def __call__(self, cmd: list[str]) -> None:
        tarefa, acao = cmd[3], cmd[1]
        if acao == AcaoSchtasks.CREATE:
            self.xmls[tarefa] = Path(cmd[cmd.index(FLAG_XML) + 1]).read_text("utf-16")
        super().__call__(cmd)
        if acao == AcaoSchtasks.QUERY and tarefa not in self.ativadas:
            raise BackendIndisponivel(MOTIVO_FALHA)
        if acao == AcaoSchtasks.CREATE:
            self.ativadas[tarefa] = True
        elif acao == AcaoSchtasks.CHANGE:
            self.ativadas[tarefa] = FLAG_ATIVAR_SCHTASKS in cmd
        elif acao == AcaoSchtasks.DELETE:
            self.ativadas.pop(tarefa, None)

    def consultar(self, cmd: list[str]) -> str | None:
        tarefa = cmd[3]
        if tarefa not in self.ativadas:
            return None
        if FLAG_XML not in cmd:
            return ""
        xml = self.xmls.get(tarefa, "")
        if self.ativadas[tarefa]:
            return xml
        return xml.replace(SETTINGS, f"{SETTINGS}{ENABLED_FALSO}")

    def raiz(self, tarefa: str) -> ET.Element:
        return ET.fromstring(self.xmls[tarefa].split("?>", 1)[1])

    def da(self, tarefa: str) -> list[list[str]]:
        return [cmd for cmd in self.comandos if cmd[3] == tarefa]


def _texto(raiz: ET.Element, caminho: str) -> str | None:
    return raiz.findtext("/".join(NS + p for p in caminho.split("/")))


def _argumentos_do_login(agendador: _Agendador) -> list[str]:
    return (_texto(agendador.raiz(NOME_TAREFA_LOGIN), XPATH_ARGUMENTOS) or "").split()


def test_subir_windows_cria_a_tarefa_sem_logon_e_roda(tmp_path: Path) -> None:
    agendador = _Agendador()

    subir(Sistema.WINDOWS, tmp_path, EXE_WINDOWS, agendador)

    cmd_criar = agendador.da(NOME_TAREFA_PROCESSO)[1]
    arquivo = cmd_criar[cmd_criar.index(FLAG_XML) + 1]
    assert agendador.da(NOME_TAREFA_PROCESSO) == [
        _schtasks(NOME_TAREFA_PROCESSO, AcaoSchtasks.END),
        _schtasks(
            NOME_TAREFA_PROCESSO,
            AcaoSchtasks.CREATE,
            FLAG_XML,
            arquivo,
            FLAG_FORCAR_SCHTASKS,
        ),
        _schtasks(NOME_TAREFA_PROCESSO, AcaoSchtasks.CHANGE, FLAG_ATIVAR_SCHTASKS),
        _schtasks(NOME_TAREFA_PROCESSO, AcaoSchtasks.RUN),
    ]
    raiz = agendador.raiz(NOME_TAREFA_PROCESSO)
    assert raiz.find(f"{NS}Triggers/{NS}LogonTrigger") is None
    assert re.fullmatch(PADRAO_INICIO, _texto(raiz, XPATH_INICIO) or "")
    assert _texto(raiz, XPATH_INTERVALO) == INTERVALO_REPETICAO
    assert raiz.find(f".//{NS}Repetition/{NS}Duration") is None
    assert _texto(raiz, XPATH_ARGUMENTOS) is None
    for xpath, esperado in XML_ESPERADO.items():
        assert _texto(raiz, xpath) == esperado, xpath
    assert not Path(arquivo).exists()


def test_subir_windows_sem_login_cria_o_logon_que_para(tmp_path: Path) -> None:
    agendador = _Agendador()

    subir(Sistema.WINDOWS, tmp_path, EXE_WINDOWS, agendador)

    assert _argumentos_do_login(agendador) == ARGUMENTOS_PARAR_LOGIN
    assert not login_ligado(Sistema.WINDOWS, tmp_path, agendador.consultar)


def test_subir_windows_mantem_o_login_ligado(tmp_path: Path) -> None:
    agendador = _Agendador()
    ligar_login(Sistema.WINDOWS, tmp_path, EXE_WINDOWS, agendador)

    subir(Sistema.WINDOWS, tmp_path, EXE_WINDOWS, agendador)

    assert [cmd[1] for cmd in agendador.da(NOME_TAREFA_LOGIN)] == [
        AcaoSchtasks.CREATE,
        AcaoSchtasks.QUERY,
    ]
    assert login_ligado(Sistema.WINDOWS, tmp_path, agendador.consultar)


def test_subir_windows_com_o_daemon_parado_cria_e_roda(tmp_path: Path) -> None:
    registro = Registro(falhar_em=AcaoSchtasks.END)
    subir(Sistema.WINDOWS, tmp_path, EXE_WINDOWS, registro)
    assert registro.comandos[-1] == _schtasks(NOME_TAREFA_PROCESSO, AcaoSchtasks.RUN)


def test_subir_windows_que_falha_apaga_a_tarefa(tmp_path: Path) -> None:
    registro = Registro(falhar_em=AcaoSchtasks.RUN)
    with pytest.raises(BackendIndisponivel):
        subir(Sistema.WINDOWS, tmp_path, EXE_WINDOWS, registro)
    assert registro.comandos[-1] == _schtasks(
        NOME_TAREFA_PROCESSO, AcaoSchtasks.DELETE, FLAG_FORCAR_SCHTASKS
    )


@pytest.mark.parametrize("falhar_em", [None, AcaoSchtasks.END])
def test_parar_windows_desativa_e_encerra(
    tmp_path: Path, falhar_em: AcaoSchtasks | None
) -> None:
    agendador = _Agendador(falhar_em)
    agendador.ativadas[NOME_TAREFA_PROCESSO] = True

    parar(Sistema.WINDOWS, tmp_path, agendador)

    assert agendador.comandos == [
        _schtasks(NOME_TAREFA_PROCESSO, AcaoSchtasks.CHANGE, FLAG_DESATIVAR_SCHTASKS),
        _schtasks(NOME_TAREFA_PROCESSO, AcaoSchtasks.END),
    ]
    assert not agendador.ativadas[NOME_TAREFA_PROCESSO]


@pytest.mark.parametrize(
    ("saida", "esperado"),
    [(XML_ATIVADA, True), (XML_DESATIVADA, False), (None, False)],
    ids=["ativada", "desativada", "sem-tarefa"],
)
def test_rodando_windows(tmp_path: Path, saida: str | None, esperado: bool) -> None:
    consulta = _schtasks(NOME_TAREFA_PROCESSO, AcaoSchtasks.QUERY, FLAG_XML)
    respostas = {} if saida is None else {tuple(consulta): saida}
    assert rodando(Sistema.WINDOWS, tmp_path, _respondendo(respostas)) is esperado


def test_login_windows_cria_tarefa_de_logon_com_argumentos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USERDOMAIN", USUARIO[0])
    monkeypatch.setenv("USERNAME", USUARIO[1])
    agendador = _Agendador()
    assert not login_ligado(Sistema.WINDOWS, tmp_path, agendador.consultar)

    ligar_login(Sistema.WINDOWS, tmp_path, EXE_WINDOWS, agendador)

    assert login_ligado(Sistema.WINDOWS, tmp_path, agendador.consultar)
    raiz = agendador.raiz(NOME_TAREFA_LOGIN)
    assert _texto(raiz, XPATH_USUARIO) == "\\".join(USUARIO)
    assert raiz.find(f"{NS}Triggers/{NS}TimeTrigger") is None
    assert _argumentos_do_login(agendador) == ARGUMENTOS_INICIAR_LOGIN
    for xpath, esperado in XML_ESPERADO.items():
        assert _texto(raiz, xpath) == esperado, xpath


def test_desligar_login_windows_troca_a_acao_para_parar(tmp_path: Path) -> None:
    agendador = _Agendador()
    ligar_login(Sistema.WINDOWS, tmp_path, EXE_WINDOWS, agendador)

    desligar_login(Sistema.WINDOWS, tmp_path, agendador)

    assert NOME_TAREFA_LOGIN in agendador.ativadas
    assert _argumentos_do_login(agendador) == ARGUMENTOS_PARAR_LOGIN
    assert not login_ligado(Sistema.WINDOWS, tmp_path, agendador.consultar)


def test_migrar_legado_windows_troca_a_tarefa_antiga(tmp_path: Path) -> None:
    agendador = _Agendador()
    agendador.ativadas[NOME_TAREFA_SERVE] = True

    assert migrar_legado(
        Sistema.WINDOWS, tmp_path, EXE_WINDOWS, agendador, agendador.consultar
    )
    assert agendador.da(NOME_TAREFA_SERVE) == [
        _schtasks(NOME_TAREFA_SERVE, AcaoSchtasks.END),
        _schtasks(NOME_TAREFA_SERVE, AcaoSchtasks.DELETE, FLAG_FORCAR_SCHTASKS),
    ]
    assert agendador.ativadas == {NOME_TAREFA_LOGIN: True, NOME_TAREFA_PROCESSO: True}
    assert login_ligado(Sistema.WINDOWS, tmp_path, agendador.consultar)
    assert agendador.comandos[-1] == _schtasks(NOME_TAREFA_PROCESSO, AcaoSchtasks.RUN)

    agendador.comandos.clear()
    assert not migrar_legado(
        Sistema.WINDOWS, tmp_path, EXE_WINDOWS, agendador, agendador.consultar
    )
    assert not agendador.comandos


def test_remover_windows_apaga_as_tres_tarefas_mesmo_se_o_sistema_falha(
    tmp_path: Path,
) -> None:
    registro = Registro(falhar_em=AcaoSchtasks.END)
    remover(Sistema.WINDOWS, tmp_path, registro)
    assert registro.comandos == [
        _schtasks(tarefa, acao, *resto)
        for tarefa in (NOME_TAREFA_PROCESSO, NOME_TAREFA_LOGIN, NOME_TAREFA_SERVE)
        for acao, *resto in (
            (AcaoSchtasks.END,),
            (AcaoSchtasks.DELETE, FLAG_FORCAR_SCHTASKS),
        )
    ]


def test_main_serve_com_argumentos_repassa_ao_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import motor.__main__ as cli

    recebidos: list[list[str]] = []
    monkeypatch.setattr(sys, "argv", [EXECUTAVEL_SERVE, *ARGUMENTOS_INICIAR_LOGIN])
    monkeypatch.setattr(cli, "main", recebidos.append)

    cli.main_serve()

    assert recebidos == [ARGUMENTOS_INICIAR_LOGIN]
    assert not (Path(diretorio_dados()) / ARQUIVO_LOG_SERVE).exists()


def test_situacao_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _como(Sistema.WINDOWS, monkeypatch)
    agendador = _Agendador()
    sem_nada = situacao(tmp_path, agendador.consultar, lambda: False)
    assert sem_nada.estado is EstadoServico.PARADO
    assert not sem_nada.login
    assert sem_nada.ver_log.endswith(f"{ARQUIVO_LOG_SERVE}'")
    assert sem_nada.ver_log.startswith("Get-Content -Wait '")
    assert situacao(tmp_path, agendador.consultar, lambda: True) == Situacao(
        EstadoServico.NO_TERMINAL
    )

    ligar_login(Sistema.WINDOWS, tmp_path, EXE_WINDOWS, agendador)
    subir(Sistema.WINDOWS, tmp_path, EXE_WINDOWS, agendador)
    assert situacao(tmp_path, agendador.consultar, lambda: True) == Situacao(
        EstadoServico.ATIVO, login=True
    )
    caiu = situacao(tmp_path, agendador.consultar, lambda: False)
    assert caiu.estado is EstadoServico.PARADO
    assert caiu.login


def test_executavel_servico_windows_tem_exe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", PLATAFORMA_WINDOWS)
    monkeypatch.setattr(
        sysconfig,
        "get_config_var",
        lambda nome: SUFIXO_EXE if nome == VAR_CONFIG_EXE else None,
    )
    assert executavel_servico().endswith(f"{EXECUTAVEL_SERVE}{SUFIXO_EXE}")
