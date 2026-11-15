"""`monitor-versoes configurar`: fontes, serviço de login e o caminho até a web."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
import questionary
from prompt_toolkit.key_binding import (
    KeyBindings,
    KeyPressEvent,
    merge_key_bindings,
)
from prompt_toolkit.keys import Keys

from motor import agendador, instalacao, plugins, servico
from motor.agendador import Sistema
from motor.cli_instalacao import COMANDO_PLUGIN, AcaoPlugin
from motor.config import Chave, Tabela, caminho_config_global
from motor.config_edicao import (
    AcaoAlteracao,
    Alteracao,
    GrupoPlugin,
    gravar,
    ler_para_edicao,
)
from motor.daemon import PORTA_PADRAO
from motor.errors import CodigoSaida, ErroDeEntrada, MotorError
from motor.instalacao import PARAMETRO_SUBDIRETORIO, PREFIXO_GIT

ENDERECO_WEB = f"http://127.0.0.1:{PORTA_PADRAO}/"
PRAZO_SUBIDA_S = 10
INTERVALO_SONDA_S = 0.5
TIMEOUT_SONDA_S = 2
ARGS_PYTHON = ("-P", "-m")
MODULO_MOTOR = "motor"
PREFIXOS_GIT = ("https://", "git@")
VAR_SSH = "SSH_CONNECTION"
VARS_DISPLAY = ("DISPLAY", "WAYLAND_DISPLAY")
TECLAS_SIM = ("s", "S")
COR_VERDE = "\x1b[32m"
COR_VERMELHA = "\x1b[31m"
SEM_COR = "\x1b[0m"


@dataclass(frozen=True)
class Embutido:
    rotulo: str
    nome: str
    pasta: str | None  # None = vem no núcleo


EMBUTIDOS: dict[GrupoPlugin, tuple[Embutido, ...]] = {
    GrupoPlugin.TAREFAS: (Embutido("Jira", "jira", "plugins/jira"),),
    GrupoPlugin.PRS: (Embutido("Bitbucket", "bitbucket", None),),
}


class Rotulo(StrEnum):
    LISTA_MANUAL = "Lista manual"
    NENHUMA = "Nenhuma (só o grep na principal)"
    OUTRO = "Outro plugin (caminho ou URL)"


class OrigemOutro(StrEnum):
    CAMINHO = "Caminho no disco"
    URL = "URL de repositório git"


class Marca(StrEnum):
    OK = "✔"
    FALHA = "✖"


_COR = {Marca.OK: COR_VERDE, Marca.FALHA: COR_VERMELHA}


@dataclass(frozen=True)
class Pergunta:
    grupo: GrupoPlugin
    tabela: Tabela
    texto: str
    tipo: str
    sem_fonte: Rotulo


PERGUNTAS = (
    Pergunta(
        GrupoPlugin.TAREFAS,
        Tabela.TAREFAS,
        "Fonte de tarefas",
        "fonte de tarefas",
        Rotulo.LISTA_MANUAL,
    ),
    Pergunta(
        GrupoPlugin.PRS,
        Tabela.PRS,
        "Fonte de commits (host de PR)",
        "host de PR",
        Rotulo.NENHUMA,
    ),
)


def _terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _serve_responde(esperar: bool) -> bool:
    limite = time.monotonic() + (PRAZO_SUBIDA_S if esperar else 0)
    while True:
        try:
            if httpx.get(ENDERECO_WEB, timeout=TIMEOUT_SONDA_S).is_success:
                return True
        except httpx.HTTPError:
            pass
        if time.monotonic() >= limite:
            return False
        time.sleep(INTERVALO_SONDA_S)


def _ambiente_grafico() -> bool:
    if sys.platform == Sistema.MACOS:
        return VAR_SSH not in os.environ
    return any(os.environ.get(v) for v in VARS_DISPLAY)


def instalar_plugin(origem: str) -> bool:
    cmd = [
        sys.executable,
        *ARGS_PYTHON,
        MODULO_MOTOR,
        COMANDO_PLUGIN,
        AcaoPlugin.INSTALAR,
        origem,
    ]
    return subprocess.run(cmd, check=False).returncode == 0


def marcar(marca: Marca, texto: str) -> None:
    simbolo = f"{_COR[marca]}{marca}{SEM_COR}" if sys.stdout.isatty() else marca
    print(f"{simbolo} {texto}")


def perguntar(pergunta: questionary.Question, sim: bool = False) -> Any:
    """Esc interrompe como o Ctrl+C; com `sim`, `s`/`S` confirmam."""
    teclas = KeyBindings()

    @teclas.add(Keys.Escape, eager=True)
    def _esc(evento: KeyPressEvent) -> None:
        evento.app.exit(exception=KeyboardInterrupt())

    if sim:
        for tecla in TECLAS_SIM:
            teclas.add(tecla)(lambda evento: evento.app.exit(result=True))
    app = pergunta.application
    app.key_bindings = merge_key_bindings([app.key_bindings or KeyBindings(), teclas])
    return pergunta.unsafe_ask()


def confirmar(texto: str, padrao: bool) -> bool:
    instrucao = "(S/n)" if padrao else "(s/N)"
    q = questionary.confirm(texto, default=padrao, instruction=instrucao)
    return bool(perguntar(q, sim=True))


def _fontes(grupo: GrupoPlugin) -> set[str]:
    importlib.invalidate_caches()
    return set(plugins.nomes_instalados(grupo))


def _origem_embutido(embutido: Embutido, url_motor: str | None) -> str | None:
    if embutido.pasta is None or url_motor is None:
        return None
    # Sem @ref: o `plugin instalar` fixa o plugin do repo do motor na tag dele.
    return f"{PREFIXO_GIT}{url_motor}#{PARAMETRO_SUBDIRETORIO}={embutido.pasta}"


def _opcoes(
    p: Pergunta, fontes: set[str], atual: str | None, url_motor: str | None
) -> list[questionary.Choice]:
    embutidos = [
        e
        for e in EMBUTIDOS[p.grupo]
        if e.nome in fontes or _origem_embutido(e, url_motor)
    ]
    nomes = {e.nome for e in embutidos}
    outros = sorted(fontes - nomes)
    if atual is not None and atual not in nomes | fontes:
        outros.append(atual)
    return [
        *(questionary.Choice(e.rotulo, e.nome) for e in embutidos),
        *(questionary.Choice(nome, nome) for nome in outros),
        questionary.Choice(p.sem_fonte, p.sem_fonte),
        questionary.Choice(Rotulo.OUTRO, Rotulo.OUTRO),
    ]


def _pedir_origem() -> str:
    tipo = perguntar(questionary.select("De onde vem o plugin?", list(OrigemOutro)))
    if tipo == OrigemOutro.CAMINHO:
        caminho = perguntar(
            questionary.path(
                "Pasta do plugin:",
                only_directories=True,
                validate=lambda t: Path(t).expanduser().is_dir() or "não é uma pasta",
            )
        )
        # Absoluto: o `plugin instalar` leria um nome solto como pacote publicado.
        return str(Path(caminho).expanduser().resolve())
    return str(
        perguntar(
            questionary.text(
                "URL do repositório (https://… ou git@…, @<ref> opcional):",
                validate=lambda t: (
                    t.startswith(PREFIXOS_GIT) or "use https://… ou git@…"
                ),
            )
        )
    )


def _outro_plugin(p: Pergunta, antes: set[str]) -> str | None:
    if not instalar_plugin(_pedir_origem()):
        marcar(Marca.FALHA, "a instalação do plugin falhou (o erro está acima)")
        return None
    novas = sorted(_fontes(p.grupo) - antes)
    if not novas:
        marcar(Marca.FALHA, f"o pacote não fornece {p.tipo}; escolha outra opção")
        return None
    if len(novas) == 1:
        return novas[0]
    return str(perguntar(questionary.select(f"Qual {p.tipo} usar?", novas)))


def _instalar_embutido(p: Pergunta, embutido: Embutido, url_motor: str | None) -> bool:
    origem = _origem_embutido(embutido, url_motor)
    if origem is None or not instalar_plugin(origem):
        marcar(Marca.FALHA, f"não foi possível instalar o {embutido.rotulo}")
        return False
    return embutido.nome in _fontes(p.grupo)


def _escolher(p: Pergunta, atual: str | None, url_motor: str | None) -> str | None:
    while True:
        fontes = _fontes(p.grupo)
        opcoes = _opcoes(p, fontes, atual, url_motor)
        resposta = str(
            perguntar(questionary.select(p.texto, opcoes, default=atual or p.sem_fonte))
        )
        if resposta == p.sem_fonte:
            return None
        embutido = next((e for e in EMBUTIDOS[p.grupo] if e.nome == resposta), None)
        if resposta == Rotulo.OUTRO:
            escolhida = _outro_plugin(p, fontes)
        elif (
            resposta in fontes
            or embutido is None
            or _instalar_embutido(p, embutido, url_motor)
        ):
            escolhida = resposta
        else:
            escolhida = None
        if escolhida is not None:
            return escolhida


def _quer_login(home: Path) -> bool | None:
    try:
        agendador.sistema_atual()
    except ErroDeEntrada:
        return None
    padrao = servico.ligado(home) or not Path(caminho_config_global()).exists()
    return confirmar("Iniciar o `serve` no login?", padrao)


def _alteracoes(
    atuais: dict[Tabela, str | None], escolhas: dict[Tabela, str | None]
) -> list[Alteracao]:
    return [
        Alteracao(AcaoAlteracao.REMOVER, tabela=t, chave=Chave.FONTE)
        if valor is None
        else Alteracao(AcaoAlteracao.DEFINIR, tabela=t, chave=Chave.FONTE, valor=valor)
        for t, valor in escolhas.items()
        if valor != atuais[t]
    ]


def _aplicar_login(home: Path, quer: bool | None) -> None:
    if quer is None or quer == servico.ligado(home):
        return
    sistema = agendador.sistema_atual()
    try:
        if quer:
            servico.ligar(
                sistema,
                home,
                servico.executavel_motor(),
                agendador.rodar_comando_do_sistema,
            )
        else:
            servico.desligar(sistema, home, agendador.rodar_comando_do_sistema)
    except MotorError as e:
        marcar(Marca.FALHA, f"serviço de login: {e}")
        return
    marcar(Marca.OK, f"serviço de login {'ligado' if quer else 'desligado'}")


def _fechar(imprimir_diagnostico: Callable[[], object], home: Path) -> None:
    imprimir_diagnostico()
    if not _serve_responde(esperar=servico.ligado(home)):
        print(
            f"Para terminar a configuração na web, rode `{servico.EXECUTAVEL} serve`."
        )
    elif not _ambiente_grafico():
        print(f"Configuração na web: {ENDERECO_WEB} (→ Configuração)")
    elif confirmar("Abrir a configuração da web no navegador?", True):
        webbrowser.open(ENDERECO_WEB)


def configurar(imprimir_diagnostico: Callable[[], object]) -> None:
    if not _terminal():
        raise ErroDeEntrada(
            "o configurar é interativo; rode-o num terminal ou edite o config.toml"
        )
    lido = ler_para_edicao()
    atuais: dict[Tabela, str | None] = {p.tabela: None for p in PERGUNTAS}
    for v in lido.valores:
        if v.repo is None and v.tabela in atuais and v.chave == Chave.FONTE:
            atuais[Tabela(v.tabela)] = str(v.valor)
    home = Path.home()
    url_motor = instalacao.url_do_motor()
    try:
        escolhas = {
            p.tabela: _escolher(p, atuais[p.tabela], url_motor) for p in PERGUNTAS
        }
        login = _quer_login(home)
    except KeyboardInterrupt:
        marcar(Marca.FALHA, "interrompido: nada foi gravado")
        sys.exit(CodigoSaida.INTERROMPIDO)
    alteracoes = _alteracoes(atuais, escolhas)
    if alteracoes:
        gravar(alteracoes, lido.versao)
        marcar(Marca.OK, f"fontes gravadas em {caminho_config_global()}")
    _aplicar_login(home, login)
    try:
        _fechar(imprimir_diagnostico, home)
    except KeyboardInterrupt:
        sys.exit(CodigoSaida.INTERROMPIDO)
