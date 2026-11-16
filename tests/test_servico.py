from __future__ import annotations

import os
import plistlib
import re
import socket
import sys
import sysconfig
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from motor import servico
from motor.__main__ import COMANDO_SERVE, main
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
from motor.errors import BackendIndisponivel, ErroDeEntrada
from motor.servico import (
    ARGUMENTOS_SERVE,
    ARQUIVO_LOG_LAUNCHD,
    ARQUIVO_LOG_SERVE,
    ARQUIVO_SERVICE,
    EXECUTAVEL_SERVE,
    FLAG_FORCAR,
    FLAG_PERSISTIR,
    NOME_TAREFA_SERVE,
    ROTULO_LAUNCHD,
    EstadoServico,
    caminho,
    desligar,
    executavel_motor,
    executavel_servico,
    ligado,
    ligar,
    reiniciar_se_ligado,
    situacao,
)
from tests.plataforma import PLATAFORMA_WINDOWS
from tests.test_agendador import Registro

EXE = "/opt/venv/bin/monitor-versoes"
ATIVO_LINUX = "active\n"
ATIVO_MACOS = "\tstate = running\n"
OUTROS_ESTADOS = (None, "inactive\n", "\tstate = waiting\n")
VER_LOG_LINUX = f"journalctl --user -u {ARQUIVO_SERVICE}"
VER_LOG_MACOS = f"tail -f ~/Library/Logs/{ARQUIVO_LOG_LAUNCHD}"
FLAG_PORTA = "--porta"
FLAG_SEM_NAVEGADOR = ARGUMENTOS_SERVE[-1]


def _nunca_pergunta() -> bool:
    raise AssertionError("só o Windows pergunta se o serve responde")


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


def _devolvendo(saida: str | None) -> Callable[[list[str]], str | None]:
    return lambda _: saida


def _alvo_mac() -> str:
    return f"gui/{os.getuid()}/{ROTULO_LAUNCHD}"


def _criar_arquivo(sistema: Sistema, home: Path) -> Path:
    arquivo = caminho(sistema, home)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.touch()
    return arquivo


@pytest.mark.parametrize("sistema", SISTEMAS)
def test_ligar_cria_o_servico_e_sobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sistema: Sistema
) -> None:
    _como(sistema, monkeypatch)
    registro = Registro()
    ligar(sistema, tmp_path, EXE, registro)

    arquivo = caminho(sistema, tmp_path)
    assert arquivo.exists()
    if sistema is Sistema.LINUX:
        texto = arquivo.read_text()
        assert f'ExecStart="{EXE}" {" ".join(ARGUMENTOS_SERVE)}' in texto
        assert "Restart=on-failure" in texto
        assert registro.comandos == [
            [*SYSTEMCTL, Acao.DAEMON_RELOAD],
            [*SYSTEMCTL, Acao.ENABLE, ARQUIVO_SERVICE],
            [*SYSTEMCTL, Acao.RESTART, ARQUIVO_SERVICE],
        ]
    else:
        dados = plistlib.loads(arquivo.read_bytes())
        log = str(tmp_path / "Library" / "Logs" / ARQUIVO_LOG_LAUNCHD)
        assert dados["ProgramArguments"] == [EXE, *ARGUMENTOS_SERVE]
        assert dados["RunAtLoad"] is True
        assert dados["KeepAlive"] is True
        assert dados["StandardOutPath"] == log
        assert dados["StandardErrorPath"] == log
        assert registro.comandos == [
            [LAUNCHCTL, Acao.UNLOAD, FLAG_PERSISTIR, str(arquivo)],
            [LAUNCHCTL, Acao.LOAD, FLAG_PERSISTIR, str(arquivo)],
        ]


@pytest.mark.parametrize(
    ("sistema", "acao"),
    [
        (Sistema.LINUX, Acao.DISABLE),
        (Sistema.LINUX, Acao.DAEMON_RELOAD),
        pytest.param(Sistema.MACOS, Acao.UNLOAD, marks=pula_mac_no_windows),
    ],
)
def test_desligar_para_e_remove_mesmo_se_o_sistema_falha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sistema: Sistema, acao: Acao
) -> None:
    _como(sistema, monkeypatch)
    arquivo = _criar_arquivo(sistema, tmp_path)
    desligar(sistema, tmp_path, Registro(falhar_em=acao))
    assert not arquivo.exists()


