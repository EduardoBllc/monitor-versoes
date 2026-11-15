from __future__ import annotations

import errno
import os
import shutil
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
from motor.__main__ import COMANDO_DESINSTALAR, COMANDO_SERVE, main
from motor.agendador import ARQUIVO_TIMER, FLAG_AGORA, SYSTEMCTL, Acao, Sistema
from motor.assistente import SUFIXOS_SQLITE, Marca, OrigemOutro, Situacao
from motor.cli_instalacao import COMANDO_PLUGIN, AcaoPlugin
from motor.config import (
    VAR_XDG_CACHE_HOME,
    VAR_XDG_CONFIG_HOME,
    Chave,
    Tabela,
    VarAmbiente,
    caminho_config_global,
    diretorio_cache,
    diretorio_dados,
)
from motor.config_edicao import GrupoPlugin
from motor.diagnostico import Estado, Peca
from motor.errors import CodigoSaida
from motor.instalacao import PARAMETRO_SUBDIRETORIO, PASTA_PLUGINS, PREFIXO_GIT
from motor.servico import ARQUIVO_SERVICE, COMANDO_CONFIGURAR, EXECUTAVEL

BAIXO = "\x1b[B"
CIMA = "\x1b[A"
ENTER = "\r"
CTRL_C = "\x03"
SIM = "s"
NAO = "n"
MOTIVO_NEGADO = "sem permissão"

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


def _rodar(
    *teclas: str, plataforma: str = Sistema.LINUX, comando: str = COMANDO_CONFIGURAR
) -> int:
    with create_pipe_input() as entrada, patch.object(sys, "platform", plataforma):
        entrada.send_text("".join(teclas))
        # Sem mais teclas, a pergunta seguinte dá EOFError em vez de travar a suíte.
        entrada.close()
        with create_app_session(input=entrada, output=DummyOutput()):
            try:
                main([comando])
            except SystemExit as e:
                assert isinstance(e.code, int)
                return e.code
    return CodigoSaida.OK


def test_configurar_grava_so_as_duas_chaves(cen):
    assert _rodar(CIMA, ENTER, CIMA, ENTER, ENTER) == CodigoSaida.OK
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
    assert _rodar(*teclas) == CodigoSaida.OK
    assert cen.fontes() == fontes
    if fontes:
        assert cen.config.read_text() == cen.original


def test_embutido_nao_instalado_instala_pelo_repo_do_motor(cen):
    cen.pontos[GrupoPlugin.TAREFAS] = {}
    cen.pacote = {GrupoPlugin.TAREFAS: {JIRA: FONTE}}
    assert _rodar(CIMA, ENTER, ENTER, ENTER) == CodigoSaida.OK
    assert cen.instalados == [
        f"{PREFIXO_GIT}{URL_MOTOR}#{PARAMETRO_SUBDIRETORIO}={PASTA_PLUGINS}{JIRA}"
    ]
    assert cen.fontes() == {Tabela.TAREFAS: JIRA}


def test_embutido_instalado_sem_a_fonte_avisa_e_volta(cen, capsys):
    cen.pontos[GrupoPlugin.TAREFAS] = {}
    assert _rodar(CIMA, ENTER, ENTER, ENTER, ENTER) == CodigoSaida.OK
    assert f"não registrou a fonte {JIRA}" in capsys.readouterr().out
    assert cen.config.read_text() == cen.original


@pytest.mark.parametrize("saida", [CodigoSaida.OK, CodigoSaida.ERRO])
def test_instalar_plugin_chama_o_plugin_instalar_do_motor(monkeypatch, saida):
    chamados: list[list[str]] = []

    def rodar(cmd: list[str], check: bool) -> subprocess.CompletedProcess[str]:
        chamados.append(cmd)
        return subprocess.CompletedProcess(cmd, saida)

    monkeypatch.setattr(subprocess, "run", rodar)
    assert assistente.instalar_plugin(URL_OUTRO) is (saida == CodigoSaida.OK)
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
    assert _rodar(*teclas) == CodigoSaida.OK
    assert cen.instalados == [origem]
    assert cen.fontes() == {Tabela.TAREFAS: FONTE_NOVA}


def test_outro_plugin_com_varias_fontes_pergunta_qual(cen):
    cen.pacote = {GrupoPlugin.TAREFAS: {FONTE_NOVA: FONTE, OUTRA_FONTE: FONTE}}
    teclas = (BAIXO, ENTER, BAIXO, ENTER, URL_OUTRO, ENTER, BAIXO, ENTER)
    assert _rodar(*teclas, ENTER, ENTER) == CodigoSaida.OK
    assert cen.fontes() == {Tabela.TAREFAS: OUTRA_FONTE}


