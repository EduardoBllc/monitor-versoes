from __future__ import annotations

from motor.adapters.estado.models import Base


def test_metadata_tem_todas_as_tabelas():
    assert set(Base.metadata.tables) == {
        "repo",
        "versao",
        "atribuicao",
        "atribuicao_commit",
        "exclusao",
        "sem_entrega",
        "pr_commit_cache",
        "pr_mergeada",
        "varredura_pr",
        "verificacao",
        "julgamento_orfao",
    }


def test_naming_convention_esta_configurada():
    # Sem isso o autogenerate nomeia constraints por reflexao e as migracoes
    # de indice/FK ficam instaveis entre maquinas.
    assert Base.metadata.naming_convention["pk"] == "pk_%(table_name)s"
    assert Base.metadata.naming_convention["fk"] == (
        "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
    )
