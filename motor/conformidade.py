"""Suíte de conformidade de esquema de versão, publicada com o pacote.

Um pacote de esquema de fora (como o `monitor-versoes-vendabem`) a roda contra o
seu, num arquivo de teste próprio:

    from motor.conformidade import ConformidadeEsquema

    class TestMeuEsquema(ConformidadeEsquema):
        esquema_cls = MeuEsquema
        exemplos = ["1.0.0", "1.1.0", "2.0.0"]  # em ordem crescente

`exemplos` vem em ordem crescente e cada um precisa ter base entre os menores
ou na principal. As verificações são funções públicas para que a própria
reprovação seja testável; reprovar é `AssertionError`, como no pytest.
"""

from __future__ import annotations

import datetime
import itertools
from typing import ClassVar

from motor.adapters.git.fake import FakeGit
from motor.ports import EsquemaVersao

#: Principal usada nas verificações: um nome que nenhum esquema confunde com versão.
PRINCIPAL = "principal"


def verificar_ordem(esquema: EsquemaVersao, exemplos: list[str]) -> None:
    """A validação aceita cada exemplo, e a ordem é total: toda permutação
    sai igual aos exemplos, que vêm em ordem crescente."""
    for v in exemplos:
        assert esquema.validar(v) == v, f"validar({v!r}) mudou o numero"
    for permutacao in itertools.permutations(exemplos):
        ordenado = esquema.ordenar(list(permutacao))
        assert ordenado == exemplos, f"ordenar({list(permutacao)}) = {ordenado}"


def verificar_base(esquema: EsquemaVersao, exemplos: list[str]) -> None:
    """A base é uma versão existente (as menores) ou a principal."""
    for i, v in enumerate(exemplos):
        existentes = exemplos[:i]
        base = esquema.base(v, existentes, PRINCIPAL)
        assert base in {*existentes, PRINCIPAL}, (
            f"base({v!r}) = {base!r}, fora de {existentes} e da principal"
        )


def _repo_de_exemplo(exemplos: list[str]) -> FakeGit:
    """Uma branch, uma tag e um commit datado em 2001 por exemplo."""
    git = FakeGit()
    anterior = ""
    for dia, v in enumerate(exemplos, start=1):
        h = f"c{dia}"
        git.add_commit(h, anterior, f"versao {v}", datetime.datetime(2001, 1, dia))
        git.branches[v] = h
        git.tags[v] = True
        git.tag_commits[v] = h
        anterior = h
    git.branches[PRINCIPAL] = anterior
    return git


def verificar_liberacoes(esquema: EsquemaVersao, exemplos: list[str]) -> None:
    """Quando o esquema declara critério de liberação, a data vem do
    repositório: é a de um commit dele, e não muda quando só o relógio muda."""
    git = _repo_de_exemplo(exemplos)
    primeira = esquema.liberacoes(git, list(exemplos))
    if primeira is None:
        return
    datas_do_repo = {c.date for c in git.commits.values()}
    for v, data in primeira.items():
        assert data in datas_do_repo, (
            f"liberacao de {v!r} em {data}: nao e data de commit do repositorio"
        )
    segunda = esquema.liberacoes(git, list(exemplos))
    assert segunda == primeira, "liberacoes mudou sem o repositorio mudar"


class ConformidadeEsquema:
    """Base dos testes de conformidade. O nome não começa com `Test`, então o
    pytest só a coleta pela subclasse que declara o esquema."""

    esquema_cls: ClassVar[type[EsquemaVersao]]
    exemplos: ClassVar[list[str]]

    def test_ordem(self) -> None:
        verificar_ordem(self.esquema_cls(), self.exemplos)

    def test_base(self) -> None:
        verificar_base(self.esquema_cls(), self.exemplos)

    def test_liberacoes(self) -> None:
        verificar_liberacoes(self.esquema_cls(), self.exemplos)
