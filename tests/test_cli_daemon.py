from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from motor import agendador, assistente, servico
from motor.__main__ import main
from motor.agendador import SYSTEMCTL, Acao, Sistema
from motor.cli_daemon import (
    COMANDO_DAEMON,
    FLAG_INICIAR_LOGIN,
    FLAG_NUNCA_INICIAR_LOGIN,
    FLAG_PARAR_LOGIN,
    FLAG_PORTA,
    FLAG_SEM_NAVEGADOR,
    FLAG_SEM_PERGUNTAS,
    AcaoDaemon,
)
from motor.config import (
    PORTA_MAXIMA,
    PORTA_MINIMA,
    caminho_config_global,
    nunca_iniciar_login,
    porta_daemon,
)
from motor.config_edicao import gravar_nunca_iniciar_login, gravar_porta_daemon
from motor.daemon import PORTA_PADRAO
from motor.errors import CodigoSaida
from motor.servico import (
    ARGUMENTOS_LEGADOS,
    ARGUMENTOS_SERVE,
    ARQUIVO_SERVICE,
    ESTADO_SYSTEMD_ATIVO,
    ESTADO_SYSTEMD_HABILITADO,
    caminho,
)
from tests.test_agendador import Registro

AVISO_RODAR = "para rodar em segundo plano, use `monitor-versoes daemon iniciar`"
PERGUNTA_LOGIN = "Iniciar também no login?"
PERGUNTA_SALVAR = "Salvar essa escolha para as próximas vezes?"
PERGUNTA_PARAR_LOGIN = "Parar de iniciar no login também?"
ERRO_NO_TERMINAL = "há um daemon rodando no terminal; feche-o"
VER_LOG_LINUX = f"journalctl --user -u {ARQUIVO_SERVICE}"
PORTA_SALVA = 9100
PORTA_NOVA = 9200
EXE_ANTIGO = "/opt/antigo/bin/monitor-versoes"
SIM = "sim"
ROTULO_RODANDO = "rodando"
ROTULO_NO_TERMINAL = "rodando no terminal"
ROTULO_PARADO = "parado"
INATIVO_SYSTEMD = "inactive"
DESABILITADO_SYSTEMD = "disabled"


class _Systemd(Registro):
    """systemd de usuário de mentira: lembra se a unit roda e se inicia no login."""

    def __init__(self, ativo: bool = False, login: bool = False) -> None:
        super().__init__()
        self.ativo = ativo
        self.login = login

    def __call__(self, cmd: list[str]) -> None:
        super().__call__(cmd)
        acao = cmd[len(SYSTEMCTL)]
        if acao in {Acao.RESTART, Acao.STOP}:
            self.ativo = acao == Acao.RESTART
        if acao in {Acao.ENABLE, Acao.DISABLE}:
            self.login = acao == Acao.ENABLE

    def consultar(self, cmd: list[str]) -> str | None:
        acao = cmd[len(SYSTEMCTL)]
        if acao == Acao.IS_ACTIVE:
            return f"{ESTADO_SYSTEMD_ATIVO if self.ativo else INATIVO_SYSTEMD}\n"
        if acao == Acao.IS_ENABLED:
            habilitado = (
                ESTADO_SYSTEMD_HABILITADO if self.login else DESABILITADO_SYSTEMD
            )
            return f"{habilitado}\n"
        return None

    def acoes(self) -> list[str]:
        return [cmd[len(SYSTEMCTL)] for cmd in self.comandos]


class _Porta:
    """O `serve_responde` de mentira: sem resposta fixa, responde quando o serviço roda."""

    def __init__(self, systemd: _Systemd, responde: bool | None) -> None:
        self.systemd = systemd
        self.responde = responde
        self.sondadas: list[int] = []

    def __call__(self, porta: int, esperar: bool) -> bool:
        self.sondadas.append(porta)
        return self.systemd.ativo if self.responde is None else self.responde


class _Confirmar:
    def __init__(self, respostas: list[bool]) -> None:
        self.respostas = list(respostas)
        self.perguntas: list[str] = []

    def __call__(self, texto: str, padrao: bool) -> bool:
        self.perguntas.append(texto)
        return self.respostas.pop(0)


@dataclass(frozen=True)
class _Maquina:
    systemd: _Systemd
    porta: _Porta
    confirmar: _Confirmar


