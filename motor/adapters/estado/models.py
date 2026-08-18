"""Modelos SQLAlchemy. Vivem SO aqui — o dominio nunca importa sqlalchemy.

Traducao modelo <-> dataclass acontece em postgres.py, na fronteira.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Nomes deterministicos de constraint: sem isso o autogenerate do Alembic
# nomeia por reflexao e as migracoes ficam instaveis entre maquinas.
CONVENCAO = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCAO)


class Repo(Base):
    __tablename__ = "repo"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(unique=True)  # basename do --repo
    tickio_sistema_id: Mapped[int]  # ID do sistema NO TICKIO, vai em ?sistema=


class RepoAlias(Base):
    """Basename alternativo do diretorio.

    Existe porque repo.nome chaveia todo o estado: o mesmo repositorio clonado
    como 'vb2web' numa maquina e 'vb2' noutra criaria duas linhas em repo e
    dois estados paralelos, sem erro nenhum aparecer.
    """

    __tablename__ = "repo_alias"

    nome: Mapped[str] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repo.id"))


class Versao(Base):
    __tablename__ = "versao"
    __table_args__ = (UniqueConstraint("repo_id", "numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repo.id"))
    numero: Mapped[str]  # '13.34.0'
    tipo: Mapped[str]  # fechada | ajustada | cliente
    base_ref: Mapped[str]
    base_commit: Mapped[str]
    # null = em construcao. Preenchida com a data do commit apontado pela tag.
    liberada_em: Mapped[datetime.datetime | None] = mapped_column(default=None)


class Atribuicao(Base):
    """Tarefa x versao destino.

    Guarda `marcada` desnormalizado de proposito: uma tabela `tarefa` global
    faria o snapshot congelado apontar para linha viva, e o registro do que
    saiu em 2026 mudaria ao editarem algo no Tickio em 2027.
    """

    __tablename__ = "atribuicao"

    versao_id: Mapped[int] = mapped_column(ForeignKey("versao.id"), primary_key=True)
    chamado: Mapped[str] = mapped_column(primary_key=True)
    marcada: Mapped[str]  # versao para a qual o Tickio marcou
    estado: Mapped[str]  # pendente | aplicado


class AtribuicaoCommit(Base):
    __tablename__ = "atribuicao_commit"
    __table_args__ = (
        ForeignKeyConstraint(
            ["versao_id", "chamado"],
            ["atribuicao.versao_id", "atribuicao.chamado"],
            ondelete="CASCADE",
        ),
    )

    versao_id: Mapped[int] = mapped_column(primary_key=True)
    chamado: Mapped[str] = mapped_column(primary_key=True)
    hash_origem: Mapped[str] = mapped_column(primary_key=True)


class Exclusao(Base):
    """Julgamento humano. A unica coisa que o recalculo nunca apaga."""

    __tablename__ = "exclusao"
    __table_args__ = (
        Index(
            "uq_exclusao_repo_hash_versao",
            "repo_id",
            "hash_origem",
            text("coalesce(versao_numero, '')"),
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repo.id"))
    hash_origem: Mapped[str]
    # null = vale para toda versao do repo (ex.: commit revertido).
    versao_numero: Mapped[str | None] = mapped_column(default=None)
    motivo: Mapped[str]


class SemEntrega(Base):
    """Chamado sem entrega NESTE repo. Por repo, nao por versao: os commits
    sao os mesmos para todas as versoes."""

    __tablename__ = "sem_entrega"

    repo_id: Mapped[int] = mapped_column(ForeignKey("repo.id"), primary_key=True)
    chamado: Mapped[str] = mapped_column(primary_key=True)
    motivo: Mapped[str]