@pytest.mark.parametrize("sistema", SISTEMAS)
def test_reiniciar_se_ligado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sistema: Sistema
) -> None:
    _como(sistema, monkeypatch)
    desligado = Registro()
    assert not reiniciar_se_ligado(tmp_path, desligado)
    assert not desligado.comandos

    _criar_arquivo(sistema, tmp_path)
    registro = Registro()
    assert reiniciar_se_ligado(tmp_path, registro)
    esperado = (
        [*SYSTEMCTL, Acao.RESTART, ARQUIVO_SERVICE]
        if sistema is Sistema.LINUX
        else [LAUNCHCTL, Acao.KICKSTART, FLAG_FORCAR, _alvo_mac()]
    )
    assert registro.comandos == [esperado]


def test_reiniciar_se_ligado_sem_suporte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(servico, "sistema_atual", _sem_suporte)
    registro = Registro()
    assert not reiniciar_se_ligado(tmp_path, registro)
    assert not ligado(tmp_path)
    assert not registro.comandos


@pytest.mark.parametrize(
    ("sistema", "ativo", "ver_log"),
    [
        pytest.param(
            Sistema.LINUX,
            ATIVO_LINUX,
            VER_LOG_LINUX,
            id="linux",
        ),
        pytest.param(
            Sistema.MACOS,
            ATIVO_MACOS,
            VER_LOG_MACOS,
            marks=pula_mac_no_windows,
            id="macos",
        ),
    ],
)
def test_situacao(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sistema: Sistema,
    ativo: str,
    ver_log: str,
) -> None:
    _como(sistema, monkeypatch)
    assert (
        situacao(tmp_path, lambda _: ativo, _nunca_pergunta).estado
        is EstadoServico.DESLIGADO
    )

    _criar_arquivo(sistema, tmp_path)
    assert (
        situacao(tmp_path, lambda _: ativo, _nunca_pergunta).estado
        is EstadoServico.ATIVO
    )
    for saida in OUTROS_ESTADOS:
        parado = situacao(tmp_path, _devolvendo(saida), _nunca_pergunta)
        assert parado.estado is EstadoServico.PARADO
        assert parado.ver_log == ver_log


def test_situacao_sem_suporte(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(servico, "sistema_atual", _sem_suporte)
    assert (
        situacao(tmp_path, lambda _: None, _nunca_pergunta).estado
        is EstadoServico.SEM_SUPORTE
    )


def test_executavel_motor_nao_depende_do_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")
    exe = Path(executavel_motor())
    assert exe.is_absolute()
    assert exe.stem == servico.EXECUTAVEL


@pytest.mark.parametrize(
    ("sistema", "acao"),
    [
        pytest.param(Sistema.LINUX, Acao.ENABLE, id="linux-enable"),
        pytest.param(Sistema.LINUX, Acao.RESTART, id="linux-restart"),
        pytest.param(Sistema.MACOS, Acao.LOAD, id="macos", marks=pula_mac_no_windows),
    ],
)
def test_ligar_que_falha_propaga_e_nao_deixa_o_arquivo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sistema: Sistema, acao: Acao
) -> None:
    _como(sistema, monkeypatch)
    with pytest.raises(BackendIndisponivel):
        ligar(sistema, tmp_path, EXE, Registro(falhar_em=acao))
    assert not ligado(tmp_path)


def test_ligar_com_restart_que_falha_desfaz_o_enable_antes_de_remover_o_arquivo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _como(Sistema.LINUX, monkeypatch)
    arquivo_existia_no_disable: list[bool] = []

    class RegistroComArquivo(Registro):
        def __call__(self, cmd: list[str]) -> None:
            if Acao.DISABLE in cmd:
                arquivo_existia_no_disable.append(
                    caminho(Sistema.LINUX, tmp_path).exists()
                )
            super().__call__(cmd)

    registro = RegistroComArquivo(falhar_em=Acao.RESTART)
    with pytest.raises(BackendIndisponivel):
        ligar(Sistema.LINUX, tmp_path, EXE, registro)
    assert [*SYSTEMCTL, Acao.DISABLE, ARQUIVO_SERVICE] in registro.comandos
    assert arquivo_existia_no_disable == [True]


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


