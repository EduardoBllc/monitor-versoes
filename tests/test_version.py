"""Porte de internal/domain/version_test.go."""

from motor.domain.version import versoes_abertas, worktrees_a_remover


def test_versoes_abertas_e_branch_sem_tag():
    todas = ["13.33.0", "13.33.1", "13.34.0", "14.0.0"]
    tags = ["13.33.0"]
    assert versoes_abertas(todas, tags) == ["13.33.1", "13.34.0", "14.0.0"]


def test_versoes_abertas_ordena_por_semver_nao_por_texto():
    todas = ["13.10.0", "13.9.0"]
    assert versoes_abertas(todas, []) == ["13.9.0", "13.10.0"]


def test_versoes_abertas_sem_nenhuma_aberta():
    assert versoes_abertas(["13.33.0"], ["13.33.0"]) == []


# --- worktrees_a_remover: politica do GC de worktrees ---
#
# `existentes` sao as worktrees de versao em disco; `mru` e a lista de uso
# recente (mais recente primeiro) lida do arquivo local pelo adapter. A ordem
# aqui e a unica coisa que decide o que morre, entao cada caso abaixo fixa uma
# regra dela.


def test_worktrees_a_remover_mru_manda_sobre_semver():
    # 12.4.0 e a mais antiga por semver, mas foi usada por ultimo: fica.
    remover = worktrees_a_remover(
        ["13.9.0", "13.10.0", "12.4.0"],
        mru=["12.4.0", "13.9.0"],
        manter=2,
        atual="12.4.0",
    )
    assert remover == ["13.10.0"]


def test_worktrees_a_remover_nao_registrada_cai_depois_por_semver_desc():
    # 13.1.0 esta no mru; 13.2.0 e 13.3.0 nao. As desconhecidas entram atras,
    # entre si da mais nova para a mais velha — 13.2.0 e a primeira a sair.
    remover = worktrees_a_remover(
        ["13.1.0", "13.2.0", "13.3.0"], mru=["13.1.0"], manter=2, atual=""
    )
    assert remover == ["13.2.0"]


def test_worktrees_a_remover_preserva_atual_mesmo_sendo_a_mais_antiga():
    # Sem mru nenhum (arquivo ausente): cai em semver desc, mas `atual` e
    # intocavel — a operacao em curso acabou de usar essa worktree.
    remover = worktrees_a_remover(
        ["12.4.0", "14.0.0", "14.1.0"], mru=[], manter=1, atual="12.4.0"
    )
    assert remover == ["14.1.0", "14.0.0"]


def test_worktrees_a_remover_manter_zero_remove_tudo_inclusive_atual():
    # manter=0 e o comportamento antigo do motor: worktree nao sobrevive ao run.
    remover = worktrees_a_remover(
        ["13.1.0", "13.2.0"], mru=["13.2.0"], manter=0, atual="13.2.0"
    )
    assert remover == ["13.2.0", "13.1.0"]


def test_worktrees_a_remover_ignora_mru_de_worktree_que_nao_existe_mais():
    # O arquivo de mru guarda historico; worktree removida continua listada la.
    remover = worktrees_a_remover(
        ["13.1.0"], mru=["13.9.0", "13.1.0"], manter=1, atual=""
    )
    assert remover == []


def test_worktrees_a_remover_nada_quando_manter_cobre_todas():
    remover = worktrees_a_remover(
        ["13.1.0", "13.2.0"], mru=["13.1.0"], manter=5, atual="13.1.0"
    )
    assert remover == []
