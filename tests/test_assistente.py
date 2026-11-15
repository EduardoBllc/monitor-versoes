from __future__ import annotations

import subprocess
import sys
import tomllib
import webbrowser
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from unittest.mock import patch

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from motor import agendador, assistente, instalacao, plugins, servico
from motor.__main__ import COMANDO_SERVE, main
from motor.agendador import FLAG_AGORA, SYSTEMCTL, Acao, Sistema
from motor.assistente import OrigemOutro
from motor.cli_instalacao import COMANDO_PLUGIN, AcaoPlugin
from motor.config import VAR_XDG_CONFIG_HOME, Chave, Tabela, caminho_config_global
from motor.config_edicao import GrupoPlugin
from motor.diagnostico import Peca
from motor.errors import CodigoSaida
from motor.servico import ARQUIVO_SERVICE, COMANDO_CONFIGURAR, EXECUTAVEL

BAIXO = "\x1b[B"
CIMA = "\x1b[A"
ENTER = "\r"
CTRL_C = "\x03"
SIM = "s"
NAO = "n"

SAIDA_OK = 0
URL_MOTOR = "https://github.com/EduardoBllc/monitor-versoes.git"
URL_OUTRO = "https://example.com/outro-plugin.git"
FONTE = "tests.fontes_falsas:FonteFixa"
HOST = "tests.fontes_falsas:HostFalso"
JIRA = "jira"
FONTE_NOVA = "minha"
OUTRA_FONTE = "outra"
HOST_NOVO = "host"
WINDOWS = "win32"
BITBUCKET = "bitbucket"

LIGAR = [
    [*SYSTEMCTL, Acao.DAEMON_RELOAD],
    [*SYSTEMCTL, Acao.ENABLE, FLAG_AGORA, ARQUIVO_SERVICE],
]
DESLIGAR = [
    [*SYSTEMCTL, Acao.DISABLE, FLAG_AGORA, ARQUIVO_SERVICE],
    [*SYSTEMCTL, Acao.DAEMON_RELOAD],
]

ORIGINAL = """\
# config central de teste
[branches]
principal = "develop"  # a principal daqui

[repos.x]
caminho = "{repo}"

[ambiente]
BITBUCKET_EMAIL = "quem@exemplo.com"
"""
COM_FONTES = f"""\
[tarefas]
fonte = "{JIRA}"

[prs]
fonte = "{BITBUCKET}"
"""


@dataclass
class Cenario:
    pontos: dict[str, dict[str, str]]
    pacote: dict[str, dict[str, str]] = field(default_factory=dict)
    instalados: list[str] = field(default_factory=list)
    comandos: list[list[str]] = field(default_factory=list)
    abertos: list[str] = field(default_factory=list)
    original: str = ""

    @property
    def config(self) -> Path:
        return Path(caminho_config_global())

    def escrever(self, texto: str) -> None:
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text(texto)
        self.original = texto

    def fontes(self) -> dict[str, object]:
        dados = tomllib.loads(self.config.read_text())
        return {
            t: dados[t][Chave.FONTE]
            for t in (Tabela.TAREFAS, Tabela.PRS)
            if Chave.FONTE in dados.get(t, {})
        }

    def unit(self) -> Path:
        return servico.caminho(Sistema.LINUX, Path.home())


@pytest.fixture
def cen(monkeypatch, tmp_path) -> Cenario:
    monkeypatch.setenv(VAR_XDG_CONFIG_HOME, str(tmp_path / "xdg"))
    c = Cenario(
        pontos={GrupoPlugin.TAREFAS: {JIRA: FONTE}, GrupoPlugin.PRS: {BITBUCKET: HOST}}
    )

    def pontos(group: str) -> list[EntryPoint]:
        if group not in c.pontos:
            return list(entry_points(group=group))
        return [EntryPoint(n, v, group) for n, v in c.pontos[group].items()]

    def instalar(origem: str) -> bool:
        c.instalados.append(origem)
        for grupo, novos in c.pacote.items():
            c.pontos[grupo].update(novos)
        return True

    monkeypatch.setattr(plugins, "entry_points", pontos)
    monkeypatch.setattr(assistente, "instalar_plugin", instalar)
    monkeypatch.setattr(assistente, "_terminal", lambda: True)
    monkeypatch.setattr(assistente, "_serve_responde", lambda esperar: False)
    monkeypatch.setattr(webbrowser, "open", c.abertos.append)
    monkeypatch.setattr(instalacao, "url_do_motor", lambda: URL_MOTOR)
    monkeypatch.setattr(agendador, "rodar_comando_do_sistema", c.comandos.append)
    repo = tmp_path / "repo"
    repo.mkdir()
    c.escrever(ORIGINAL.format(repo=repo))
    return c


