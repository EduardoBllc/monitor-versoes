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

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from motor.adapters.git.subprocess import new_git_subprocess
from motor.adapters.tasksource.manuallist import ManualList
from motor.adapters.tasksource.rest import ClickUpRest
from motor.domain.types import VersionStatus
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
from motor.engine.reconstruir_lock import reconstruir_lock
from motor.engine.verificar import verificar


def _build_parser() -> argparse.ArgumentParser:
    """Um subparser por comando: `motor -h` lista os comandos e
    `motor <comando> -h` mostra so as flags daquele comando (help nativo do
    argparse). Flags compartilhadas (--repo, --debug) vivem num parent parser.
    """
    comum = argparse.ArgumentParser(add_help=False)
    comum.add_argument("versao", help="versao alvo no formato X.Y.Z")
    comum.add_argument("--repo", required=True, help="path do repo ou nome dentro de PROJECTS_DIR")
    comum.add_argument("--debug", action="store_true", help="loga tempos de cada etapa/comando git")

    parser = argparse.ArgumentParser(prog="motor")
    sub = parser.add_subparsers(dest="comando", required=True, metavar="comando")

    sub.add_parser("verificar", parents=[comum], help="mostra status da versao (verde, tasks, faltantes)")

    p_criar = sub.add_parser("criar", parents=[comum], help="cria a branch da versao a partir das tasks")
    p_criar.add_argument("--task-source", dest="fonte_flag", default="rest", choices=["rest", "manual"], help="fonte das tasks (default: rest = ClickUp)")
    p_criar.add_argument("--lista", dest="lista_manual", default="", help="arquivo de lista (obrigatorio com --task-source=manual)")
    p_criar.add_argument("--clickup-token", dest="token", default=os.environ.get("CLICKUP_TOKEN", ""), help="token ClickUp (default: $CLICKUP_TOKEN)")

    p_inc = sub.add_parser("atualizar", parents=[comum], help="aplica commits faltantes na branch da versao")
    grupo = p_inc.add_mutually_exclusive_group()
    grupo.add_argument("--continue", dest="continuar", action="store_true", help="retoma apos resolver conflito")
    grupo.add_argument("--abort", dest="abortar", action="store_true", help="aborta o incremento em andamento")

    sub.add_parser("reconstruir-lock", parents=[comum], help="regenera o lock a partir do git")

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
            return candidato

    print(
        f"--repo nao encontrado: tentou '{valor}' e '{os.path.join(projects_dir, valor) if projects_dir else '(PROJECTS_DIR nao setada)'}'",
        file=sys.stderr,
    )
    sys.exit(1)


def _agrupar_por_task(commits: list) -> dict[str, list]:
    """Agrupa preservando a ordem de 1a aparicao de cada task."""
    grupos: dict[str, list] = {}
    for c in commits:
        chave = f"{c.chamado} {c.task}".strip() or c.hash_origem[:8]
        grupos.setdefault(chave, []).append(c)
    return grupos


def _imprimir_commits_por_task(titulo: str, commits: list, conflitantes: set[str]) -> None:
    grupos = _agrupar_por_task(commits)
    print(f"{titulo} ({len(commits)} em {len(grupos)} tasks):")
    for chave, itens in grupos.items():
        print(f"  {chave}:")
        for c in itens:
            primeira_linha_msg = c.msg.splitlines()[0] if c.msg else ""
            tag = " [CONFLITANTE]" if c.hash_origem in conflitantes else ""
            print(f"    - {c.hash_origem[:8]} {primeira_linha_msg}{tag}".rstrip())


def imprimir_status(s: VersionStatus) -> None:
    print(f"verde: {s.verde}")
    print(f"tasks novas: {s.tasks_novas}")
    print(f"tasks removidas: {s.tasks_removidas}")
    if not s.lock_integro:
        print(f"lock: divergente do git ({len(s.commits_sumidos)} commits sumidos)")
        for hash_ in s.commits_sumidos:
            print(f"  - {hash_[:8]}")
    else:
        print("lock: integro")
    conflitantes = {c.hash_origem for c in s.conflitantes}
    _imprimir_commits_por_task("faltantes", s.faltantes, conflitantes)


def imprimir_atualizacao(r: AtualizarResult) -> None:
    if r.aplicados:
        _imprimir_commits_por_task("cherry-picks aplicados", r.aplicados, set())
    else:
        print("nenhum cherry-pick (branch ja atualizada)")
    if r.ja_presentes:
        print(f"{r.ja_presentes} commits ja presentes no historico (ignorados)")

    if r.status == AtualizarStatus.BLOCKED:
        print(f"BLOQUEADO em {r.blocked_commit[:8]}, arquivos: {r.arquivos_conflito}")
        print("resolva e rode: motor atualizar <versao> --repo <path> --continue")
        return
    print("concluido")


def main(argv: list[str] | None = None) -> None:
    if load_dotenv:
        load_dotenv()

    argv = list(sys.argv[1:] if argv is None else argv)

    args = _build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.ERROR,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s" if args.debug else "%(levelname)s: %(message)s",
    )

    repo = _resolver_repo(args.repo)

    try:
        git_repo = new_git_subprocess(repo)

        # fonte_flag/token/lista_manual so existem no subparser 'criar';
        # os demais comandos usam ClickUp (rest) por default.
        if getattr(args, "fonte_flag", "rest") == "rest":
            tasks = ClickUpRest(token=getattr(args, "token", os.environ.get("CLICKUP_TOKEN", "")))
        else:
            if not args.lista_manual:
                print("--lista e obrigatorio quando --task-source=manual (ou use --task-source=rest para ClickUp)", file=sys.stderr)
                sys.exit(1)
            tasks = ManualList(caminho=args.lista_manual)

        motor_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target_repo_name = os.path.basename(repo)
        lock_dir = os.path.join(motor_root, "locks", target_repo_name)

        deps = Deps(git=git_repo, tasks=tasks, lock_dir=lock_dir)

        inicio = time.monotonic()
        if args.comando == "verificar":
            status = verificar(deps, args.versao)
            imprimir_status(status)
        elif args.comando == "criar":
            resultado = criar(deps, args.versao)
            imprimir_atualizacao(resultado)
        elif args.comando == "atualizar":
            if args.abortar:
                atualizar_abort(deps, args.versao)
                print("abortado")
            elif args.continuar:
                imprimir_atualizacao(atualizar_continue(deps, args.versao))
            else:
                imprimir_atualizacao(atualizar(deps, args.versao))
        else:  # reconstruir-lock (unico comando restante; argparse ja validou)
            resultado = reconstruir_lock(deps, args.versao)
            print(f"status: {resultado.status}, orfaos: {len(resultado.orfaos)}")
        logging.debug("comando '%s' concluido em %.3fs", args.comando, time.monotonic() - inicio)
    except MotorError as e:
        logging.error(str(e))
        sys.exit(1)
    except Exception:
        logging.exception("Erro interno fatal (bug). Traceback completo:")
        sys.exit(1)


if __name__ == "__main__":
    main()