@pytest.fixture
def maquina(monkeypatch: pytest.MonkeyPatch) -> Callable[..., _Maquina]:
    def montar(
        ativo: bool = False,
        login: bool = False,
        responde: bool | None = None,
        terminal: bool = True,
        respostas: list[bool] | None = None,
    ) -> _Maquina:
        systemd = _Systemd(ativo, login)
        m = _Maquina(systemd, _Porta(systemd, responde), _Confirmar(respostas or []))
        for modulo in (agendador, servico):
            monkeypatch.setattr(modulo, "sistema_atual", lambda: Sistema.LINUX)
        monkeypatch.setattr(agendador, "rodar_comando_do_sistema", systemd)
        monkeypatch.setattr(servico, "consultar_do_sistema", systemd.consultar)
        monkeypatch.setattr(servico, "serve_responde", m.porta)
        monkeypatch.setattr(assistente, "terminal", lambda: terminal)
        monkeypatch.setattr(assistente, "confirmar", m.confirmar)
        return m

    return montar


@pytest.fixture
def servidos(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, bool]]:
    import motor.daemon.app as daemon_app

    vistos: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        daemon_app,
        "servir",
        lambda porta, ambiente, abrir_navegador: vistos.append(
            (porta, abrir_navegador)
        ),
    )
    return vistos


def _daemon(acao: AcaoDaemon, *flags: str) -> None:
    main([COMANDO_DAEMON, acao, *flags])


def _erro(acao: AcaoDaemon, *flags: str) -> None:
    with pytest.raises(SystemExit) as saida:
        _daemon(acao, *flags)
    assert saida.value.code == CodigoSaida.ERRO


@pytest.mark.parametrize("tty", [True, False])
def test_rodar_avisa_so_em_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys, servidos, tty: bool
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: tty)
    _daemon(AcaoDaemon.RODAR, FLAG_SEM_NAVEGADOR)
    assert (AVISO_RODAR in capsys.readouterr().out) is tty
    assert servidos == [(PORTA_PADRAO, False)]


def test_rodar_usa_a_porta_salva_e_porta_da_flag_nao_salva(servidos) -> None:
    gravar_porta_daemon(PORTA_SALVA)
    _daemon(AcaoDaemon.RODAR)
    _daemon(AcaoDaemon.RODAR, FLAG_PORTA, str(PORTA_NOVA))
    assert servidos == [(PORTA_SALVA, True), (PORTA_NOVA, True)]
    assert porta_daemon() == PORTA_SALVA


@pytest.mark.parametrize(
    ("flags", "login", "nunca", "terminal", "respostas", "perguntas", "esperado"),
    [
        ([FLAG_INICIAR_LOGIN], False, True, True, [], [], (True, True)),
        ([FLAG_NUNCA_INICIAR_LOGIN], True, False, True, [], [], (False, True)),
        ([], True, False, True, [], [], (True, False)),
        ([], False, True, True, [], [], (False, True)),
        ([FLAG_SEM_PERGUNTAS], False, False, True, [], [], (False, False)),
        ([], False, False, False, [], [], (False, False)),
        ([], False, False, True, [True], [PERGUNTA_LOGIN], (True, False)),
        (
            [],
            False,
            False,
            True,
            [False, True],
            [PERGUNTA_LOGIN, PERGUNTA_SALVAR],
            (False, True),
        ),
        (
            [],
            False,
            False,
            True,
            [False, False],
            [PERGUNTA_LOGIN, PERGUNTA_SALVAR],
            (False, False),
        ),
    ],
    ids=[
        "flag-liga",
        "flag-nunca",
        "ja-ligado",
        "nunca-salvo",
        "sem-perguntas",
        "sem-terminal",
        "sim",
        "nao-e-salva",
        "nao-sem-salvar",
    ],
)
def test_iniciar_sobe_e_segue_a_tabela_de_login(
    maquina, flags, login, nunca, terminal, respostas, perguntas, esperado
) -> None:
    gravar_nunca_iniciar_login(nunca)
    m = maquina(login=login, terminal=terminal, respostas=respostas)

    _daemon(AcaoDaemon.INICIAR, *flags)

    assert m.systemd.ativo
    assert m.confirmar.perguntas == perguntas
    assert (m.systemd.login, nunca_iniciar_login()) == esperado


@pytest.mark.parametrize(
    ("flags", "login_depois"), [([FLAG_INICIAR_LOGIN], True), ([], False)]
)
def test_iniciar_ja_rodando_nao_reinicia_mas_aplica_a_flag_de_login(
    maquina, flags, login_depois
) -> None:
    m = maquina(ativo=True)
    _daemon(AcaoDaemon.INICIAR, *flags)
    assert Acao.RESTART not in m.systemd.acoes()
    assert m.systemd.login is login_depois
    assert m.confirmar.perguntas == []


def test_iniciar_porta_nova_com_daemon_rodando_reinicia(maquina) -> None:
    m = maquina(ativo=True, login=True)
    _daemon(AcaoDaemon.INICIAR, FLAG_PORTA, str(PORTA_NOVA))
    assert Acao.RESTART in m.systemd.acoes()
    assert m.porta.sondadas[-1] == PORTA_NOVA
    assert porta_daemon() == PORTA_NOVA


