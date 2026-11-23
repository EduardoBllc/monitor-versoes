"""`monitor-versoes configurar`: fontes, início do daemon no login e o caminho até a web."""

from __future__ import annotations

import contextlib
import importlib
import os
import shutil
import subprocess
import sys
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import questionary
from prompt_toolkit.key_binding import (
    KeyBindings,
    KeyPressEvent,
    merge_key_bindings,
)
from prompt_toolkit.keys import Keys

from motor import agendador, console, instalacao, plugins, servico
from motor.agendador import Sistema
from motor.cli_daemon import COMANDO_DAEMON, AcaoDaemon
from motor.cli_instalacao import COMANDO_PLUGIN, AcaoPlugin
from motor.config import (
    Chave,
    Tabela,
    VarAmbiente,
    caminho_config_global,
    diretorio_cache,
    diretorio_dados,
    nunca_iniciar_login,
    porta_daemon,
)
from motor.config_edicao import (
    AcaoAlteracao,
    Alteracao,
    GrupoPlugin,
    gravar,
    gravar_nunca_iniciar_login,
    ler_para_edicao,
)
from motor.errors import CodigoSaida, ErroDeEntrada, MotorError
from motor.instalacao import PARAMETRO_SUBDIRETORIO, PREFIXO_GIT

ARGS_PYTHON = ("-P", "-m")
MODULO_MOTOR = "motor"
PREFIXOS_GIT = ("https://", "git@")
VAR_SSH = "SSH_CONNECTION"
VARS_DISPLAY = ("DISPLAY", "WAYLAND_DISPLAY")
TECLAS_SIM = ("s", "S")
COR_VERDE = "\x1b[32m"
COR_VERMELHA = "\x1b[31m"
SEM_COR = "\x1b[0m"
SUFIXOS_SQLITE = ("", "-wal", "-shm")


@dataclass(frozen=True)
class Embutido:
    rotulo: str
    nome: str
    pasta: str


