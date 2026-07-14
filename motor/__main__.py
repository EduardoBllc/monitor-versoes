"""Porte de cmd/motor/main.go.

CLI fina: so parseia argumentos, monta Deps e chama o engine. Sem logica de
dominio aqui.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

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
from motor.engine.incrementar import (
    IncrementResult,
    IncrementStatus,
    incrementar,
    incrementar_abort,
    incrementar_continue,
)
from motor.engine.reconstruir_lock import reconstruir_lock
from motor.engine.verificar import verificar


def _go_bool(b: bool) -> str:
    return "true" if b else "false"


def _go_list(itens: list[str]) -> str:
    return "[" + " ".join(itens) + "]"


def _build_parser() -> argparse.ArgumentParser:
    """Espelha flag.NewFlagSet(comando, ...) do Go: o mesmo conjunto de
    flags existe pra todo comando (o Go nunca varia o flagset por comando).

    Um unico parser flat (sem subparsers): `comando` nao usa `choices=` pra
    que um comando desconhecido nao vire erro do argparse - ele precisa
    seguir adiante ate o dispatch em main(), onde cai no `else` (equivalente
    ao `default` do switch do Go), depois de repo/git ja terem sido validados.
    """
    parser = argparse.ArgumentParser(prog="motor", add_help=False)
    parser.add_argument("comando")
    parser.add_argument("versao")
    parser.add_argument("--repo", default="")
    parser.add_argument("--task-source", dest="fonte_flag", default="rest")
    parser.add_argument("--lista", dest="lista_manual", default="")
    parser.add_argument(
        "--clickup-token", dest="token", default=os.environ.get("CLICKUP_TOKEN", "")
    )
    parser.add_argument("--continue", dest="continuar", action="store_true")
    parser.add_argument("--abort", dest="abortar", action="store_true")

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


def imprimir_uso() -> None:
    print(
        """uso:
  motor verificar        <X.Y.Z> --repo <path>
  motor criar             <X.Y.Z> --repo <path> [--task-source=rest|manual (default: rest) --clickup-token=...] [--lista=arquivo]
  motor incrementar      <X.Y.Z> --repo <path> [--continue | --abort]
  motor reconstruir-lock <X.Y.Z> --repo <path>""",
        file=sys.stderr,
    )


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
    print(f"verde: {_go_bool(s.verde)}")
    print(f"tasks novas: {_go_list(s.tasks_novas)}")
    print(f"tasks removidas: {_go_list(s.tasks_removidas)}")
    if not s.lock_integro:
        print(f"lock: divergente do git ({len(s.commits_sumidos)} commits sumidos)")
        for hash_ in s.commits_sumidos:
            print(f"  - {hash_[:8]}")
    else:
        print("lock: integro")
    conflitantes = {c.hash_origem for c in s.conflitantes}
    _imprimir_commits_por_task("faltantes", s.faltantes, conflitantes)


def imprimir_incremento(r: IncrementResult) -> None:
    if r.status == IncrementStatus.BLOCKED:
        print(f"BLOQUEADO em {r.blocked_commit}, arquivos: {_go_list(r.arquivos_conflito)}")
        print("resolva e rode: motor incrementar <versao> --repo <path> --continue")
        return
    print("concluido")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if load_dotenv:
        load_dotenv()

    argv = list(sys.argv[1:] if argv is None else argv)

    if len(argv) < 2:
        # Espelha `if len(os.Args) < 3` do Go: so checa aridade (comando +
        # versao), nao valida se o comando existe - isso fica pro dispatch
        # em main(), depois de repo/git ja terem sido validados.
        imprimir_uso()
        sys.exit(1)

    args = _build_parser().parse_args(argv)

    if args.repo == "":
        print("--repo e obrigatorio", file=sys.stderr)
        sys.exit(1)

    repo = _resolver_repo(args.repo)

    try:
        git_repo = new_git_subprocess(repo)

        if args.fonte_flag == "rest":
            tasks = ClickUpRest(token=args.token)
        else:
            if not args.lista_manual:
                print("--lista e obrigatorio quando --task-source=manual (ou use --task-source=rest para ClickUp)", file=sys.stderr)
                sys.exit(1)
            tasks = ManualList(caminho=args.lista_manual)

        motor_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target_repo_name = os.path.basename(repo)
        lock_dir = os.path.join(motor_root, "locks", target_repo_name)

        deps = Deps(git=git_repo, tasks=tasks, lock_dir=lock_dir)

        if args.comando == "verificar":
            status = verificar(deps, args.versao)
            imprimir_status(status)
        elif args.comando == "criar":
            resultado = criar(deps, args.versao)
            imprimir_incremento(resultado)
        elif args.comando == "incrementar":
            if args.continuar:
                resultado = incrementar_continue(deps, args.versao)
            elif args.abortar:
                incrementar_abort(deps, args.versao)
                resultado = None
            else:
                resultado = incrementar(deps, args.versao)
            if not args.abortar:
                imprimir_incremento(resultado)
        elif args.comando == "reconstruir-lock":
            resultado = reconstruir_lock(deps, args.versao)
            print(f"status: {resultado.status}, orfaos: {len(resultado.orfaos)}")
        else:
            # Equivalente ao `default` do switch em main.go: comando
            # desconhecido chega aqui SO depois de repo/git ja validados,
            # igual ao Go (mesmo flagset, mesma ordem de checagem).
            imprimir_uso()
            sys.exit(1)
    except MotorError as e:
        logging.error(str(e))
        sys.exit(1)
    except Exception:
        logging.exception("Erro interno fatal (bug). Traceback completo:")
        sys.exit(1)


if __name__ == "__main__":
    main()
