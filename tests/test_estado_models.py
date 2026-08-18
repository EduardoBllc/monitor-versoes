from __future__ import annotations

from motor.adapters.estado.models import Base


def test_metadata_tem_todas_as_tabelas():
    assert set(Base.metadata.tables) == {
        "repo",
        "repo_alias",
        "versao",
        "atribuicao",
        "atribuicao_commit",
        "exclusao",
        "sem_entrega",
    }


def test_naming_convention_esta_configurada():
    # Sem isso o autogenerate nomeia constraints por reflexao e as migracoes
    # de indice/FK ficam instaveis entre maquinas.
    assert "pk" in Base.metadata.naming_convention
    assert "fk" in Base.metadata.naming_convention


def test_dominio_nao_importa_sqlalchemy():
    # A regra que sustenta a suite sem banco: modelo ORM so no adapter.
    import pathlib

    dominio = pathlib.Path("motor/domain")
    for arquivo in dominio.glob("*.py"):
        assert "sqlalchemy" not in arquivo.read_text(encoding="utf-8"), arquivo
