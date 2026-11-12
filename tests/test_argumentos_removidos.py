"""Argumentos que sairam do CLI (com o Tickio e com o Postgres) e continuam recusados.

Este arquivo nomeia o que saiu de proposito: e uma das excecoes listadas no
teste de nucleo neutro (tests/test_nucleo_neutro.py).
"""

from __future__ import annotations

import pytest

from motor.__main__ import _build_parser


def test_task_source_tickio_e_erro_de_argumento():
    with pytest.raises(SystemExit) as saida:
        _build_parser().parse_args(
            ["criar", "1.0.0", "--repo", ".", "--task-source", "tickio"]
        )

    assert saida.value.code == 2


def test_nao_existe_flag_de_token_do_tickio():
    # credencial de fonte de tarefas vem do ambiente, lida pelo plugin: token
    # colado em flag nao existe.
    with pytest.raises(SystemExit):
        _build_parser().parse_args(
            ["criar", "1.0.0", "--repo", ".", "--tickio-token", "xyz"]
        )


def test_repo_adicionar_recusa_tickio_sistema_id():
    with pytest.raises(SystemExit) as saida:
        _build_parser().parse_args(
            ["repo", "adicionar", "backend", "--tickio-sistema-id", "42"]
        )

    assert saida.value.code == 2


@pytest.mark.parametrize(
    "argv", [["init"], ["migrar-estado", "--de", "x", "--para", "y"]]
)
def test_comandos_do_postgres_sairam(argv):
    with pytest.raises(SystemExit) as saida:
        _build_parser().parse_args(argv)

    assert saida.value.code == 2
