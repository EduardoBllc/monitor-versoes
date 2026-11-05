"""Politica do GC de worktrees.

`existentes` sao as worktrees de versao em disco, da mais recente para a mais
antiga pelo esquema; `mru` e a lista de uso recente (mais recente primeiro)
lida do arquivo local pelo adapter. A ordem aqui e a unica coisa que decide o
que morre, entao cada caso abaixo fixa uma regra dela.
"""

from motor.domain.worktrees import worktrees_a_remover


def test_mru_manda_sobre_a_ordem_recebida():
    # 12.4.0 e a mais antiga, mas foi usada por ultimo: fica.
    remover = worktrees_a_remover(
        ["13.10.0", "13.9.0", "12.4.0"],
        mru=["12.4.0", "13.9.0"],
        manter=2,
        atual="12.4.0",
    )
    assert remover == ["13.10.0"]


def test_nao_registrada_cai_depois_na_ordem_recebida():
    # 13.1.0 esta no mru; 13.3.0 e 13.2.0 nao. As desconhecidas entram atras,
    # entre si na ordem recebida — 13.2.0 vem depois e e a primeira a sair.
    remover = worktrees_a_remover(
        ["13.3.0", "13.2.0", "13.1.0"], mru=["13.1.0"], manter=2, atual=""
    )
    assert remover == ["13.2.0"]


def test_ordem_recebida_nao_e_reordenada():
    # Branches com prefixo nao sao numero: a ordem e a de quem chamou.
    remover = worktrees_a_remover(
        ["release/1.10.0", "release/1.9.0"], mru=[], manter=1, atual=""
    )
    assert remover == ["release/1.9.0"]


def test_preserva_atual_mesmo_sendo_a_mais_antiga():
    # Sem mru nenhum (arquivo ausente): cai na ordem recebida, mas `atual` e
    # intocavel — a operacao em curso acabou de usar essa worktree.
    remover = worktrees_a_remover(
        ["14.1.0", "14.0.0", "12.4.0"], mru=[], manter=1, atual="12.4.0"
    )
    assert remover == ["14.1.0", "14.0.0"]


def test_manter_zero_remove_tudo_inclusive_atual():
    # manter=0 e o comportamento antigo do motor: worktree nao sobrevive ao run.
    remover = worktrees_a_remover(
        ["13.2.0", "13.1.0"], mru=["13.2.0"], manter=0, atual="13.2.0"
    )
    assert remover == ["13.2.0", "13.1.0"]


def test_ignora_mru_de_worktree_que_nao_existe_mais():
    # O arquivo de mru guarda historico; worktree removida continua listada la.
    remover = worktrees_a_remover(
        ["13.1.0"], mru=["13.9.0", "13.1.0"], manter=1, atual=""
    )
    assert remover == []


def test_nada_quando_manter_cobre_todas():
    remover = worktrees_a_remover(
        ["13.2.0", "13.1.0"], mru=["13.1.0"], manter=5, atual="13.1.0"
    )
    assert remover == []