@pula_mac_no_windows
def test_ligar_no_macos_com_o_job_ja_carregado_recarrega(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _como(Sistema.MACOS, monkeypatch)
    registro = Registro(falhar_em=Acao.UNLOAD)
    ligar(Sistema.MACOS, tmp_path, EXE, registro)
    assert registro.comandos[-1][1] == Acao.LOAD


EXE_WINDOWS = r"C:\venv\Scripts\monitor-versoes-serve.exe"
SAIDA_ALEMA = "FEHLER: Das System kann die angegebene Datei nicht finden."
PADRAO_INICIO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d"


def _schtasks(acao: AcaoSchtasks, *resto: str) -> list[str]:
    return [SCHTASKS, acao, FLAG_TAREFA, NOME_TAREFA_SERVE, *resto]


def test_ligar_windows_cria_a_tarefa_pelo_xml_e_a_roda(tmp_path: Path) -> None:
    chamadas: list[list[str]] = []
    xmls: list[str] = []

    def rodar(cmd: list[str]) -> None:
        chamadas.append(cmd)
        if AcaoSchtasks.CREATE in cmd:
            xmls.append(Path(cmd[cmd.index(FLAG_XML) + 1]).read_text("utf-16"))

    ligar(Sistema.WINDOWS, tmp_path, EXE_WINDOWS, rodar)

    arquivo = chamadas[0][chamadas[0].index(FLAG_XML) + 1]
    assert chamadas == [
        _schtasks(AcaoSchtasks.CREATE, FLAG_XML, arquivo, FLAG_FORCAR_SCHTASKS),
        _schtasks(AcaoSchtasks.RUN),
    ]
    (xml,) = xmls
    assert re.search(f"<StartBoundary>{PADRAO_INICIO}</StartBoundary>", xml)
    assert f"<Command>{EXE_WINDOWS}</Command>" in xml
    assert "<Interval>PT1M</Interval>" in xml
    assert not Path(arquivo).exists()


def test_ligar_windows_que_falha_apaga_a_tarefa(tmp_path: Path) -> None:
    registro = Registro(falhar_em=AcaoSchtasks.RUN)
    with pytest.raises(BackendIndisponivel):
        ligar(Sistema.WINDOWS, tmp_path, EXE_WINDOWS, registro)
    assert registro.comandos[-1] == _schtasks(AcaoSchtasks.DELETE, FLAG_FORCAR_SCHTASKS)


def test_desligar_windows_encerra_e_apaga(tmp_path: Path) -> None:
    registro = Registro(falhar_em=AcaoSchtasks.END)
    desligar(Sistema.WINDOWS, tmp_path, registro)
    assert registro.comandos == [
        _schtasks(AcaoSchtasks.END),
        _schtasks(AcaoSchtasks.DELETE, FLAG_FORCAR_SCHTASKS),
    ]


def test_situacao_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _como(Sistema.WINDOWS, monkeypatch)
    assert (
        situacao(tmp_path, _devolvendo(None), _nunca_pergunta).estado
        is EstadoServico.DESLIGADO
    )
    parado = situacao(tmp_path, _devolvendo(SAIDA_ALEMA), lambda: False)
    assert parado.estado is EstadoServico.PARADO
    assert ARQUIVO_LOG_SERVE in parado.ver_log
    assert (
        situacao(tmp_path, _devolvendo(""), lambda: True).estado is EstadoServico.ATIVO
    )


def test_reiniciar_se_ligado_no_windows_nao_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _como(Sistema.WINDOWS, monkeypatch)
    registro = Registro()
    assert not reiniciar_se_ligado(tmp_path, registro)
    assert not registro.comandos


def test_executavel_servico_windows_tem_exe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", PLATAFORMA_WINDOWS)
    monkeypatch.setattr(
        sysconfig,
        "get_config_var",
        lambda nome: ".exe" if nome == "EXE" else None,
    )
    assert executavel_servico().endswith(f"{EXECUTAVEL_SERVE}.exe")
