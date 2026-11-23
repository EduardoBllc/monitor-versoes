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
from motor.__main__ import main
from motor.agendador import (
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
from motor.cli_daemon import COMANDO_DAEMON, AcaoDaemon
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
from tests.test_agendador import Registro

EXE = "/opt/venv/bin/monitor-versoes"
ARGUMENTOS_INICIAR_LOGIN = ["daemon", "iniciar", "--sem-perguntas"]
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


def _devolvendo(saida: str | None) -> Callable[[list[str]], str | None]:
    return lambda _: saida


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
        log = str(tmp_path / "Library" / "Logs" / ARQUIVO_LOG_LAUNCHD)
        assert dados["StandardOutPath"] == log
        assert dados["StandardErrorPath"] == log
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
        *_comandos_de_subir(Sistema.MACOS, tmp_path),
        [LAUNCHCTL, Acao.UNLOAD, FLAG_PERSISTIR, str(legado)],
    ]

    assert not migrar_legado(Sistema.MACOS, tmp_path, EXE, Registro(), _respondendo({}))


@pula_mac_no_windows
def test_migrar_legado_macos_que_falha_ao_subir_mantem_o_plist_antigo(
    tmp_path: Path,
) -> None:
    legado = _agente(tmp_path, ROTULO_LEGADO)
    legado.parent.mkdir(parents=True)
    legado.touch()
    registro = Registro(falhar_em=Acao.LOAD)

    with pytest.raises(BackendIndisponivel):
        migrar_legado(Sistema.MACOS, tmp_path, EXE, registro, _respondendo({}))
    assert legado.exists()
    assert [
        LAUNCHCTL,
        Acao.UNLOAD,
        FLAG_PERSISTIR,
        str(legado),
    ] not in registro.comandos


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
def test_daemon_rodar_sem_navegador_nao_abre(
    monkeypatch: pytest.MonkeyPatch, sem_navegador: bool
) -> None:
    import threading

    import uvicorn

    import motor.daemon.app as daemon_app

    with socket.socket() as livre:
        livre.bind(("127.0.0.1", 0))
        porta = livre.getsockname()[1]
    abertos: list[str] = []

    def timer(_atraso, funcao, args):
        return SimpleNamespace(start=lambda: funcao(*args))

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(threading, "Timer", timer)
    monkeypatch.setattr(daemon_app, "_abrir_navegador", abertos.append)

    main(
        [
            COMANDO_DAEMON,
            AcaoDaemon.RODAR,
            FLAG_PORTA,
            str(porta),
            *([FLAG_SEM_NAVEGADOR] * sem_navegador),
        ]
    )

    assert bool(abertos) is not sem_navegador


EXE_WINDOWS = r"C:\venv\Scripts\monitor-versoes-serve.exe"
SAIDA_ALEMA = "FEHLER: Das System kann die angegebene Datei nicht finden."
SUFIXO_EXE = ".exe"
VAR_CONFIG_EXE = "EXE"
NS = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
USUARIO = ("DOMINIO", "fulano")
PADRAO_INICIO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d"
XPATH_USUARIO = "Triggers/LogonTrigger/UserId"
XPATH_INICIO = "Triggers/TimeTrigger/StartBoundary"
INTERVALO_REPETICAO = "PT1M"
LOGON_INTERATIVO = "InteractiveToken"
NIVEL_MINIMO = "LeastPrivilege"
POLITICA_IGNORAR = "IgnoreNew"
SEM_LIMITE = "PT0S"
FALSO = "false"
XML_ESPERADO = {
    "Triggers/TimeTrigger/Repetition/Interval": INTERVALO_REPETICAO,
    "Principals/Principal/LogonType": LOGON_INTERATIVO,
    "Principals/Principal/RunLevel": NIVEL_MINIMO,
    "Settings/MultipleInstancesPolicy": POLITICA_IGNORAR,
    "Settings/DisallowStartIfOnBatteries": FALSO,
    "Settings/StopIfGoingOnBatteries": FALSO,
    "Settings/ExecutionTimeLimit": SEM_LIMITE,
    "Actions/Exec/Command": EXE_WINDOWS,
}


def _schtasks(acao: AcaoSchtasks, *resto: str) -> list[str]:
    return [SCHTASKS, acao, FLAG_TAREFA, NOME_TAREFA_SERVE, *resto]