def _rodar(*teclas: str, plataforma: str = Sistema.LINUX) -> int:
    with create_pipe_input() as entrada, patch.object(sys, "platform", plataforma):
        entrada.send_text("".join(teclas))
        # Sem mais teclas, a pergunta seguinte dá EOFError em vez de travar a suíte.
        entrada.close()
        with create_app_session(input=entrada, output=DummyOutput()):
            try:
                main([COMANDO_CONFIGURAR])
            except SystemExit as e:
                assert isinstance(e.code, int)
                return e.code
    return SAIDA_OK


def test_configurar_grava_so_as_duas_chaves(cen):
    assert _rodar(CIMA, ENTER, CIMA, ENTER, ENTER) == SAIDA_OK
    assert cen.config.read_text() == f"{cen.original}\n{COM_FONTES}"


@pytest.mark.parametrize(
    ("teclas", "fontes"),
    [
        ((ENTER, ENTER, ENTER), {Tabela.TAREFAS: JIRA, Tabela.PRS: BITBUCKET}),
        ((BAIXO, ENTER, BAIXO, ENTER, ENTER), {}),
    ],
    ids=["mantem", "lista-manual-e-nenhuma"],
)
def test_reconfigurar_parte_do_valor_atual(cen, teclas, fontes):
    cen.escrever(f"{cen.original}\n{COM_FONTES}")
    assert _rodar(*teclas) == SAIDA_OK
    assert cen.fontes() == fontes
    if fontes:
        assert cen.config.read_text() == cen.original


def test_embutido_nao_instalado_instala_pelo_repo_do_motor(cen):
    cen.pontos[GrupoPlugin.TAREFAS] = {}
    cen.pacote = {GrupoPlugin.TAREFAS: {JIRA: FONTE}}
    assert _rodar(CIMA, ENTER, ENTER, ENTER) == SAIDA_OK
    assert cen.instalados == [f"git+{URL_MOTOR}#subdirectory=plugins/{JIRA}"]
    assert cen.fontes() == {Tabela.TAREFAS: JIRA}


@pytest.mark.parametrize("saida", [SAIDA_OK, CodigoSaida.ERRO])
def test_instalar_plugin_chama_o_plugin_instalar_do_motor(monkeypatch, saida):
    chamados: list[list[str]] = []

    def rodar(cmd: list[str], check: bool) -> subprocess.CompletedProcess[str]:
        chamados.append(cmd)
        return subprocess.CompletedProcess(cmd, saida)

    monkeypatch.setattr(subprocess, "run", rodar)
    assert assistente.instalar_plugin(URL_OUTRO) is (saida == SAIDA_OK)
    assert chamados == [
        [
            sys.executable,
            *assistente.ARGS_PYTHON,
            assistente.MODULO_MOTOR,
            COMANDO_PLUGIN,
            AcaoPlugin.INSTALAR,
            URL_OUTRO,
        ]
    ]


@pytest.mark.parametrize("tipo", list(OrigemOutro))
def test_outro_plugin_instala_e_escolhe_a_fonte(cen, tmp_path, tipo):
    cen.pacote = {GrupoPlugin.TAREFAS: {FONTE_NOVA: FONTE}}
    if tipo is OrigemOutro.CAMINHO:
        origem, escolha_tipo = str(tmp_path / "repo"), ENTER
    else:
        origem, escolha_tipo = URL_OUTRO, BAIXO + ENTER
    teclas = (BAIXO, ENTER, escolha_tipo, origem, ENTER, ENTER, ENTER)
    assert _rodar(*teclas) == SAIDA_OK
    assert cen.instalados == [origem]
    assert cen.fontes() == {Tabela.TAREFAS: FONTE_NOVA}


