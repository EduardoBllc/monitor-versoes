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
        "pr_commit_cache",
        "bitbucket_pr",
        "bitbucket_varredura",
    }


def test_naming_convention_esta_configurada():
    # Sem isso o autogenerate nomeia constraints por reflexao e as migracoes
    # de indice/FK ficam instaveis entre maquinas.
    assert Base.metadata.naming_convention["pk"] == "pk_%(table_name)s"
    assert Base.metadata.naming_convention["fk"] == (
        "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
    )


def test_dominio_nao_importa_sqlalchemy():
    # A regra que sustenta a suite sem banco: modelo ORM so no adapter.
    import pathlib

    # Relativo a __file__, nao ao CWD: rodar pytest de outro diretorio nao
    # pode fazer o glob vir vazio e o teste passar sem checar nada.
    dominio = pathlib.Path(__file__).resolve().parent.parent / "motor" / "domain"
    arquivos = list(dominio.rglob("*.py"))
    assert arquivos, f"nenhum arquivo encontrado em {dominio}"
    for arquivo in arquivos:
        assert "sqlalchemy" not in arquivo.read_text(encoding="utf-8"), arquivo