def test_outro_plugin_sem_fonte_avisa_e_volta(cen, capsys):
    cen.pacote = {GrupoPlugin.PRS: {HOST_NOVO: HOST}}
    outro = (BAIXO, ENTER, BAIXO, ENTER, URL_OUTRO, ENTER)
    assert _rodar(*outro, ENTER, ENTER, ENTER) == CodigoSaida.OK
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


def test_sem_terminal_recusa_sem_mudar_nada(cen, monkeypatch, caplog):
    monkeypatch.setattr(assistente, "_terminal", lambda: False)
    assert _rodar() == CodigoSaida.ERRO
    assert "interativo" in caplog.text
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
    assert _rodar(ENTER, ENTER, tecla) == CodigoSaida.OK
    assert cen.comandos == comandos
    assert cen.unit().exists() is not ligado


@pytest.mark.parametrize(
    ("com_config", "ligado", "comandos"),
    [(False, False, LIGAR), (True, False, []), (True, True, LIGAR)],
    ids=["primeira-vez-liga", "desligado-fica", "ligado-religa"],
)
def test_padrao_do_login(cen, com_config, ligado, comandos):
    if not com_config:
        cen.config.unlink()
    if ligado:
        cen.unit().parent.mkdir(parents=True)
        cen.unit().write_text("")
    assert _rodar(ENTER, ENTER, ENTER) == CodigoSaida.OK
    assert cen.comandos == comandos
    assert cen.unit().exists() is (ligado or not com_config)


def test_windows_nao_pergunta_o_login(cen):
    assert _rodar(ENTER, ENTER, plataforma=WINDOWS) == CodigoSaida.OK
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
    assert _rodar(ENTER, ENTER, ENTER, *teclas) == CodigoSaida.OK
    saida = capsys.readouterr().out
    assert cen.abertos == abertos
    assert no_stdout in saida
    assert Peca.DAEMON in saida


def test_configurar_no_primeiro_uso_nao_acusa_falta_de_migracao(cen, capsys):
    assert _rodar(ENTER, ENTER, ENTER) == CodigoSaida.OK
    assert f"{Estado.FALHA.value}  {Peca.MIGRACAO}" not in capsys.readouterr().out


def _dados_do_usuario(tmp_path, monkeypatch, cache_base=None) -> list[Path]:
    monkeypatch.setenv(
        VAR_XDG_CACHE_HOME, str(cache_base or tmp_path / "cache-isolado")
    )
    banco = Path(os.environ[VarAmbiente.DATABASE_SQLITE_PATH])
    pastas = [
        Path(caminho_config_global()).parent,
        Path(diretorio_dados()),
        Path(diretorio_cache()),
    ]
    for pasta in pastas:
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "dado").write_text("")
    banco.write_text("")
    for sufixo in SUFIXOS_SQLITE:
        Path(f"{banco}{sufixo}").write_text("")
    return [*pastas, *(Path(f"{banco}{s}") for s in SUFIXOS_SQLITE)]


def test_desinstalar_remove_servico_e_timer_antigo(cen, tmp_path, monkeypatch):
    dados = _dados_do_usuario(tmp_path, monkeypatch)
    cen.unit().parent.mkdir(parents=True)
    cen.unit().write_text("")
    for arquivo in agendador.caminhos(Sistema.LINUX, Path.home()):
        arquivo.write_text("")

    assert _rodar(ENTER, comando=COMANDO_DESINSTALAR) == CodigoSaida.OK

    assert not cen.unit().exists()
    assert not any(a.exists() for a in agendador.caminhos(Sistema.LINUX, Path.home()))
    assert cen.comandos == [
        *DESLIGAR,
        [*SYSTEMCTL, Acao.DISABLE, FLAG_AGORA, ARQUIVO_TIMER],
        [*SYSTEMCTL, Acao.DAEMON_RELOAD],
    ]
    assert all(d.exists() for d in dados)


@pytest.mark.parametrize(
    ("teclas", "terminal", "apagou"),
    [((SIM,), True, True), ((ENTER,), True, False), ((), False, False)],
    ids=["sim", "enter-mantem", "sem-terminal"],
)
def test_desinstalar_apaga_dados_so_com_sim(
    cen, tmp_path, monkeypatch, capsys, teclas, terminal, apagou
):
    dados = _dados_do_usuario(tmp_path, monkeypatch)
    monkeypatch.setattr(assistente, "_terminal", lambda: terminal)

    assert _rodar(*teclas, comando=COMANDO_DESINSTALAR) == CodigoSaida.OK

    assert all(d.exists() is not apagou for d in dados)
    assert _linhas_do_relatorio(capsys) == {
        f"{Situacao.REMOVIDO if apagou else Situacao.MANTIDO}: {d}" for d in dados
    }


def _linhas_do_relatorio(capsys) -> set[str]:
    prefixos = tuple(f"{s}: " for s in Situacao)
    return {
        linha
        for linha in capsys.readouterr().out.splitlines()
        if linha.startswith(prefixos)
    }


