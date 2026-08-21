"""Conformidade dos adapters com as portas — verificada pelo type checker.

`Protocol` e estrutural: o mypy so confere conformidade em **ponto de
atribuicao**. Sem um arquivo como este, a cobertura era acidental — vinha das
construcoes de `Deps` espalhadas pela suite, e desaparecia no dia em que um
teste parasse de passar o fake adiante.

As declaracoes abaixo nao rodam assercao nenhuma. Elas existem para o
`mypy motor tests` falhar quando um adapter divergir da porta. Verificado
removendo `patch_id` do `FakeGit`: o erro sai aqui, na linha da lista.

**O que isto NAO pega:** renome de parametro, com o tipo mantido
(`patch_id(self, hash_do_commit: str)` no lugar de `hash: str`). O mypy aceita,
porque toda chamada de porta no projeto e posicional. Vale saber antes de
chamar porta com argumento nomeado — e antes de prometer isso a um adapter de
fora. Pega: metodo faltando, tipo de parametro trocado, retorno trocado.

O `test_estado_contrato.py` cobre o outro lado — o **comportamento** que a
assinatura nao expressa.

Este e tambem o modelo que um adapter de fora copia: declare o seu ao lado dos
nossos e rode o checker.
"""

from __future__ import annotations

import pytest

from motor.adapters.commitsource.bitbucket import BitbucketPRCommitSource
from motor.adapters.commitsource.chain import ChainCommitSource
from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.commitsource.grep import GrepCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.estado.postgres import PostgresEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.git.subprocess import GitSubprocess
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.adapters.tasksource.manuallist import ManualList
from motor.adapters.tasksource.tickio import TickioRest
from motor.ports import CommitSource, EstadoRepo, GitRepo, TaskSource

# O fake entra junto com o real de proposito: fake mais permissivo que o
# adapter deixa a suite verde num caminho que quebra em producao, e este
# projeto ja pagou por isso tres vezes.
_GIT: list[type[GitRepo]] = [GitSubprocess, FakeGit]
_ESTADO: list[type[EstadoRepo]] = [PostgresEstado, FakeEstado]
_TASKS: list[type[TaskSource]] = [TickioRest, ManualList, FakeTaskSource]
_COMMITS: list[type[CommitSource]] = [
    BitbucketPRCommitSource,
    GrepCommitSource,
    ChainCommitSource,
    FakeCommitSource,
]


def test_todo_adapter_esta_declarado_na_sua_porta() -> None:
    """A checagem de verdade e estatica; isto so impede o arquivo de virar
    codigo morto que ninguem executa nem importa.
    """
    assert [len(_GIT), len(_ESTADO), len(_TASKS), len(_COMMITS)] == [2, 2, 3, 4]


def test_porta_nao_aceita_argumento_nomeado() -> None:
    """Os parametros das portas sao posicionais, de proposito.

    O mypy nao pega renome de parametro num adapter (verificado no sub-projeto
    A: remover metodo acusa, renomear parametro passa). Como nenhum chamador
    passa por nome, marcar posicional torna o renome explicitamente permitido —
    o adapter de terceiro nomeia como quiser — e fecha a lacuna em vez de
    documenta-la.
    """
    fake = FakeGit()

    with pytest.raises(TypeError, match="positional"):
        fake.is_ancestor(commit="abc", branch="13.34.0")  # type: ignore[call-arg]
