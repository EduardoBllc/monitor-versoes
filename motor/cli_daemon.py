"""Comando `daemon`: roda em primeiro plano ou dirige o serviço do sistema e o início no login."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from motor import agendador, servico
from motor.agendador import Sistema
from motor.config import (
    checar_backend,
    nunca_iniciar_login,
    porta_daemon,
    validar_porta,
)
from motor.config_edicao import gravar_nunca_iniciar_login, gravar_porta_daemon
from motor.daemon import PORTA_PADRAO
from motor.errors import BackendIndisponivel, ErroDeEntrada
from motor.servico import EstadoServico, Situacao

COMANDO_DAEMON = "daemon"
FLAG_PORTA = "--porta"
FLAG_SEM_NAVEGADOR = "--sem-navegador"
FLAG_INICIAR_LOGIN = "--iniciar-login"
FLAG_NUNCA_INICIAR_LOGIN = "--nunca-iniciar-login"
FLAG_PARAR_LOGIN = "--parar-login"
FLAG_SEM_PERGUNTAS = "--sem-perguntas"


class AcaoDaemon(StrEnum):
    RODAR = "rodar"
    INICIAR = "iniciar"
    PARAR = "parar"
    REINICIAR = "reiniciar"
    ESTADO = "estado"


AVISO_RODAR = (
    "para rodar em segundo plano, use "
    f"`{servico.EXECUTAVEL} {COMANDO_DAEMON} {AcaoDaemon.INICIAR}`"
)
PERGUNTA_LOGIN = "Iniciar também no login?"
PERGUNTA_SALVAR = "Salvar essa escolha para as próximas vezes?"
PERGUNTA_PARAR_LOGIN = "Parar de iniciar no login também?"
ERRO_NO_TERMINAL = "há um daemon rodando no terminal; feche-o"

_ROTULO_ESTADO = {
    EstadoServico.ATIVO: "rodando",
    EstadoServico.NO_TERMINAL: "rodando no terminal",
    EstadoServico.PARADO: "parado",
}
_SIM_NAO = {True: "sim", False: "não"}


@dataclass(frozen=True)
class _Alvo:
    sistema: Sistema
    home: Path
    executavel: str


def adicionar_parsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p_daemon = sub.add_parser(
        COMANDO_DAEMON, help="roda, inicia, para e mostra o daemon da interface web"
    )
    p_daemon.set_defaults(porta=None)
    acoes = p_daemon.add_subparsers(dest="acao_daemon", required=True, metavar="acao")
    porta = argparse.ArgumentParser(add_help=False)
    porta.add_argument(
        FLAG_PORTA,
        type=int,
        help=f"porta da interface web (padrão: a salva, ou {PORTA_PADRAO})",
    )
    perguntas = argparse.ArgumentParser(add_help=False)
    perguntas.add_argument(
        FLAG_SEM_PERGUNTAS,
        action="store_true",
        help="não pergunta nada; o início no login fica como está",
    )

    p_rodar = acoes.add_parser(
        AcaoDaemon.RODAR, parents=[porta], help="roda em primeiro plano"
    )
    p_rodar.add_argument(
        FLAG_SEM_NAVEGADOR, action="store_true", help="não abre o navegador ao subir"
    )
    p_iniciar = acoes.add_parser(
        AcaoDaemon.INICIAR,
        parents=[porta, perguntas],
        help="sobe em segundo plano; --porta fica salva",
    )
    login = p_iniciar.add_mutually_exclusive_group()
    login.add_argument(
        FLAG_INICIAR_LOGIN, action="store_true", help="inicia também em todo login"
    )
    login.add_argument(
        FLAG_NUNCA_INICIAR_LOGIN,
        action="store_true",
        help="não inicia no login e não pergunta mais",
    )
    p_parar = acoes.add_parser(
        AcaoDaemon.PARAR, parents=[perguntas], help="para o daemon em segundo plano"
    )
    p_parar.add_argument(
        FLAG_PARAR_LOGIN, action="store_true", help="para de iniciar no login também"
    )
    acoes.add_parser(
        AcaoDaemon.REINICIAR,
        parents=[porta],
        help="para e sobe de novo; --porta fica salva",
    )
    acoes.add_parser(
        AcaoDaemon.ESTADO, help="mostra se roda, se inicia no login e onde ver o log"
    )


def daemon(args: argparse.Namespace) -> None:
    if args.porta is not None:
        validar_porta(args.porta)
    acao = AcaoDaemon(args.acao_daemon)
    if acao is AcaoDaemon.RODAR:
        _rodar(args)
        return
    alvo = _Alvo(agendador.sistema_atual(), Path.home(), servico.executavel_servico())
    servico.migrar_legado(
        alvo.sistema,
        alvo.home,
        alvo.executavel,
        agendador.rodar_comando_do_sistema,
        servico.consultar_do_sistema,
    )
    match acao:
        case AcaoDaemon.INICIAR:
            _iniciar(args, alvo)
        case AcaoDaemon.PARAR:
            _parar(args, alvo)
        case AcaoDaemon.REINICIAR:
            _reiniciar(args, alvo)
        case AcaoDaemon.ESTADO:
            _estado(alvo)


def _rodar(args: argparse.Namespace) -> None:
    from motor.daemon.app import servir

    checar_backend()
    if sys.stdout.isatty():
        print(AVISO_RODAR)
    porta = porta_daemon() if args.porta is None else args.porta
    servir(porta, args.ambiente_filhos, not args.sem_navegador)


def _iniciar(args: argparse.Namespace, alvo: _Alvo) -> None:
    anterior = porta_daemon()
    situacao = _sem_daemon_no_terminal(alvo, anterior)
    porta = _salvar_porta(args, anterior)
    rodando = situacao.estado is EstadoServico.ATIVO
    if rodando and porta == anterior:
        print(f"o daemon já está rodando em {servico.endereco_web(porta)}")
    else:
        _subir(alvo, porta)
    _login_ao_iniciar(args, alvo, situacao.login, rodando)


def _login_ao_iniciar(
    args: argparse.Namespace, alvo: _Alvo, ligado: bool, rodando: bool
) -> None:
    if args.iniciar_login:
        _ligar_login(alvo)
        return
    if args.nunca_iniciar_login:
        if ligado:
            _desligar_login(alvo)
        gravar_nunca_iniciar_login(True)
        return
    if ligado or rodando or nunca_iniciar_login() or not _pode_perguntar(args):
        return
    if _confirmar(PERGUNTA_LOGIN, True):
        _ligar_login(alvo)
    elif _confirmar(PERGUNTA_SALVAR, False):
        gravar_nunca_iniciar_login(True)


def _parar(args: argparse.Namespace, alvo: _Alvo) -> None:
    situacao = _sem_daemon_no_terminal(alvo, porta_daemon())
    if situacao.estado is EstadoServico.ATIVO:
        servico.parar(alvo.sistema, alvo.home, agendador.rodar_comando_do_sistema)
        print("daemon parado")
    else:
        print("o daemon já está parado")
    if not situacao.login:
        return
    if args.parar_login or (
        _pode_perguntar(args) and _confirmar(PERGUNTA_PARAR_LOGIN, False)
    ):
        _desligar_login(alvo)


def _reiniciar(args: argparse.Namespace, alvo: _Alvo) -> None:
    anterior = porta_daemon()
    _sem_daemon_no_terminal(alvo, anterior)
    _subir(alvo, _salvar_porta(args, anterior))


def _estado(alvo: _Alvo) -> None:
    situacao = _situacao(alvo, porta_daemon())
    print(f"daemon: {_ROTULO_ESTADO[situacao.estado]}")
    print(f"iniciar no login: {_SIM_NAO[situacao.login]}")
    print(f"nunca iniciar no login: {_SIM_NAO[nunca_iniciar_login()]}")
    print(f"log: {_ver_log(alvo)}")


def _situacao(alvo: _Alvo, porta: int) -> Situacao:
    return servico.situacao(
        alvo.home,
        servico.consultar_do_sistema,
        lambda: servico.serve_responde(porta, esperar=False),
    )


def _sem_daemon_no_terminal(alvo: _Alvo, porta: int) -> Situacao:
    situacao = _situacao(alvo, porta)
    if situacao.estado is EstadoServico.NO_TERMINAL:
        raise ErroDeEntrada(ERRO_NO_TERMINAL)
    return situacao


def _ver_log(alvo: _Alvo) -> str:
    # Sem serviço nem porta respondendo, a situação é sempre PARADO, a única que traz o log.
    return servico.situacao(alvo.home, lambda _: None, lambda: False).ver_log


def _salvar_porta(args: argparse.Namespace, anterior: int) -> int:
    if args.porta is None:
        return anterior
    gravar_porta_daemon(args.porta)
    return int(args.porta)


def _subir(alvo: _Alvo, porta: int) -> None:
    servico.subir(
        alvo.sistema, alvo.home, alvo.executavel, agendador.rodar_comando_do_sistema
    )
    endereco = servico.endereco_web(porta)
    if not servico.serve_responde(porta, esperar=True):
        raise BackendIndisponivel(
            f"o daemon não respondeu em {endereco}; veja o log com `{_ver_log(alvo)}`"
        )
    print(f"daemon rodando em {endereco}")


def _ligar_login(alvo: _Alvo) -> None:
    servico.ligar_login(
        alvo.sistema, alvo.home, alvo.executavel, agendador.rodar_comando_do_sistema
    )
    print("início no login ligado")


def _desligar_login(alvo: _Alvo) -> None:
    servico.desligar_login(alvo.sistema, alvo.home, agendador.rodar_comando_do_sistema)
    print("início no login desligado")


def _pode_perguntar(args: argparse.Namespace) -> bool:
    from motor import assistente

    return not args.sem_perguntas and assistente.terminal()


def _confirmar(texto: str, padrao: bool) -> bool:
    from motor import assistente

    return assistente.confirmar(texto, padrao)