def test_outro_plugin_com_varias_fontes_pergunta_qual(cen):
    cen.pacote = {GrupoPlugin.TAREFAS: {FONTE_NOVA: FONTE, OUTRA_FONTE: FONTE}}
    teclas = (BAIXO, ENTER, BAIXO, ENTER, URL_OUTRO, ENTER, BAIXO, ENTER)
    assert _rodar(*teclas, ENTER, ENTER) == SAIDA_OK
    assert cen.fontes() == {Tabela.TAREFAS: OUTRA_FONTE}


def test_outro_plugin_sem_fonte_avisa_e_volta(cen, capsys):
    cen.pacote = {GrupoPlugin.PRS: {HOST_NOVO: HOST}}
    outro = (BAIXO, ENTER, BAIXO, ENTER, URL_OUTRO, ENTER)
    assert _rodar(*outro, ENTER, ENTER, ENTER) == SAIDA_OK
    assert "não fornece fonte de tarefas" in capsys.readouterr().out
    assert cen.instalados == [URL_OUTRO]
    assert cen.config.read_text() == cen.original


def test_ctrl_c_nao_grava(cen):
    cen.pontos[GrupoPlugin.TAREFAS] = {}
    cen.pacote = {GrupoPlugin.TAREFAS: {JIRA: FONTE}}
    assert _rodar(CIMA, ENTER, CTRL_C) == CodigoSaida.INTERROMPIDO
    assert cen.config.read_text() == cen.original
    assert cen.comandos == []
    assert len(cen.instalados) == 1


def test_sem_terminal_recusa_sem_mudar_nada(cen, monkeypatch, capsys, caplog):
    monkeypatch.setattr(assistente, "_terminal", lambda: False)
    assert _rodar() == CodigoSaida.ERRO
    assert "interativo" in capsys.readouterr().err + caplog.text
    assert cen.config.read_text() == cen.original
    assert cen.instalados == []


@pytest.mark.parametrize(
    ("ligado", "tecla", "comandos"),
    [(False, SIM, LIGAR), (True, NAO, DESLIGAR)],
    ids=["liga", "desliga"],
)
def test_ligar_e_desligar_no_login(cen, ligado, tecla, comandos):
    if ligado:
        cen.unit().parent.mkdir(parents=True)
        cen.unit().write_text("")
    assert _rodar(ENTER, ENTER, tecla) == SAIDA_OK
    assert cen.comandos == comandos
    assert cen.unit().exists() is not ligado


@pytest.mark.parametrize(
    ("com_config", "ligado", "comandos"),
    [(False, False, LIGAR), (True, False, []), (True, True, [])],
    ids=["primeira-vez-liga", "desligado-fica", "ligado-fica"],
)
def test_padrao_do_login(cen, com_config, ligado, comandos):
    if not com_config:
        cen.config.unlink()
    if ligado:
        cen.unit().parent.mkdir(parents=True)
        cen.unit().write_text("")
    assert _rodar(ENTER, ENTER, ENTER) == SAIDA_OK
    assert cen.comandos == comandos
    assert cen.unit().exists() is (ligado or not com_config)


def test_windows_nao_pergunta_o_login(cen):
    assert _rodar(ENTER, ENTER, plataforma=WINDOWS) == SAIDA_OK
    assert cen.comandos == []


@pytest.mark.parametrize(
    ("serve", "grafico", "teclas", "abertos", "no_stdout"),
    [
        (True, True, (SIM,), [assistente.ENDERECO_WEB], ""),
        (True, False, (), [], assistente.ENDERECO_WEB),
        (False, True, (), [], f"{EXECUTAVEL} {COMANDO_SERVE}"),
    ],
    ids=["abre", "sem-grafico", "sem-serve"],
)
def test_fechamento(
    cen, monkeypatch, capsys, serve, grafico, teclas, abertos, no_stdout
):
    monkeypatch.setattr(assistente, "_serve_responde", lambda esperar: serve)
    monkeypatch.setattr(assistente, "_ambiente_grafico", lambda: grafico)
    assert _rodar(ENTER, ENTER, ENTER, *teclas) == SAIDA_OK
    saida = capsys.readouterr().out
    assert cen.abertos == abertos
    assert no_stdout in saida
    assert Peca.DAEMON in saida
