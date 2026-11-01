"""`migrar-estado`: copia o estado completo entre bancos, nos dois sentidos."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from motor.adapters.estado import models
from motor.adapters.estado.engine import criar_engine, garantir_esquema
from motor.adapters.estado.models import Base
from motor.adapters.estado.postgres import PostgresEstado
from motor.domain.types import VersaoInfo, VersionType
from motor.engine import migrar_estado as modulo
from motor.engine.migrar_estado import migrar_estado
from motor.errors import ErroDeEntrada

REPO = "vendabemweb"
LIBERADA = datetime.datetime(
    2026, 3, 1, 12, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3))
)
T = Base.metadata.tables


def _povoar(url: str) -> None:
    """Uma linha (ou mais) em cada tabela de estado, com uma versao liberada."""
    garantir_esquema(url)
    engine = criar_engine(url)
    try:
        with engine.begin() as con:
            con.execute(
                insert(T["repo"]),
                {
                    "id": 5,
                    "nome": REPO,
                    "tickio_sistema_id": 7,
                    "piso_versao": "13.2.0",
                },
            )
            con.execute(insert(T["repo_alias"]), {"nome": "vbweb", "repo_id": 5})
            con.execute(
                insert(T["versao"]),
                [
                    {"id": 11, "repo_id": 5, "numero": "13.33.0", "tipo": "fechada",
                     "base_ref": "13.32.0", "base_commit": "aaa"},
                    {"id": 12, "repo_id": 5, "numero": "13.34.0", "tipo": "ajustada",
                     "base_ref": "13.33.0", "base_commit": "bbb"},
                ],
            )  # fmt: skip
            con.execute(
                insert(T["atribuicao"]),
                [
                    {"versao_id": 11, "chamado": "100", "marcada": "13.33.0", "estado": "aplicado"},
                    {"versao_id": 12, "chamado": "101", "marcada": "13.34.0", "estado": "pendente"},
                ],
            )  # fmt: skip
            con.execute(
                insert(T["atribuicao_commit"]),
                [
                    {"versao_id": 11, "chamado": "100", "hash_origem": "h1"},
                    {"versao_id": 11, "chamado": "100", "hash_origem": "h2"},
                ],
            )
            # congela a 13.33.0 por ultimo: a trigger recusa atribuicao depois
            con.execute(
                update(T["versao"])
                .where(T["versao"].c.id == 11)
                .values(liberada_em=LIBERADA)
            )
            con.execute(
                insert(T["exclusao"]),
                [
                    {"id": 3, "repo_id": 5, "hash_origem": "x1", "versao_numero": None, "motivo": "revertido"},
                    {"id": 4, "repo_id": 5, "hash_origem": "x2", "versao_numero": "13.34.0", "motivo": "outro"},
                ],
            )  # fmt: skip
            con.execute(
                insert(T["sem_entrega"]),
                {"repo_id": 5, "chamado": "200", "motivo": "so config"},
            )
            con.execute(
                insert(T["pr_commit_cache"]),
                {"repo_id": 5, "pr_id": 2**40, "hash_origem": "c1", "parent": "p",
                 "commit_date": LIBERADA, "msg": "m"},
            )  # fmt: skip
            con.execute(
                insert(T["bitbucket_pr"]),
                {"repo_id": 5, "pr_id": 2**40, "titulo": "ch100", "branch": "b",
                 "updated_on": LIBERADA},
            )  # fmt: skip
            con.execute(
                insert(T["bitbucket_varredura"]), {"repo_id": 5, "ate": LIBERADA}
            )
    finally:
        engine.dispose()


def _dump(url: str) -> dict[str, list[tuple[Any, ...]]]:
    engine = criar_engine(url)
    try:
        with engine.connect() as con:
            return {
                t.name: sorted((tuple(r) for r in con.execute(select(t))), key=repr)
                for t in Base.metadata.sorted_tables
            }
    finally:
        engine.dispose()


def _leitura(url: str) -> tuple[Any, ...]:
    """O que o `consultar` le: versoes, atribuicoes, exclusoes e sem entrega."""
    engine = criar_engine(url)
    try:
        with Session(engine) as sessao:
            estado = PostgresEstado(sessao=sessao)
            return (
                estado.versao(REPO, "13.33.0"),
                estado.atribuicoes(REPO, "13.33.0"),
                estado.atribuicoes(REPO, "13.34.0"),
                estado.exclusoes(REPO),
                estado.sem_entrega(REPO),
            )
    finally:
        engine.dispose()


def _gravar_novos(url: str) -> None:
    engine = criar_engine(url)
    try:
        with Session(engine) as sessao:
            estado = PostgresEstado(sessao=sessao)
            estado.registrar_versao(
                REPO,
                VersaoInfo("13.35.0", VersionType.FECHADA, "13.34.0", "ccc"),
            )
            sessao.execute(
                insert(models.Exclusao).values(
                    repo_id=5, hash_origem="novo", versao_numero=None, motivo="m"
                )
            )
            sessao.commit()
            assert estado.versao(REPO, "13.35.0") is not None
            assert "novo" in {e.hash_origem for e in estado.exclusoes(REPO)}
    finally:
        engine.dispose()


def _verificar(origem: str, destino: str) -> None:
    resumo = migrar_estado(origem, destino)

    assert _dump(destino) == _dump(origem)
    assert resumo.linhas["pr_commit_cache"] == 1
    assert resumo.total == sum(len(v) for v in _dump(origem).values())
    antes = _leitura(origem)
    assert _leitura(destino) == antes
    assert antes[0].liberada_em == LIBERADA  # com fuso, mesmo instante
    _gravar_novos(destino)  # ids novos nao colidem (sequences reposicionadas)


def test_sqlite_para_sqlite(tmp_path: Path) -> None:
    origem = f"sqlite:///{tmp_path / 'a.db'}"
    _povoar(origem)

    _verificar(origem, f"sqlite:///{tmp_path / 'b.db'}")


@pytest.mark.integracao
def test_sqlite_para_postgres(
    tmp_path: Path, sessao_postgres: Any, _postgres_efemero: Any
) -> None:
    origem = f"sqlite:///{tmp_path / 'a.db'}"
    _povoar(origem)

    _verificar(origem, _postgres_efemero.get_connection_url())


@pytest.mark.integracao
def test_postgres_para_sqlite(
    tmp_path: Path, sessao_postgres: Any, _postgres_efemero: Any
) -> None:
    origem = _postgres_efemero.get_connection_url()
    _povoar(origem)

    _verificar(origem, f"sqlite:///{tmp_path / 'b.db'}")


@pytest.mark.integracao
def test_url_postgresql_sem_driver_e_normalizada(
    tmp_path: Path, sessao_postgres: Any, _postgres_efemero: Any
) -> None:
    destino = _postgres_efemero.get_connection_url().replace(
        "postgresql+psycopg://", "postgresql://"
    )
    origem = f"sqlite:///{tmp_path / 'a.db'}"
    _povoar(origem)

    assert migrar_estado(origem, destino).total > 0


def test_destino_com_linha_e_recusado_sem_escrita(tmp_path: Path) -> None:
    origem = f"sqlite:///{tmp_path / 'a.db'}"
    destino = f"sqlite:///{tmp_path / 'b.db'}"
    _povoar(origem)
    garantir_esquema(destino)
    engine = criar_engine(destino)
    with engine.begin() as con:
        con.execute(insert(T["repo"]), {"nome": "outro", "tickio_sistema_id": 1})
    engine.dispose()
    antes = _dump(destino)

    with pytest.raises(ErroDeEntrada, match="repo"):
        migrar_estado(origem, destino)

    assert _dump(destino) == antes


def test_de_igual_a_para(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'a.db'}"
    _povoar(url)

    with pytest.raises(ErroDeEntrada, match="mesmo banco"):
        migrar_estado(url, f"sqlite:///{tmp_path}/./a.db")


def test_esquema_de_url_desconhecido(tmp_path: Path) -> None:
    origem = f"sqlite:///{tmp_path / 'a.db'}"
    _povoar(origem)

    with pytest.raises(ErroDeEntrada, match="desconhecido"):
        migrar_estado(origem, "mysql://u:p@h/db")


def test_origem_sqlite_inexistente_nao_e_criada(tmp_path: Path) -> None:
    origem = tmp_path / "nao-existe.db"

    with pytest.raises(ErroDeEntrada, match="inexistente"):
        migrar_estado(f"sqlite:///{origem}", f"sqlite:///{tmp_path / 'b.db'}")

    assert not origem.exists()
    assert not (tmp_path / "b.db").exists()


def test_falha_no_meio_da_copia_deixa_destino_intacto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origem = f"sqlite:///{tmp_path / 'a.db'}"
    destino = f"sqlite:///{tmp_path / 'b.db'}"
    _povoar(origem)
    garantir_esquema(destino)
    original = modulo._copiar_tabela

    def quebra(de: Any, para: Any, tabela: Any) -> Any:
        if tabela.name == "exclusao":
            raise RuntimeError("falha forcada")
        return original(de, para, tabela)

    monkeypatch.setattr(modulo, "_copiar_tabela", quebra)

    with pytest.raises(RuntimeError):
        migrar_estado(origem, destino)

    assert all(linhas == [] for linhas in _dump(destino).values())


def test_falha_remove_o_arquivo_que_o_comando_criou(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origem = f"sqlite:///{tmp_path / 'a.db'}"
    _povoar(origem)

    def quebra(*_: Any) -> Any:
        raise RuntimeError("falha forcada")

    monkeypatch.setattr(modulo, "_copiar_tabela", quebra)

    with pytest.raises(RuntimeError):
        migrar_estado(origem, f"sqlite:///{tmp_path / 'novo.db'}")

    assert not (tmp_path / "novo.db").exists()