def test_iniciar_que_nao_responde_erra_com_o_log(maquina, caplog) -> None:
    maquina(responde=False, terminal=False)
    _erro(AcaoDaemon.INICIAR)
    assert VER_LOG_LINUX in caplog.text


@pytest.mark.parametrize(
    ("flags", "terminal", "respostas", "perguntas", "login_depois"),
    [
        ([FLAG_PARAR_LOGIN], True, [], [], False),
        ([], True, [True], [PERGUNTA_PARAR_LOGIN], False),
        ([], True, [False], [PERGUNTA_PARAR_LOGIN], True),
        ([FLAG_SEM_PERGUNTAS], True, [], [], True),
        ([], False, [], [], True),
    ],
    ids=["flag", "sim", "nao", "sem-perguntas", "sem-terminal"],
)
def test_parar_com_login_pergunta_ou_obedece_a_flag(
    maquina, flags, terminal, respostas, perguntas, login_depois
) -> None:
    m = maquina(ativo=True, login=True, terminal=terminal, respostas=respostas)
    _daemon(AcaoDaemon.PARAR, *flags)
    assert not m.systemd.ativo
    assert m.confirmar.perguntas == perguntas
    assert m.systemd.login is login_depois


def test_reiniciar_sobe_o_parado_sem_mexer_no_login(maquina) -> None:
    m = maquina()
    _daemon(AcaoDaemon.REINICIAR, FLAG_PORTA, str(PORTA_NOVA))
    assert m.systemd.ativo
    assert not m.systemd.login
    assert m.confirmar.perguntas == []
    assert m.porta.sondadas[-1] == PORTA_NOVA
    assert porta_daemon() == PORTA_NOVA


@pytest.mark.parametrize(
    "acao", [AcaoDaemon.INICIAR, AcaoDaemon.PARAR, AcaoDaemon.REINICIAR]
)
def test_iniciar_e_parar_recusam_daemon_no_terminal(maquina, caplog, acao) -> None:
    m = maquina(responde=True)
    _erro(acao)
    assert caplog.messages == [ERRO_NO_TERMINAL]
    assert not {Acao.RESTART, Acao.STOP} & set(m.systemd.acoes())


@pytest.mark.parametrize(
    ("ativo", "responde", "rotulo"),
    [
        (True, False, ROTULO_RODANDO),
        (False, True, ROTULO_NO_TERMINAL),
        (False, False, ROTULO_PARADO),
    ],
)
def test_estado_mostra_rodando_login_nunca_e_log(
    maquina, capsys, ativo, responde, rotulo
) -> None:
    gravar_nunca_iniciar_login(True)
    maquina(ativo=ativo, login=True, responde=responde)
    _daemon(AcaoDaemon.ESTADO)
    assert capsys.readouterr().out.splitlines() == [
        f"daemon: {rotulo}",
        f"iniciar no login: {SIM}",
        f"nunca iniciar no login: {SIM}",
        f"log: {VER_LOG_LINUX}",
    ]


def _unit_antiga(home: Path) -> Path:
    unit = caminho(Sistema.LINUX, home)
    unit.parent.mkdir(parents=True)
    unit.write_text(
        f'[Service]\nExecStart="{EXE_ANTIGO}" {" ".join(ARGUMENTOS_LEGADOS)}\n'
    )
    return unit


@pytest.mark.parametrize("porta", [PORTA_MINIMA - 1, PORTA_MAXIMA + 1])
@pytest.mark.parametrize(
    "acao", [AcaoDaemon.RODAR, AcaoDaemon.INICIAR, AcaoDaemon.REINICIAR]
)
def test_porta_invalida_nao_altera_nada(maquina, servidos, acao, porta) -> None:
    m = maquina()
    unit = _unit_antiga(Path.home())
    antes = unit.read_text()

    _erro(acao, FLAG_PORTA, str(porta))

    assert m.systemd.comandos == []
    assert servidos == []
    assert unit.read_text() == antes
    assert not Path(caminho_config_global()).exists()


def test_ponte_do_serve_legado_regrava_e_roda(
    monkeypatch: pytest.MonkeyPatch, maquina, servidos
) -> None:
    monkeypatch.setattr(sys, "platform", Sistema.LINUX.value)
    m = maquina()
    unit = _unit_antiga(Path.home())

    main(list(ARGUMENTOS_LEGADOS))

    assert " ".join(ARGUMENTOS_SERVE) in unit.read_text()
    assert m.systemd.acoes() == [Acao.DAEMON_RELOAD]
    assert servidos == [(PORTA_PADRAO, False)]
