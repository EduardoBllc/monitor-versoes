"""Porte de internal/domain/version_test.go."""

from motor.domain.version import versoes_abertas


def test_versoes_abertas_e_branch_sem_tag():
    todas = ["13.33.0", "13.33.1", "13.34.0", "14.0.0"]
    tags = ["13.33.0"]
    assert versoes_abertas(todas, tags) == ["13.33.1", "13.34.0", "14.0.0"]


def test_versoes_abertas_ordena_por_semver_nao_por_texto():
    todas = ["13.10.0", "13.9.0"]
    assert versoes_abertas(todas, []) == ["13.9.0", "13.10.0"]


def test_versoes_abertas_sem_nenhuma_aberta():
    assert versoes_abertas(["13.33.0"], ["13.33.0"]) == []
