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
    parser.add_argument("--task-source", dest="fonte_flag", default="manual")
    parser.add_argument("--lista", dest="lista_manual", default="")
    parser.add_argument(
        "--clickup-token", dest="token", default=os.environ.get("CLICKUP_TOKEN", "")
    )
    parser.add_argument("--clickup-team", dest="team_id", default="")
    parser.add_argument("--clickup-campo-chamado", dest="campo_chamado", default="")
    parser.add_argument("--continue", dest="continuar", action="store_true")
    parser.add_argument("--abort", dest="abortar", action="store_true")

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
        elif args.comando == "reconstruir-lock":
            resultado = reconstruir_lock(deps, args.versao)
            print(f"status: {resultado.status}, orfaos: {len(resultado.orfaos)}")
        else:
            # Equivalente ao `default` do switch em main.go: comando
            # desconhecido chega aqui SO depois de repo/git ja validados,
            # igual ao Go (mesmo flagset, mesma ordem de checagem).
            imprimir_uso()
            sys.exit(1)
    except Exception as e:
        # Go's checar(err) trata qualquer error retornado pelas chamadas
        # acima, nao panics. O `except Exception` aqui e estritamente mais
        # amplo: tambem engole bugs de programacao (ex.: AttributeError) que
        # em Go seriam panics nao recuperados - nao ha paridade exata, so a
        # mesma garantia pratica de nao vazar stacktrace pro usuario.
        print("erro:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
