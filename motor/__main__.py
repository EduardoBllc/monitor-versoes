"""Porte de cmd/motor/main.go.

CLI fina: so parseia argumentos, monta Deps e chama o engine. Sem logica de
dominio aqui.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from motor.adapters.estado.postgres import PostgresEstado
from motor.adapters.git.subprocess import new_git_subprocess
from motor.adapters.tasksource.manuallist import ManualList
from motor.adapters.tasksource.tickio import TickioRest
from motor.config import database_url
from motor.domain.types import RepoInfo, VersionStatus
from motor.errors import MotorError
from motor.engine.criar import criar
from motor.engine.deps import Deps
from motor.engine.atualizar import (
    AtualizarResult,
    AtualizarStatus,
    atualizar,
    atualizar_abort,
    atualizar_continue,
)
from motor.engine.reconstruir_estado import reconstruir_estado
from motor.engine.verificar import verificar
from motor.ports import TaskSource

_ARQUIVOS_AMBIENTE = {
    "development": ".env.development",
    "production": ".env",
}


def _carregar_ambiente(argv: list[str]) -> None:
    seletor = argparse.ArgumentParser(add_help=False)
    seletor.add_argument("--env", choices=_ARQUIVOS_AMBIENTE,
                         default="development")
    ambiente = seletor.parse_known_args(argv)[0].env
    if load_dotenv:
        raiz = os.path.dirname(os.path.dirname(__file__))
        load_dotenv(os.path.join(raiz, _ARQUIVOS_AMBIENTE[ambiente]),
                    override=True)


def _build_parser() -> argparse.ArgumentParser:
    """Um subparser por comando: `motor -h` lista os comandos e
    `motor <comando> -h` mostra so as flags daquele comando (help nativo do
    argparse). Flags compartilhadas (--repo, --debug) vivem num parent parser.
    """
    comum = argparse.ArgumentParser(add_help=False)
    comum.add_argument("versao", help="versao alvo no formato X.Y.Z")
    comum.add_argument("--repo", required=True, help="path do repo ou nome dentro de PROJECTS_DIR")
    comum.add_argument("--debug", action="store_true", help="loga tempos de cada etapa/comando git")
    comum.add_argument("--bitbucket-token", dest="bitbucket_token", default=os.environ.get("BITBUCKET_TOKEN", ""), help="token Bitbucket Cloud (default: $BITBUCKET_TOKEN); ativa descoberta de commits por PR")
    comum.add_argument("--bitbucket-email", dest="bitbucket_email", default=os.environ.get("BITBUCKET_EMAIL", ""), help="email da conta dona do token Bitbucket (default: $BITBUCKET_EMAIL)")
    # No parser pai, nao no 'criar': todos os comandos montam a fonte de tasks
    # (o Deps e um so), e uma flag exclusiva do 'criar' viraria AttributeError
    # nos outros.
    comum.add_argument("--task-source", dest="fonte_flag", default="tickio",
                       choices=["tickio", "manual"],
                       help="fonte das tasks (default: tickio)")
    comum.add_argument("--lista", dest="lista_manual", default="", help="arquivo de lista (obrigatorio com --task-source=manual)")

    parser = argparse.ArgumentParser(prog="motor")
    parser.add_argument("--env", choices=_ARQUIVOS_AMBIENTE,
                        default="development",
                        help="ambiente (default: development)")
    sub = parser.add_subparsers(dest="comando", required=True, metavar="comando")

    sub.add_parser("verificar", parents=[comum], help="mostra status da versao (verde, tasks, faltantes)")

    sub.add_parser("criar", parents=[comum], help="cria a branch da versao a partir das tasks")

    p_inc = sub.add_parser("atualizar", parents=[comum], help="aplica commits faltantes na branch da versao")
    grupo = p_inc.add_mutually_exclusive_group()
    grupo.add_argument("--continue", dest="continuar", action="store_true", help="retoma apos resolver conflito")
    grupo.add_argument("--abort", dest="abortar", action="store_true", help="aborta o incremento em andamento")

    sub.add_parser("reconstruir-estado", parents=[comum],
                   help="regenera as atribuicoes a partir do git")

    return parser


def _resolver_repo(valor: str) -> str:
    """Resolve --repo: caminho literal existente tem prioridade; senao tenta
    PROJECTS_DIR/valor (ex: PROJECTS_DIR=/Volumes/ESSD/Projetos/ + --repo=foo)."""
    if os.path.isdir(valor):
        return os.path.abspath(valor)

    projects_dir = os.environ.get("PROJECTS_DIR", "")
    if projects_dir:
        candidato = os.path.join(projects_dir, valor)
        if os.path.isdir(candidato):
            # abspath tambem tira a barra final que o tab-completion do shell
            # anexa: o basename de "repo/" e "", e esse nome e a chave do estado.
            return os.path.abspath(candidato)

    print(
        f"--repo nao encontrado: tentou '{valor}' e '{os.path.join(projects_dir, valor) if projects_dir else '(PROJECTS_DIR nao setada)'}'",
        file=sys.stderr,
    )
    sys.exit(1)


def _agrupar_por_task(commits: list) -> dict[str, list]:
    """Agrupa preservando a ordem de 1a aparicao de cada chamado."""
    grupos: dict[str, list] = {}
    for c in commits:
        chave = c.chamado or c.hash_origem[:8]
        grupos.setdefault(chave, []).append(c)
    return grupos


def _imprimir_commits_por_task(
    titulo: str, commits: list, conflitantes: set[str], suspeitos: set[str] = frozenset()
) -> None:
    grupos = _agrupar_por_task(commits)
    print(f"{titulo} ({len(commits)} em {len(grupos)} tasks):")
    for chave, itens in grupos.items():
        print(f"  {chave}:")
        for c in itens:
            primeira_linha_msg = c.msg.splitlines()[0] if c.msg else ""
            tag = " [CONFLITANTE]" if c.hash_origem in conflitantes else ""
            tag += " [SUSPEITO: msg+arquivos ja existem no alvo com conteudo diferente]" if c.hash_origem in suspeitos else ""
            print(f"    - {c.hash_origem[:8]} {primeira_linha_msg}{tag}".rstrip())


def _imprimir_alertas(s: VersionStatus) -> None:
    """As secoes vermelhas do status. Vive separada porque o `atualizar` tambem
    tem de imprimi-las: sao computadas, derrubam o verde e antes nao chegavam a
    lugar nenhum no caminho do atualizar.
    """
    if s.tasks_ambiguas:
        print(f"tasks marcadas em mais de uma versao: {s.tasks_ambiguas}")
        print("  (dado inconsistente no Tickio - corrija a marcacao)")
    if s.tasks_sem_commits:
        print(f"tasks sem commits: {s.tasks_sem_commits}")
        print("  (nenhum commit/PR achado - registre em sem_entrega se for proposital)")
    if not s.estado_integro:
        print(f"estado: divergente do git ({len(s.commits_sumidos)} commits sumidos)")
        for hash_ in s.commits_sumidos:
            print(f"  - {hash_[:8]}")


def imprimir_status(s: VersionStatus) -> None:
    if s.liberada_em is not None:
        # Snapshot de versao liberada (spec §4): nada foi recalculado, e sem
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
    _imprimir_commits_por_task("faltantes", s.faltantes, conflitantes, suspeitos)


def imprimir_atualizacao(r: AtualizarResult) -> None:
    if r.aplicados:
        _imprimir_commits_por_task("cherry-picks aplicados", r.aplicados, set())
    else:
        print("nenhum cherry-pick (branch ja atualizada)")
    if r.ja_presentes:
        print(f"{r.ja_presentes} commits ja presentes no historico (ignorados)")

    # Antes do "concluido": o lote e empurrado mesmo sem verde, mas o operador
    # tem de ficar sabendo do que o verificar viu.
    if r.status_versao is not None:
        _imprimir_alertas(r.status_versao)

    if r.status == AtualizarStatus.BLOCKED:
        print(f"BLOQUEADO em {r.blocked_commit[:8]}, arquivos: {r.arquivos_conflito}")
        print("resolva e rode: motor atualizar <versao> --repo <path> --continue")
        return
    print("concluido")


@contextmanager
def _abrir_sessao():
    """Ciclo de vida do banco: uma engine e uma sessao por comando.

    O CLI e um processo de segundos, entao nao ha o que reaproveitar de um pool
    — a engine nasce aqui, e descartada no fim e a sessao fecha com o `with`.
    Nada disso vive em nivel de modulo: a suite roda sem banco, e uma sessao
    montada no import (ou na construcao do parser) exigiria banco de pe so
    para rodar `--help`.
    """
    engine = create_engine(database_url())
    try:
        with Session(engine) as sessao:
            yield sessao
    finally:
        engine.dispose()


def _montar_task_source(args: argparse.Namespace, info: RepoInfo) -> TaskSource:
    """A fonte de tasks depende do repo: o sistema_id do Tickio sai da linha
    `repo` do banco, lida antes daqui via EstadoRepo.resolver_repo."""
    if args.fonte_flag == "tickio":
        # Sem validar as variaveis aqui: montar nao e usar. `atualizar --abort`
        # e `reconstruir-estado` recebem esta fonte e nunca chamam fetch — quem
        # cobra credencial e o TickioRest, na primeira busca.
        return TickioRest(
            base_url=os.environ.get("TICKIO_BASE_URL", ""),
            usuario=os.environ.get("TICKIO_USER", ""),
            senha=os.environ.get("TICKIO_PASSWORD", ""),
            sistema_id=info.tickio_sistema_id,
        )
    return ManualList(caminho=args.lista_manual)


def _despachar(args: argparse.Namespace, deps: Deps) -> None:
    inicio = time.monotonic()
    if args.comando == "verificar":
        imprimir_status(verificar(deps, args.versao))
    elif args.comando == "criar":
        imprimir_atualizacao(criar(deps, args.versao))
    elif args.comando == "atualizar":
        if args.abortar:
            atualizar_abort(deps, args.versao)
            print("abortado")
        elif args.continuar:
            imprimir_atualizacao(atualizar_continue(deps, args.versao))
        else:
            imprimir_atualizacao(atualizar(deps, args.versao))
    else:  # reconstruir-estado (unico comando restante; argparse ja validou)
        resultado = reconstruir_estado(deps, args.versao)
        print(f"status: {resultado.status.name}, orfaos: {len(resultado.orfaos)}")
        for hash_ in resultado.orfaos:
            print(f"  - {hash_[:8]} (sem ch<num> na mensagem)")
    logging.debug("comando '%s' concluido em %.3fs", args.comando,
                  time.monotonic() - inicio)


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    _carregar_ambiente(argv)

    args = _build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.ERROR,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s" if args.debug else "%(levelname)s: %(message)s",
    )

    # Antes de abrir o banco: erro de flag nao depende de conexao, e conectar
    # primeiro esconderia a flag errada atras de um "banco inacessivel".
    if args.fonte_flag == "manual" and not args.lista_manual:
        print("--lista e obrigatorio quando --task-source=manual", file=sys.stderr)
        sys.exit(1)

    repo = _resolver_repo(args.repo)

    try:
        git_repo = new_git_subprocess(repo)

        with _abrir_sessao() as sessao:
            estado = PostgresEstado(sessao=sessao)
            # O estado vem antes da fonte de tasks: o nome canonico do repo e o
            # tickio_sistema_id saem da linha `repo` (aceita nome ou alias).
            info = estado.resolver_repo(os.path.basename(repo))

            deps = Deps(
                git=git_repo,
                tasks=_montar_task_source(args, info),
                estado=estado,
                repo=info.nome,
                bitbucket_token=getattr(args, "bitbucket_token", ""),
                bitbucket_email=getattr(args, "bitbucket_email", ""),
            )
            _despachar(args, deps)
    except MotorError as e:
        logging.error(str(e))
        sys.exit(1)
    except Exception:
        logging.exception("Erro interno fatal (bug). Traceback completo:")
        sys.exit(1)


if __name__ == "__main__":
    main()
