"""Porte de cmd/motor/main.go.

CLI fina: so parseia argumentos, monta Deps e chama o engine. Sem logica de
dominio aqui.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import textwrap
import time
from collections.abc import Callable
from collections.abc import Set as AbstractSet
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import TextIO

from motor.agendador import (
    agendar,
    desagendar,
    executavel_motor,
    instalado,
    rodar_comando_do_sistema,
    sistema_atual,
)
from motor.config import (
    AMBIENTE_PADRAO,
    SECAO_REPOS,
    ambiente_central,
    caminho_config_global,
    carregar_config_global,
    carregar_config_repo,
    repos_configurados,
    validar_nome_repo,
)
from motor.daemon import PORTA_PADRAO
from motor.diagnostico import diagnosticar, falhou, formatar
from motor.domain.commits import agrupar_por_chamado
from motor.domain.inscricao import Desfecho, Resultado
from motor.domain.referencia import FonteReferencia, formatar_referencia
from motor.domain.types import CommitRef, VersionStatus
from motor.engine.atualizar import (
    AtualizarResult,
    AtualizarStatus,
    atualizar,
    atualizar_abort,
    atualizar_continue,
)
from motor.engine.consultar import ChamadoConsultado, consultar
from motor.engine.criar import criar
from motor.engine.deps import Deps
from motor.engine.inscricao import executar_inscricao
from motor.engine.migrar_estado import migrar_estado
from motor.engine.orfaos import (
    OrfaoDaVersao,
    julgar_orfao,
    linha_do_orfao,
    listar_orfaos,
)
from motor.engine.reconstruir_estado import reconstruir_estado
from motor.engine.verificar import verificar
from motor.errors import ErroDeEntrada, MotorError, formatar_com_notas
from motor.init import iniciar
from motor.inscricoes import (
    INTERVALO_PADRAO,
    Inscricao,
    caminho_arquivo,
    carregar,
    disparar_subprocesso,
    formatar_intervalo,
    inscrever,
    parse_intervalo,
    registrar_execucao,
    remover,
    rodar,
)
from motor.migracoes import head, migrar
from motor.montagem import (
    CredenciaisBitbucket,
    FonteTasks,
    abrir_sessao,
    montar_deps,
    montar_notificador,
)
from motor.progresso import Progresso, RelatorProgresso, silencioso

# Anotado Optional na declaracao: sem isso o `= None` do fallback conflita com
# o tipo da funcao importada, e `if load_dotenv:` passa a ser lido como
# "funcao sempre verdadeira".
_CarregarAmbiente = Callable[..., bool]
load_dotenv: _CarregarAmbiente | None
try:
    from dotenv import load_dotenv as _load_dotenv
except ImportError:
    load_dotenv = None
else:
    load_dotenv = _load_dotenv

AJUDA_REPO = f"nome da seção [{SECAO_REPOS}.<nome>] do config.toml"

_ARQUIVOS_AMBIENTE = {
    "development": ".env.development",
    "production": ".env",
}


def _tipo_cli[T](validador: Callable[[str], T]) -> Callable[[str], T]:
    """Adapta um validador de `motor.montagem` ao protocolo do argparse.

    A regra e compartilhada com a TUI e fala `MotorError`; traduzir para
    `ArgumentTypeError` e trabalho do CLI, e so aqui, porque so aqui existe
    argparse.
    """

    def converter(valor: str) -> T:
        try:
            return validador(valor)
        except MotorError as erro:
            raise argparse.ArgumentTypeError(str(erro)) from None

    return converter


def _selecionar(argv: list[str]) -> tuple[str, str | None, str | None]:
    """`--env`, comando e ação, lidos antes do parser montar os defaults."""
    seletor = argparse.ArgumentParser(add_help=False)
    seletor.add_argument("--env", choices=_ARQUIVOS_AMBIENTE, default=AMBIENTE_PADRAO)
    seletor.add_argument("comando", nargs="?")
    seletor.add_argument("acao", nargs="?")
    lidos = seletor.parse_known_args(argv)[0]
    return lidos.env, lidos.comando, lidos.acao


def _carregar_ambiente(argv: list[str]) -> MotorError | None:
    """Aplica `[ambiente]` do central > `.env` do cwd > shell.

    O caminho do central sai do `XDG_CONFIG_HOME` herdado e é restaurado no fim:
    um `.env` (ou o próprio `[ambiente]`) que o mudasse faria o motor ler um
    arquivo diferente do que acabou de aplicar.

    O `inscricao rodar` não lê nada e repassa aos filhos o ambiente que herdou;
    o `inscricao executar` não lê `.env`, para não depender de onde o agendador
    o chamou. Devolve o erro do central quando o comando o tolera.
    """
    ambiente, comando, acao = _selecionar(argv)
    if (comando, acao) == ("inscricao", AcaoInscricao.RODAR):
        return None
    filho = (comando, acao) == ("inscricao", AcaoInscricao.EXECUTAR)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    erro: MotorError | None = None
    try:
        central = ambiente_central()
    except ErroDeEntrada as e:
        # O diagnóstico mostra o erro numa linha própria; o filho o grava como
        # desfecho da inscrição. Os demais comandos morrem com ele.
        if comando != "diagnostico" and not filho:
            raise
        central, erro = {}, e
    if load_dotenv and not filho:
        load_dotenv(Path.cwd() / _ARQUIVOS_AMBIENTE[ambiente], override=True)
    os.environ.update(central)
    if xdg is None:
        os.environ.pop("XDG_CONFIG_HOME", None)
    else:
        os.environ["XDG_CONFIG_HOME"] = xdg
    return erro


def _init(_args: argparse.Namespace) -> None:
    for mensagem in iniciar(Path.cwd(), caminho_config_global()):
        print(mensagem)


def _migrar(_args: argparse.Namespace) -> None:
    migrar()
    print("migrações aplicadas")


def _diagnostico(args: argparse.Namespace) -> None:
    resultados = diagnosticar(
        os.environ,
        abrir_sessao=abrir_sessao,
        head=head(),
        ambiente=args.env,
        config_central=carregar_config_global,
        repos=repos_configurados,
        config_em=caminho_config_global(),
        erro_ambiente=args.erro_central,
    )
    for resultado in resultados:
        print(formatar(resultado))
    if falhou(resultados):
        sys.exit(1)


class AcaoInscricao(StrEnum):
    ADICIONAR = "adicionar"
    LISTAR = "listar"
    REMOVER = "remover"
    AGENDAR = "agendar"
    RODAR = "rodar"
    EXECUTAR = "executar"


def _agendador_instalado() -> bool:
    try:
        return instalado(sistema_atual(), Path.home())
    except ErroDeEntrada:  # SO sem agendador: o adicionar só avisa
        return False


def _inscricao_adicionar(args: argparse.Namespace) -> None:
    carregar_config_repo(args.repo)  # recusa já aqui o nome que o executar não acharia
    inscrever(
        caminho_arquivo(),
        Inscricao(
            repo=args.repo,
            versao=args.versao,
            intervalo=parse_intervalo(args.intervalo),
        ),
    )
    print(f"inscrição de {args.versao} registrada")
    if not _agendador_instalado():
        print(
            "agendador não instalado: rode `motor inscricao agendar`", file=sys.stderr
        )


def _inscricao_listar() -> None:
    for i in carregar(caminho_arquivo()):
        if i.ultima is None:
            ultima = "nunca rodou"
        else:
            ultima = (
                f"{i.ultima.hora.astimezone():%Y-%m-%d %H:%M} {i.ultima.desfecho.value}"
            )
            if i.ultima.mensagem:
                ultima += f": {i.ultima.mensagem}"
        print(
            f"{i.versao}  {i.repo}  a cada {formatar_intervalo(i.intervalo)}  {ultima}"
        )


def _inscricao_agendar(args: argparse.Namespace) -> None:
    sistema = sistema_atual()
    if args.desfazer:
        desagendar(sistema, Path.home(), rodar_comando_do_sistema)
        print("agendador removido")
    else:
        agendar(sistema, Path.home(), executavel_motor(), rodar_comando_do_sistema)
        print("agendador instalado")


def _inscricao_executar(args: argparse.Namespace) -> None:
    caminho = caminho_arquivo()
    inscricao = next(
        (
            i
            for i in carregar(caminho)
            if (i.repo, i.versao) == (args.repo, args.versao)
        ),
        None,
    )
    if inscricao is None:
        raise ErroDeEntrada(f"inscrição não encontrada: {args.repo} {args.versao}")
    notificador = montar_notificador()
    if args.erro_central is not None:
        # Meia configuração (sem o [ambiente]) poderia cair noutro banco: o
        # erro do arquivo é o desfecho, visível no `listar`.
        erro_central = Resultado(Desfecho.ERRO, mensagem=str(args.erro_central))
        registrar_execucao(
            caminho, inscricao, erro_central, notificador, datetime.now(UTC)
        )
        return
    try:
        with abrir_sessao() as sessao:
            resultado = executar_inscricao(montar_deps(args.repo, sessao), args.versao)
    except MotorError as e:
        resultado = Resultado(Desfecho.ERRO, mensagem=str(e))
    except Exception as e:
        # Grava antes de propagar: o traceback segue para o log do agendador.
        erro = Resultado(Desfecho.ERRO, mensagem=f"{type(e).__name__}: {e}")
        registrar_execucao(caminho, inscricao, erro, notificador, datetime.now(UTC))
        raise
    registrar_execucao(caminho, inscricao, resultado, notificador, datetime.now(UTC))


def _inscricao(args: argparse.Namespace) -> None:
    match AcaoInscricao(args.acao_inscricao):
        case AcaoInscricao.ADICIONAR:
            _inscricao_adicionar(args)
        case AcaoInscricao.LISTAR:
            _inscricao_listar()
        case AcaoInscricao.REMOVER:
            remover(caminho_arquivo(), args.repo, args.versao)
        case AcaoInscricao.AGENDAR:
            _inscricao_agendar(args)
        case AcaoInscricao.RODAR:
            rodar(
                caminho_arquivo(),
                datetime.now(UTC),
                partial(disparar_subprocesso, env=dict(os.environ)),
                montar_notificador(),
            )
        case AcaoInscricao.EXECUTAR:
            _inscricao_executar(args)


# Comandos que não passam pela montagem de dependências do `main()` (repos,
# fonte de tarefas, fontes de commit): cada um cuida do próprio banco, ou não usa.
_SEM_BANCO: dict[str, Callable[[argparse.Namespace], None]] = {
    "init": _init,
    "migrar": _migrar,
    "diagnostico": _diagnostico,
    "inscricao": _inscricao,
}


def _parsers_de_orfaos(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    comum: argparse.ArgumentParser,
) -> None:
    sub.add_parser(
        "orfaos",
        parents=[comum],
        help="lista os commits sem referencia de tarefa da versao e o julgamento",
    )
    p_julgar = sub.add_parser(
        "julgar-orfao",
        parents=[comum],
        help="grava a qual chamado pertence um commit orfao da versao",
    )
    p_julgar.add_argument("hash", help="hash do orfao (pode ser abreviado)")
    destino = p_julgar.add_mutually_exclusive_group(required=True)
    destino.add_argument(
        "--chamado", metavar="ID", help="ID do chamado a que o commit pertence"
    )
    destino.add_argument(
        "--nenhum",
        action="store_true",
        help="o commit nao pertence a chamado nenhum",
    )
    p_julgar.add_argument(
        "--motivo", metavar="TEXTO", required=True, help="por que (obrigatorio)"
    )


def _build_parser() -> argparse.ArgumentParser:
    """Um subparser por comando: `motor -h` lista os comandos e
    `motor <comando> -h` mostra so as flags daquele comando (help nativo do
    argparse). Flags compartilhadas (--repo, --debug) vivem num parent parser.
    """
    comum = argparse.ArgumentParser(add_help=False)
    comum.add_argument("versao", help="versao alvo no formato X.Y.Z")
    comum.add_argument(
        "--repo", required=True, type=_tipo_cli(validar_nome_repo), help=AJUDA_REPO
    )
    comum.add_argument(
        "--debug", action="store_true", help="loga tempos de cada etapa/comando git"
    )
    comum.add_argument(
        "--sem-progresso",
        dest="sem_progresso",
        action="store_true",
        help="nao mostra a barra de progresso (ligada por default em terminal)",
    )
    comum.add_argument(
        "--bitbucket-token",
        dest="bitbucket_token",
        default=os.environ.get("BITBUCKET_TOKEN", ""),
        help="token Bitbucket Cloud (default: $BITBUCKET_TOKEN); ativa descoberta de commits por PR",
    )
    comum.add_argument(
        "--bitbucket-email",
        dest="bitbucket_email",
        default=os.environ.get("BITBUCKET_EMAIL", ""),
        help="email da conta dona do token Bitbucket (default: $BITBUCKET_EMAIL)",
    )
    # No parser pai, nao no 'criar': todos os comandos montam a fonte de tasks
    # (o Deps e um so), e uma flag exclusiva do 'criar' viraria AttributeError
    # nos outros.
    comum.add_argument(
        "--task-source",
        dest="fonte_flag",
        default="config",
        choices=["config", "manual"],
        help="fonte das tasks (default: config, a [tarefas] fonte)",
    )
    comum.add_argument(
        "--lista",
        dest="lista_manual",
        default="",
        help="arquivo de lista (obrigatorio com --task-source=manual)",
    )

    parser = argparse.ArgumentParser(prog="motor")
    parser.add_argument(
        "--env",
        choices=_ARQUIVOS_AMBIENTE,
        default=AMBIENTE_PADRAO,
        help=f"ambiente (default: {AMBIENTE_PADRAO})",
    )
    sub = parser.add_subparsers(dest="comando", required=True, metavar="comando")

    p_verificar = sub.add_parser(
        "verificar",
        parents=[comum],
        help="mostra status da versao (verde, tasks, faltantes)",
    )
    p_verificar.add_argument(
        "--auditar",
        action="store_true",
        help="recalcula uma versao liberada contra a tag, sem alterar o snapshot",
    )

    sub.add_parser(
        "criar", parents=[comum], help="cria a branch da versao a partir das tasks"
    )

    p_inc = sub.add_parser(
        "atualizar",
        parents=[comum],
        help="aplica commits faltantes na branch da versao",
    )
    grupo = p_inc.add_mutually_exclusive_group()
    grupo.add_argument(
        "--continue",
        dest="continuar",
        action="store_true",
        help="retoma apos resolver conflito",
    )
    grupo.add_argument(
        "--abort",
        dest="abortar",
        action="store_true",
        help="aborta o incremento em andamento",
    )
    p_inc.add_argument(
        "--allow-empty",
        dest="allow_empty",
        action="store_true",
        help="com --continue: aceita a resolucao que nao deixou alteracao, "
        "registrando o commit como vazio",
    )

    sub.add_parser(
        "reconstruir-estado",
        parents=[comum],
        help="regenera as atribuicoes a partir do git",
    )
    sub.add_parser(
        "consulta",
        parents=[comum],
        help="mostra os chamados e commits salvos para a versao",
    )
    _parsers_de_orfaos(sub, comum)

    sub.add_parser(
        "tui",
        help="abre a interface interativa de consulta, verificacao e atualizacao",
    )

    p_serve = sub.add_parser("serve", help="sobe a interface web local")
    p_serve.add_argument("--porta", type=int, default=PORTA_PADRAO)

    sub.add_parser("migrar", help="aplica as migrações pendentes do banco")

    sub.add_parser("init", help="escreve compose.yml no diretório atual")

    sub.add_parser(
        "diagnostico",
        help="checa cada peça da instalação e diz como corrigir o que falhar",
    )

    p_migrar = sub.add_parser(
        "migrar-estado",
        help="copia o estado completo de um banco para outro (SQLite <-> Postgres)",
    )
    p_migrar.add_argument(
        "--de",
        required=True,
        metavar="URL",
        help="origem: sqlite:///<caminho> ou postgresql://...",
    )
    p_migrar.add_argument(
        "--para", required=True, metavar="URL", help="destino vazio, no mesmo formato"
    )

    p_insc = sub.add_parser("inscricao", help="acompanha versões em segundo plano")
    acoes_insc = p_insc.add_subparsers(
        dest="acao_inscricao", required=True, metavar="acao"
    )
    repo_arg = argparse.ArgumentParser(add_help=False)
    repo_arg.add_argument("versao", help="versao alvo no formato X.Y.Z")
    repo_arg.add_argument(
        "--repo", required=True, type=_tipo_cli(validar_nome_repo), help=AJUDA_REPO
    )
    p_inscrever = acoes_insc.add_parser(
        AcaoInscricao.ADICIONAR, parents=[repo_arg], help="inscreve uma versão"
    )
    p_inscrever.add_argument(
        "--intervalo", default=INTERVALO_PADRAO, help="Nm ou Nh (default: 30m)"
    )
    acoes_insc.add_parser(AcaoInscricao.LISTAR, help="lista as inscrições")
    acoes_insc.add_parser(
        AcaoInscricao.REMOVER, parents=[repo_arg], help="remove uma inscrição"
    )
    p_agendar = acoes_insc.add_parser(
        AcaoInscricao.AGENDAR, help="instala o disparo por minuto"
    )
    p_agendar.add_argument("--desfazer", action="store_true", help="remove o disparo")
    acoes_insc.add_parser(AcaoInscricao.RODAR, help="dispara as inscrições vencidas")
    # Sem help=: o argparse não lista; é o comando interno do agendador.
    acoes_insc.add_parser(AcaoInscricao.EXECUTAR, parents=[repo_arg])

    return parser


def _iniciar_serve(porta: int) -> None:
    from motor.daemon.app import servir

    servir(porta)


def _iniciar_tui() -> None:
    from motor.tui import run_tui

    run_tui()


def _imprimir_commits_por_task(
    titulo: str,
    commits: list[CommitRef],
    conflitantes: set[str],
    suspeitos: AbstractSet[str] = frozenset(),
    causado_por: dict[str, list[str]] | None = None,
) -> None:
    """`causado_por` leva as referencias ja formatadas, prontas para imprimir."""
    grupos = agrupar_por_chamado(commits)
    print(f"{titulo} ({len(commits)} em {len(grupos)} tasks):")
    for chave, itens in grupos.items():
        print(f"  {chave}:")
        for c in itens:
            primeira_linha_msg = c.msg.splitlines()[0] if c.msg else ""
            tag = ""
            if c.hash_origem in conflitantes:
                # Os culpados vao dentro da propria tag: em linha separada o
                # operador perde a ligacao com o commit ao ler uma lista longa.
                culpados = (causado_por or {}).get(c.hash_origem, [])
                tag = (
                    " [CONFLITANTE: depende de "
                    + ", ".join(culpados)
                    + ", fora desta versao]"
                    if culpados
                    else " [CONFLITANTE]"
                )
            tag += (
                " [SUSPEITO: msg+arquivos ja existem no alvo com conteudo diferente]"
                if c.hash_origem in suspeitos
                else ""
            )
            print(f"    - {c.hash_origem[:8]} {primeira_linha_msg}{tag}".rstrip())


def _imprimir_alertas(s: VersionStatus) -> None:
    """As secoes vermelhas do status. Vive separada porque o `atualizar` tambem
    tem de imprimi-las: sao computadas, derrubam o verde e antes nao chegavam a
    lugar nenhum no caminho do atualizar.
    """
    if s.tasks_ambiguas:
        print(f"tasks marcadas em mais de uma versao: {s.tasks_ambiguas}")
        print("  (dado inconsistente no rastreador - corrija a marcacao)")
    if s.tasks_sem_commits:
        print(f"tasks sem commits: {s.tasks_sem_commits}")
        print("  (nenhum commit/PR achado - registre em sem_entrega se for proposital)")
    if not s.estado_integro:
        print(f"estado: divergente do git ({len(s.commits_sumidos)} commits sumidos)")
        for hash_ in s.commits_sumidos:
            print(f"  - {hash_[:8]}")


def _referencias_dos_culpados(
    causado_por: dict[str, list[str]], referencia: FonteReferencia
) -> dict[str, list[str]]:
    """Culpados pela referencia da tarefa (como `ch123`).

    Resolvida so se ha culpado: snapshot e status sem conflito atribuido nao
    passam a exigir padrao de referencia.
    """
    if not any(causado_por.values()):
        return causado_por
    ref = referencia()
    return {
        h: [formatar_referencia(ref, ch) for ch in chamados]
        for h, chamados in causado_por.items()
    }


def imprimir_status(s: VersionStatus, referencia: FonteReferencia) -> None:
    if s.liberada_em is not None:
        # Snapshot de versao liberada (docs/decisoes/010-travas-publicada-e-liberada.md):
        # nada foi recalculado, e sem
        # dizer isso a saida seria indistinguivel de uma versao verde em
        # construcao. Os chamados vem primeiro porque este e o unico lugar em
        # que se le o que so o banco registra.
        print(
            f"versao liberada em {s.liberada_em:%Y-%m-%d %H:%M} - "
            "snapshot congelado, nao recalculado"
        )
        print(f"chamados ({len(s.chamados)}): {', '.join(s.chamados)}".rstrip())
        print(f"verde: {s.verde}")
        return

    print(f"verde: {s.verde}")
    print(f"tasks novas: {s.tasks_novas}")
    print(f"tasks removidas: {s.tasks_removidas}")
    _imprimir_alertas(s)
    if s.estado_integro:
        print("estado: integro")
    conflitantes = {c.hash_origem for c in s.conflitantes}
    suspeitos = {c.hash_origem for c in s.suspeitos_conteudo}
    _imprimir_commits_por_task(
        "faltantes",
        s.faltantes,
        conflitantes,
        suspeitos,
        _referencias_dos_culpados(s.conflito_causado_por, referencia),
    )


def imprimir_atualizacao(r: AtualizarResult, referencia: FonteReferencia) -> None:
    if r.reaproveitada_de is not None:
        hora = r.reaproveitada_de.astimezone().strftime("%H:%M")
        print(f"reaproveitando a verificacao das {hora}")
    if r.aplicados:
        _imprimir_commits_por_task("cherry-picks aplicados", r.aplicados, set())
    else:
        print("nenhum cherry-pick (branch ja atualizada)")
    if r.vazios:
        hashes = ", ".join(c.hash_origem[:8] for c in r.vazios)
        print(
            f"{len(r.vazios)} commits sem alteracao no alvo, registrados como "
            f"commit vazio: {hashes}"
        )
    if r.ja_presentes:
        print(f"{r.ja_presentes} commits ja presentes no historico (ignorados)")

    # Antes do "concluido": o lote e empurrado mesmo sem verde, mas o operador
    # tem de ficar sabendo do que o verificar viu.
    if r.status_versao is not None:
        _imprimir_alertas(r.status_versao)

    if r.status == AtualizarStatus.BLOCKED:
        linha = f"BLOQUEADO em {r.blocked_commit[:8]}, arquivos: {r.arquivos_conflito}"
        if r.culpados:
            refs = _referencias_dos_culpados(
                {r.blocked_commit: r.culpados}, referencia
            )[r.blocked_commit]
            linha += f", depende de {', '.join(refs)}, fora desta versao"
        print(linha)
        print("resolva e rode: motor atualizar <versao> --repo <path> --continue")
        return
    if r.status == AtualizarStatus.VAZIO:
        print(
            f"VAZIO em {r.blocked_commit[:8]}: a resolucao nao deixou alteracao "
            "nenhuma no alvo"
        )
        print(
            "confirme com: motor atualizar <versao> --repo <path> --continue "
            "--allow-empty (entra como commit vazio, com o trailer -x)"
        )
        print(
            "ou descarte o commit com: motor atualizar <versao> --repo <path> --abort"
        )
        return
    print("concluido")


def imprimir_consulta(chamados: list[ChamadoConsultado]) -> None:
    if not chamados:
        print("nenhum chamado registrado para esta versao")
        return
    for chamado in chamados:
        print(f"{chamado.chamado} [{chamado.estado.upper()}]")
        if not chamado.commits:
            print("  (sem commits registrados)")
        for commit in chamado.commits:
            titulo = (
                commit.msg.splitlines()[0] if commit.msg else "mensagem indisponível"
            )
            titulo = textwrap.shorten(titulo, width=100, placeholder="…")
            print(f"  - {commit.hash_origem[:8]} {titulo}")


def imprimir_orfaos(orfaos: list[OrfaoDaVersao]) -> None:
    if not orfaos:
        print("sem orfaos")
        return
    for o in orfaos:
        print(linha_do_orfao(o))


def _escrever_progresso(progresso: Progresso, saida: TextIO) -> None:
    r"""Uma linha reescrita no lugar, em stderr.

    stderr e nao stdout porque a saida dos comandos e canalizavel (`motor
    consulta | grep`) — barra no meio do pipe quebraria quem consome.

    O `\x1b[K` apaga o resto da linha: sem ele, uma fase curta depois de uma
    longa ("gravando estado" depois de "commits dos chamados no Bitbucket
    12/48") deixa o rabo da anterior na tela.
    """
    contagem = f" {progresso.feito}/{progresso.total}" if progresso.total else ""
    saida.write(f"\r\x1b[K{progresso.fase}{contagem}")
    saida.flush()


def _relator_do_cli(
    *, desligado: bool, saida: TextIO | None = None
) -> RelatorProgresso:
    r"""Sem flag para ligar: liga sozinho em terminal, cala em pipe ou arquivo.

    Redirecionado, cada evento viraria uma linha com `\r` cru no log — e nao ha
    barra para ninguem ver. `--sem-progresso` existe para o caso em que o
    terminal e interativo mas a barra incomoda (script com `script -q`, CI com
    TTY alocado).
    """
    saida = sys.stderr if saida is None else saida
    if desligado or not saida.isatty():
        return silencioso
    return lambda progresso: _escrever_progresso(progresso, saida)


def _limpar_progresso(relator: RelatorProgresso, saida: TextIO | None = None) -> None:
    """Apaga a linha da barra antes da saida de verdade do comando."""
    if relator is silencioso:
        return
    saida = sys.stderr if saida is None else saida
    saida.write("\r\x1b[K")
    saida.flush()


def _despachar(args: argparse.Namespace, deps: Deps) -> None:
    inicio = time.monotonic()
    if args.comando == "verificar":
        status = verificar(deps, args.versao, auditar=args.auditar)
        if args.auditar:
            print(f"auditoria da tag {args.versao} (snapshot nao alterado)")
        imprimir_status(status, deps.referencia)
    elif args.comando == "criar":
        imprimir_atualizacao(criar(deps, args.versao), deps.referencia)
    elif args.comando == "atualizar":
        if args.abortar:
            atualizar_abort(deps, args.versao)
            print("abortado")
        elif args.continuar:
            imprimir_atualizacao(
                atualizar_continue(deps, args.versao, allow_empty=args.allow_empty),
                deps.referencia,
            )
        else:
            imprimir_atualizacao(atualizar(deps, args.versao), deps.referencia)
    elif args.comando == "consulta":
        imprimir_consulta(consultar(deps, args.versao))
    else:  # orfaos, julgar-orfao e reconstruir-estado (argparse ja validou)
        _despachar_orfaos(args, deps)
    logging.debug(
        "comando '%s' concluido em %.3fs", args.comando, time.monotonic() - inicio
    )


def _despachar_orfaos(args: argparse.Namespace, deps: Deps) -> None:
    if args.comando == "orfaos":
        imprimir_orfaos(listar_orfaos(deps, args.versao))
    elif args.comando == "julgar-orfao":
        j = julgar_orfao(
            deps,
            args.versao,
            args.hash,
            None if args.nenhum else args.chamado,
            args.motivo,
        )
        print(f"julgado: {j.hash_origem[:8]} -> {j.chamado or 'nenhum'}")
    else:  # reconstruir-estado (unico comando restante)
        resultado = reconstruir_estado(deps, args.versao)
        print(f"status: {resultado.status.name}, orfaos: {len(resultado.orfaos)}")
        for hash_ in resultado.orfaos:
            print(f"  - {hash_[:8]} (sem referencia de tarefa na mensagem)")
        if resultado.orfaos:
            print(
                f"julgue com: motor julgar-orfao {args.versao} <hash> "
                f"--repo {args.repo} (--chamado ID | --nenhum) --motivo TEXTO"
            )


def _migrar_estado(args: argparse.Namespace) -> None:
    # Sem abrir_sessao nem database_url(): as URLs vem so dos argumentos.
    resumo = migrar_estado(args.de, args.para)
    for tabela, n in resumo.linhas.items():
        print(f"{tabela}: {n}")
    print(f"estado copiado: {resumo.total} linhas")


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        erro_central = _carregar_ambiente(argv)
    except MotorError as e:
        print(f"ERROR: {formatar_com_notas(e)}", file=sys.stderr)
        sys.exit(1)

    args = _build_parser().parse_args(argv)
    args.erro_central = erro_central

    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "debug", False) else logging.ERROR,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        if getattr(args, "debug", False)
        else "%(levelname)s: %(message)s",
    )

    # Antes de abrir o banco: erro de flag nao depende de conexao, e conectar
    # primeiro esconderia a flag errada atras de um "banco inacessivel".
    if getattr(args, "fonte_flag", None) == "manual" and not args.lista_manual:
        print("--lista e obrigatorio quando --task-source=manual", file=sys.stderr)
        sys.exit(1)

    try:
        if args.comando == "serve":
            _iniciar_serve(args.porta)
            return

        if args.comando == "tui":
            _iniciar_tui()
            return

        if args.comando in _SEM_BANCO:
            _SEM_BANCO[args.comando](args)
            return

        if args.comando == "migrar-estado":
            _migrar_estado(args)
            return

        with abrir_sessao() as sessao:
            relator = _relator_do_cli(desligado=getattr(args, "sem_progresso", False))
            deps = montar_deps(
                args.repo,
                sessao,
                tasks=FonteTasks(args.fonte_flag, args.lista_manual),
                bitbucket=CredenciaisBitbucket(
                    getattr(args, "bitbucket_token", ""),
                    getattr(args, "bitbucket_email", ""),
                ),
                progresso=relator,
            )
            try:
                _despachar(args, deps)
            finally:
                # No finally: erro no meio do comando tambem tem de limpar a
                # linha, senao a mensagem de erro sai colada na barra.
                _limpar_progresso(relator)
    except MotorError as e:
        logging.error(formatar_com_notas(e))
        sys.exit(1)
    except Exception:
        logging.exception("Erro interno fatal (bug). Traceback completo:")
        sys.exit(1)


if __name__ == "__main__":
    main()