EMBUTIDOS: dict[GrupoPlugin, tuple[Embutido, ...]] = {
    GrupoPlugin.TAREFAS: (
        Embutido("Jira", "jira", "plugins/jira"),
        Embutido("GitHub Issues", "github", "plugins/github"),
        Embutido("GitLab Issues", "gitlab", "plugins/gitlab"),
    ),
    GrupoPlugin.PRS: (
        Embutido("Bitbucket", "bitbucket", "plugins/bitbucket"),
        Embutido("GitHub", "github", "plugins/github"),
        Embutido("GitLab", "gitlab", "plugins/gitlab"),
    ),
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


class Situacao(StrEnum):
    REMOVIDO = "removido"
    MANTIDO = "mantido"


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


def terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _ambiente_grafico() -> bool:
    if sys.platform == Sistema.WINDOWS:
        return True
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
    return (
        subprocess.run(
            cmd, check=False, creationflags=console.FLAGS_SEM_JANELA
        ).returncode
        == CodigoSaida.OK
    )


def _para_depois_de_instalar() -> bool:
    return sys.platform == Sistema.WINDOWS


def _terminar_se_windows() -> None:
    """No Windows o plugin é instalado por um ajudante que reinstala o motor."""
    if not _para_depois_de_instalar():
        return
    marcar(Marca.OK, "plugin entregue à reinstalação; nada foi gravado")
    print(
        f"Quando ela terminar, rode `{servico.EXECUTAVEL} {servico.COMANDO_CONFIGURAR}` de novo."
    )
    sys.exit(CodigoSaida.OK)


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
    if url_motor is None:
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
    _terminar_se_windows()
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
    _terminar_se_windows()
    if embutido.nome not in _fontes(p.grupo):
        marcar(
            Marca.FALHA,
            f"o {embutido.rotulo} foi instalado, mas não registrou a fonte "
            f"{embutido.nome}",
        )
        return False
    return True


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


def _login_ligado(home: Path) -> bool:
    try:
        sistema = agendador.sistema_atual()
    except ErroDeEntrada:
        return False
    return servico.login_ligado(sistema, home, servico.consultar_do_sistema)


def _quer_login(home: Path) -> bool | None:
    try:
        sistema = agendador.sistema_atual()
    except ErroDeEntrada:
        return None
    # Quem atualizou pode ter sido o motor antigo, que não migra: o padrão e o Sim/Não valem para a peça nova.
    try:
        servico.migrar_legado(
            sistema,
            home,
            servico.executavel_servico(),
            agendador.rodar_comando_do_sistema,
            servico.consultar_do_sistema,
        )
    except MotorError as e:
        marcar(Marca.FALHA, f"não deu para trocar o serviço antigo pelo daemon: {e}")
    padrao = _login_ligado(home) or not Path(caminho_config_global()).exists()
    return confirmar("Iniciar o daemon no login?", padrao and not nunca_iniciar_login())


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
    # Sim sempre religa: repara um serviço parado e atualiza o caminho do executável.
    if quer is None or (not quer and not _login_ligado(home)):
        return
    sistema = agendador.sistema_atual()
    rodar = agendador.rodar_comando_do_sistema
    try:
        if quer:
            servico.ligar_login(sistema, home, servico.executavel_servico(), rodar)
            servico.subir(sistema, home, servico.executavel_servico(), rodar)
            if nunca_iniciar_login():
                gravar_nunca_iniciar_login(False)
        else:
            servico.desligar_login(sistema, home, rodar)
    except MotorError as e:
        marcar(Marca.FALHA, f"início no login: {e}")
        return
    marcar(
        Marca.OK,
        "daemon rodando e iniciando no login" if quer else "início no login desligado",
    )


def _fechar(imprimir_diagnostico: Callable[[], object], home: Path) -> None:
    imprimir_diagnostico()
    porta = porta_daemon()
    if not servico.serve_responde(porta, esperar=_login_ligado(home)):
        iniciar = f"{servico.EXECUTAVEL} {COMANDO_DAEMON} {AcaoDaemon.INICIAR}"
        print(f"Para terminar a configuração na web, rode `{iniciar}`.")
    elif not _ambiente_grafico():
        print(f"Configuração na web: {servico.endereco_web(porta)} (→ Configuração)")
    elif confirmar("Abrir a configuração da web no navegador?", True):
        webbrowser.open(servico.endereco_web(porta))


def configurar(imprimir_diagnostico: Callable[[], object]) -> None:
    if not terminal():
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


def _existe(caminho: Path) -> bool:
    return caminho.exists() or caminho.is_symlink()


def _sem_aninhados(candidatos: list[Path]) -> list[Path]:
    """O `.resolve()` só compara; quem fica é o caminho original.

    Um caminho dentro de outro listado sai junto com ele; se o de fora é um
    link, o de dentro é conteúdo do alvo e fica intocado.
    """

    def dentro(c: Path, fora: Path) -> bool:
        if fora is c:
            return False
        if fora.is_symlink():
            return fora in c.parents
        return fora.resolve() in c.resolve().parents

    vistos: set[Path] = set()
    unicos = []
    for c in candidatos:
        if (chave := c.parent.resolve() / c.name) not in vistos:
            vistos.add(chave)
            unicos.append(c)
    return [c for c in unicos if not any(dentro(c, f) for f in unicos)]


def _caminhos_de_dados() -> tuple[list[Path], list[Path]]:
    """Pastas e arquivos do SQLite (fora delas), só os que existem."""
    pastas = [
        Path(os.path.abspath(p))
        for p in (
            Path(caminho_config_global()).parent,
            diretorio_dados(),
            diretorio_cache(),
        )
    ]
    arquivos = []
    banco = os.environ.get(VarAmbiente.DATABASE_SQLITE_PATH, "").strip()
    if banco:
        base = Path(os.path.abspath(Path(banco).expanduser()))
        arquivos = [Path(f"{base}{s}") for s in SUFIXOS_SQLITE]
    listados = _sem_aninhados([c for c in [*pastas, *arquivos] if _existe(c)])
    return (
        [c for c in listados if c in pastas],
        [c for c in listados if c in arquivos],
    )


def _descrever(caminho: Path) -> str:
    if caminho.is_symlink():
        return f"{caminho} → {caminho.resolve()}, só o link é removido"
    return str(caminho)


def _confirmar_apagar(caminhos: list[Path]) -> bool:
    print("Dados do monitor-versoes:")
    for caminho in caminhos:
        print(f"  {_descrever(caminho)}")
    try:
        return confirmar("Apagar esses dados?", False)
    except KeyboardInterrupt:
        sys.exit(CodigoSaida.INTERROMPIDO)


def _apagar(caminho: Path, pasta: bool) -> bool:
    try:
        if pasta and caminho.is_dir() and not caminho.is_symlink():
            shutil.rmtree(caminho)
        else:
            caminho.unlink()
    except OSError as e:
        marcar(Marca.FALHA, f"não foi possível apagar {caminho}: {e.strerror or e}")
        return False
    return True


def desinstalar() -> None:
    home = Path.home()
    with contextlib.suppress(ErroDeEntrada):
        if servico.remover(
            agendador.sistema_atual(), home, agendador.rodar_comando_do_sistema
        ):
            marcar(Marca.OK, "daemon e início no login removidos")
    agendador.remover_agendador_antigo(home, agendador.rodar_comando_do_sistema)
    pastas, arquivos = _caminhos_de_dados()
    caminhos = [*pastas, *arquivos]
    if not caminhos:
        print("Nenhum dado do monitor-versoes a remover.")
        return
    apagar = terminal() and _confirmar_apagar(caminhos)
    for caminho in caminhos:
        removido = apagar and _apagar(caminho, pasta=caminho in pastas)
        situacao = Situacao.REMOVIDO if removido else Situacao.MANTIDO
        print(f"{situacao}: {_descrever(caminho)}")
