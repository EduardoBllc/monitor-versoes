"""Porte de cmd/motor/main.go.

CLI fina: so parseia argumentos, monta Deps e chama o engine. Sem logica de
dominio aqui.
"""

from __future__ import annotations

import argparse
import os
import sys

from motor.adapters.git.subprocess import new_git_subprocess
from motor.adapters.tasksource.manuallist import ManualList
from motor.adapters.tasksource.rest import ClickUpRest
from motor.domain.types import VersionStatus
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

_COMANDOS = ("verificar", "criar", "incrementar", "reconstruir-lock")


def _go_bool(b: bool) -> str:
    return "true" if b else "false"


def _go_list(itens: list[str]) -> str:
    return "[" + " ".join(itens) + "]"


def _build_parser() -> argparse.ArgumentParser:
    """Espelha flag.NewFlagSet(comando, ...) do Go: o mesmo conjunto de
    flags existe pra todo comando (o Go nunca varia o flagset por comando).
    """
    parser = argparse.ArgumentParser(prog="motor", add_help=False)
    sub = parser.add_subparsers(dest="comando")

    for nome in _COMANDOS:
        sp = sub.add_parser(nome, add_help=False)
        sp.add_argument("versao")
        sp.add_argument("--repo", default="")
        sp.add_argument("--task-source", dest="fonte_flag", default="manual")
        sp.add_argument("--lista", dest="lista_manual", default="")
        sp.add_argument(
            "--clickup-token", dest="token", default=os.environ.get("CLICKUP_TOKEN", "")
        )
        sp.add_argument("--clickup-team", dest="team_id", default="")
        sp.add_argument("--clickup-campo-chamado", dest="campo_chamado", default="")
        sp.add_argument("--continue", dest="continuar", action="store_true")
        sp.add_argument("--abort", dest="abortar", action="store_true")

    return parser


def imprimir_uso() -> None:
    print(
        """uso:
  motor verificar        <X.Y.Z> --repo <path>
  motor criar             <X.Y.Z> --repo <path> [--task-source=rest|manual --clickup-token=... --clickup-team=... --clickup-campo-chamado=...] [--lista=arquivo]
  motor incrementar      <X.Y.Z> --repo <path> [--continue | --abort]
  motor reconstruir-lock <X.Y.Z> --repo <path>""",
        file=sys.stderr,
    )


def imprimir_status(s: VersionStatus) -> None:
    print(f"verde: {_go_bool(s.verde)}")
    print(f"tasks novas: {_go_list(s.tasks_novas)}")
    print(f"tasks removidas: {_go_list(s.tasks_removidas)}")
    print(f"lock integro: {_go_bool(s.lock_integro)}")
    print(f"commits sumidos: {_go_list(s.commits_sumidos)}")
    print(f"faltantes: {len(s.faltantes)}")
    print(f"conflitantes: {len(s.conflitantes)}")


def imprimir_incremento(r: IncrementResult) -> None:
    if r.status == IncrementStatus.BLOCKED:
        print(f"BLOQUEADO em {r.blocked_commit}, arquivos: {_go_list(r.arquivos_conflito)}")
        print("resolva e rode: motor incrementar <versao> --repo <path> --continue")
        return
    print("concluido")


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)

    if len(argv) < 2 or argv[0] not in _COMANDOS:
        # ponytail: Go ainda constroi o GitRepo antes de bater no `default` do
        # switch pra comando desconhecido; sem teste cobrindo isso, aqui a
        # validacao de comando sai mais cedo - mesmo resultado observavel
        # (usa e exit 1) pro caso que importa.
        imprimir_uso()
        sys.exit(1)

    args = _build_parser().parse_args(argv)

    if args.repo == "":
        print("--repo e obrigatorio", file=sys.stderr)
        sys.exit(1)

    try:
        git_repo = new_git_subprocess(args.repo)

        if args.fonte_flag == "rest":
            tasks = ClickUpRest(team_id=args.team_id, token=args.token, campo_chamado_id=args.campo_chamado)
        else:
            tasks = ManualList(caminho=args.lista_manual)

        deps = Deps(git=git_repo, tasks=tasks)

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
        else:  # reconstruir-lock
            resultado = reconstruir_lock(deps, args.versao)
            print(f"status: {resultado.status}, orfaos: {len(resultado.orfaos)}")
    except Exception as e:
        # ponytail: Go's checar(err) trata qualquer error, nao so um tipo
        # especifico - MotorError e o caminho esperado, mas alguns adapters
        # (ex.: subprocess com cwd inexistente) ainda escapam com excecoes
        # nativas do Python (OSError) em vez de MotorError. Captura ampla
        # aqui reproduz a garantia do Go de nunca vazar stacktrace pro usuario.
        print("erro:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