def test_desinstalar_falha_ao_apagar_mantem_e_explica(
    cen, tmp_path, monkeypatch, capsys
):
    dados = _dados_do_usuario(tmp_path, monkeypatch)
    cache = Path(diretorio_cache())
    rmtree = shutil.rmtree

    def rmtree_negado(caminho, *a, **k):
        if Path(caminho) == cache:
            raise PermissionError(errno.EACCES, MOTIVO_NEGADO)
        rmtree(caminho, *a, **k)

    monkeypatch.setattr(shutil, "rmtree", rmtree_negado)

    assert _rodar(SIM, comando=COMANDO_DESINSTALAR) == CodigoSaida.OK

    assert cache.exists()
    assert not any(d.exists() for d in dados if d != cache)
    saida = capsys.readouterr()
    assert f"{Situacao.MANTIDO}: {cache}" in saida.out
    assert MOTIVO_NEGADO in saida.out


def test_desinstalar_banco_relativo_dentro_de_pasta_listada_aparece_uma_vez(
    cen, tmp_path, monkeypatch, capsys
):
    dados = _dados_do_usuario(tmp_path, monkeypatch)
    monkeypatch.chdir(Path(diretorio_cache()).parent)
    relativo = Path(diretorio_cache()).name + "/estado.db"
    (Path(diretorio_cache()) / "estado.db").write_text("")
    monkeypatch.setenv(VarAmbiente.DATABASE_SQLITE_PATH, relativo)

    assert _rodar(ENTER, comando=COMANDO_DESINSTALAR) == CodigoSaida.OK

    listados = {
        Path(linha.split(": ", 1)[1]).resolve()
        for linha in _linhas_do_relatorio(capsys)
    }
    assert listados == {d.resolve() for d in dados[:3]}


def test_desinstalar_sem_nada_diz_que_nao_ha_o_que_remover(cen, capsys):
    shutil.rmtree(cen.config.parent)

    assert _rodar(comando=COMANDO_DESINSTALAR) == CodigoSaida.OK

    assert "Nenhum dado" in capsys.readouterr().out


def _trocar_por_link(caminho: Path, alvo: Path) -> None:
    caminho.rename(alvo)
    caminho.symlink_to(alvo)


@pytest.mark.parametrize("o_que", ["pasta", "banco"])
def test_desinstalar_link_remove_so_o_link(cen, tmp_path, monkeypatch, capsys, o_que):
    dados = _dados_do_usuario(tmp_path, monkeypatch)
    original = dados[1] if o_que == "pasta" else dados[3]
    alvo = tmp_path / "alvo-fora"
    _trocar_por_link(original, alvo)

    assert _rodar(SIM, comando=COMANDO_DESINSTALAR) == CodigoSaida.OK

    assert not original.is_symlink()
    assert alvo.exists()
    assert not dados[0].exists()
    if o_que == "pasta":
        assert (alvo / "dado").exists()
    assert f"{original} → {alvo}, só o link é removido" in capsys.readouterr().out


def test_desinstalar_pasta_dentro_de_outra_nao_e_listada_a_parte(
    cen, tmp_path, monkeypatch, capsys
):
    dados = _dados_do_usuario(tmp_path, monkeypatch, cache_base=Path(diretorio_dados()))

    assert _rodar(SIM, comando=COMANDO_DESINSTALAR) == CodigoSaida.OK

    listados = {linha.split(": ", 1)[1] for linha in _linhas_do_relatorio(capsys)}
    assert str(Path(diretorio_cache())) not in listados
    assert not any(d.exists() for d in dados)


def test_desinstalar_banco_dentro_de_pasta_link_fica_com_o_alvo(
    cen, tmp_path, monkeypatch, capsys
):
    dados = _dados_do_usuario(tmp_path, monkeypatch)
    alvo = tmp_path / "alvo-fora"
    _trocar_por_link(dados[1], alvo)
    banco = dados[1] / "estado.db"
    banco.write_text("")
    monkeypatch.setenv(VarAmbiente.DATABASE_SQLITE_PATH, str(banco))

    assert _rodar(SIM, comando=COMANDO_DESINSTALAR) == CodigoSaida.OK

    assert not dados[1].is_symlink()
    assert (alvo / "estado.db").exists()
    assert Marca.FALHA not in capsys.readouterr().out


def test_desinstalar_banco_que_e_diretorio_nao_passa_por_rmtree(
    cen, tmp_path, monkeypatch, capsys
):
    banco = tmp_path / "banco-dir.db"
    (banco / "dentro").mkdir(parents=True)
    monkeypatch.setenv(VarAmbiente.DATABASE_SQLITE_PATH, str(banco))

    assert _rodar(SIM, comando=COMANDO_DESINSTALAR) == CodigoSaida.OK

    assert (banco / "dentro").exists()
    saida = capsys.readouterr().out
    assert Marca.FALHA in saida
    assert f"{Situacao.MANTIDO}: {banco}" in saida