def test_subir_windows_cria_a_tarefa_pelo_xml_e_a_roda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USERDOMAIN", USUARIO[0])
    monkeypatch.setenv("USERNAME", USUARIO[1])
    chamadas: list[list[str]] = []
    xmls: list[str] = []

    def rodar(cmd: list[str]) -> None:
        chamadas.append(cmd)
        if AcaoSchtasks.CREATE in cmd:
            xmls.append(Path(cmd[cmd.index(FLAG_XML) + 1]).read_text("utf-16"))

    subir(Sistema.WINDOWS, tmp_path, EXE_WINDOWS, rodar)

    arquivo = chamadas[1][chamadas[1].index(FLAG_XML) + 1]
    assert chamadas == [
        _schtasks(AcaoSchtasks.END),
        _schtasks(AcaoSchtasks.CREATE, FLAG_XML, arquivo, FLAG_FORCAR_SCHTASKS),
        _schtasks(AcaoSchtasks.RUN),
    ]
    (xml,) = xmls
    raiz = ET.fromstring(xml.split("?>", 1)[1])

    def texto(caminho: str) -> str | None:
        return raiz.findtext("/".join(NS + p for p in caminho.split("/")))

    assert texto(XPATH_USUARIO) == "\\".join(USUARIO)
    assert re.fullmatch(PADRAO_INICIO, texto(XPATH_INICIO) or "")
    assert raiz.find(f".//{NS}Repetition/{NS}Duration") is None
    for xpath, esperado in XML_ESPERADO.items():
        assert texto(xpath) == esperado, xpath
    assert not Path(arquivo).exists()


def test_subir_windows_sem_tarefa_anterior_cria_e_roda(tmp_path: Path) -> None:
    registro = Registro(falhar_em=AcaoSchtasks.END)
    subir(Sistema.WINDOWS, tmp_path, EXE_WINDOWS, registro)
    assert [cmd[1] for cmd in registro.comandos] == [
        AcaoSchtasks.END,
        AcaoSchtasks.CREATE,
        AcaoSchtasks.RUN,
    ]


def test_subir_windows_que_falha_apaga_a_tarefa(tmp_path: Path) -> None:
    registro = Registro(falhar_em=AcaoSchtasks.RUN)
    with pytest.raises(BackendIndisponivel):
        subir(Sistema.WINDOWS, tmp_path, EXE_WINDOWS, registro)
    assert registro.comandos[-1] == _schtasks(AcaoSchtasks.DELETE, FLAG_FORCAR_SCHTASKS)


def test_remover_windows_encerra_e_apaga(tmp_path: Path) -> None:
    registro = Registro(falhar_em=AcaoSchtasks.END)
    remover(Sistema.WINDOWS, tmp_path, registro)
    assert registro.comandos == [
        _schtasks(AcaoSchtasks.END),
        _schtasks(AcaoSchtasks.DELETE, FLAG_FORCAR_SCHTASKS),
    ]


def test_situacao_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _como(Sistema.WINDOWS, monkeypatch)
    sem_tarefa = situacao(tmp_path, _devolvendo(None), lambda: False)
    assert sem_tarefa.estado is EstadoServico.PARADO
    assert not sem_tarefa.login
    assert situacao(tmp_path, _devolvendo(None), lambda: True) == Situacao(
        EstadoServico.NO_TERMINAL
    )
    parado = situacao(tmp_path, _devolvendo(SAIDA_ALEMA), lambda: False)
    assert parado.estado is EstadoServico.PARADO
    assert parado.login
    assert parado.ver_log.endswith(f"{ARQUIVO_LOG_SERVE}'")
    assert parado.ver_log.startswith("Get-Content -Wait '")
    assert situacao(tmp_path, _devolvendo(""), lambda: True) == Situacao(
        EstadoServico.ATIVO, login=True
    )


def test_executavel_servico_windows_tem_exe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", PLATAFORMA_WINDOWS)
    monkeypatch.setattr(
        sysconfig,
        "get_config_var",
        lambda nome: SUFIXO_EXE if nome == VAR_CONFIG_EXE else None,
    )
    assert executavel_servico().endswith(f"{EXECUTAVEL_SERVE}{SUFIXO_EXE}")
