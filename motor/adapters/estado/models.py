"""Modelos SQLAlchemy. Vivem SO aqui — o dominio nunca importa sqlalchemy.

Traducao modelo <-> dataclass acontece em postgres.py, na fronteira.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import DateTime, TypeDecorator

# Nomes deterministicos de constraint: sem isso o autogenerate do Alembic
# nomeia por reflexao e as migracoes ficam instaveis entre maquinas.
CONVENCAO = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class DataComFuso(TypeDecorator[datetime.datetime]):
    """`timestamptz` que volta com fuso nos dois backends.

    O Postgres ja guarda e devolve o instante com fuso. O SQLite guarda texto
    sem fuso e devolveria datetime ingenuo — que comparado com um datetime com
    fuso estoura `TypeError`. Aqui o SQLite grava em UTC e le como UTC.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime.datetime | None, dialect: Dialect
    ) -> datetime.datetime | None:
        if value is not None and dialect.name == "sqlite" and value.tzinfo:
            return value.astimezone(datetime.UTC)
        return value

    def process_result_value(
        self, value: datetime.datetime | None, dialect: Dialect
    ) -> datetime.datetime | None:
        if value is not None and dialect.name == "sqlite" and value.tzinfo is None:
            return value.replace(tzinfo=datetime.UTC)
        return value


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCAO)


class Repo(Base):
    __tablename__ = "repo"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(unique=True)  # nome da seção [repos.<nome>]


class Versao(Base):
    __tablename__ = "versao"
    __table_args__ = (
        # nome explicito: a convencao gera uq_versao_repo_id, que le como se
        # repo_id sozinho fosse unico — e um repo tem muitas versoes.
        UniqueConstraint("repo_id", "numero", name="uq_versao_repo_id_numero"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repo.id"))
    numero: Mapped[str]  # '13.34.0'
    # rotulo livre do esquema de versao; null quando o esquema nao classifica.
    tipo: Mapped[str | None]
    base_ref: Mapped[str]
    base_commit: Mapped[str]
    # null = em construcao. Preenchida com a data do commit apontado pela tag.
    liberada_em: Mapped[datetime.datetime | None] = mapped_column(
        DataComFuso(), default=None
    )


class Atribuicao(Base):
    """Tarefa x versao destino.

    Guarda `marcada` desnormalizado de proposito: uma tabela `tarefa` global
    faria o snapshot congelado apontar para linha viva, e o registro do que
    saiu em 2026 mudaria ao editarem algo no rastreador em 2027.
    """

    __tablename__ = "atribuicao"

    versao_id: Mapped[int] = mapped_column(ForeignKey("versao.id"), primary_key=True)
    chamado: Mapped[str] = mapped_column(primary_key=True)
    marcada: Mapped[str]  # versao para a qual o rastreador marcou
    estado: Mapped[str]  # ck_atribuicao_estado


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


class JulgamentoOrfao(Base):
    """Julgamento humano de um commit órfão da versão: o git não o recupera,
    e nenhum recálculo o apaga (docs/decisoes/004-estado-descartavel.md).

    Sem trigger de congelamento: não é atribuição. Numa versão liberada ele
    pode ser gravado antes de levantar o congelamento e vale no
    `verificar --auditar` (docs/decisoes/034-julgamento-de-orfao.md).
    """

    __tablename__ = "julgamento_orfao"

    versao_id: Mapped[int] = mapped_column(ForeignKey("versao.id"), primary_key=True)
    hash_origem: Mapped[str] = mapped_column(primary_key=True)
    # null = o commit não pertence a chamado nenhum.
    chamado: Mapped[str | None] = mapped_column(default=None)
    motivo: Mapped[str]


class PrCommitCache(Base):
    """Commits de uma PR mergeada do host — cache puro de fato imutavel.

    Existe para cortar o `GET /pullrequests/{id}/commits`, que hoje roda uma vez
    por PR a cada `verificar`. A busca das PRs do chamado continua batendo na
    API toda vez: e ela que descobre PR nova, e cachea-la esconderia um commit
    de correcao — falso-verde, que e o modo de falha que o motor existe para
    evitar.

    Fica de fora de proposito: `chamado`, que vem da busca e nao da PR, e
    `is_ancestor(hash, principal)`, que e volatil — uma PR mergeada numa branch que
    ainda nao chegou na principal viraria commit escondido para sempre.
    """

    __tablename__ = "pr_commit_cache"

    repo_id: Mapped[int] = mapped_column(ForeignKey("repo.id"), primary_key=True)
    # BigInteger: o pr_id vem do host, nao e nosso para caber em int4.
    pr_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    hash_origem: Mapped[str] = mapped_column(primary_key=True)
    parent: Mapped[str]
    commit_date: Mapped[datetime.datetime] = mapped_column(DataComFuso())
    msg: Mapped[str]


class PrMergeada(Base):
    """Indice local das PRs mergeadas — o que substitui uma busca na API por
    chamado por uma leitura de tabela.

    Titulo e branch entram crus. O casamento e um predicado (`ch<n>` no comeco
    do titulo ou dentro da branch), nao uma extracao: guardar o chamado ja
    extraido escolheria uma interpretacao nova e divergiria do adapter em
    silencio.
    """

    __tablename__ = "pr_mergeada"

    repo_id: Mapped[int] = mapped_column(ForeignKey("repo.id"), primary_key=True)
    pr_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    titulo: Mapped[str]
    branch: Mapped[str]
    updated_on: Mapped[datetime.datetime] = mapped_column(DataComFuso())


class VerificacaoVersao(Base):
    """Cache do último `verificar` da versão; descartável, nunca migrado."""

    __tablename__ = "verificacao"

    versao_id: Mapped[int] = mapped_column(
        ForeignKey("versao.id", ondelete="CASCADE"), primary_key=True
    )
    tip: Mapped[str]
    impressao: Mapped[str]
    verificado_em: Mapped[datetime.datetime] = mapped_column(DataComFuso())
    status: Mapped[str] = mapped_column(Text)


class VarreduraPr(Base):
    """Marca d'agua da varredura incremental: ate quando o indice esta completo.

    Ausente = nunca varrido, e a proxima varredura baixa o historico inteiro.
    Guarda o INICIO da varredura, nao o maior `updated_on` visto: PR mergeada
    durante a propria varredura pode nao aparecer nela, e so cai na proxima
    porque o `updated_on` dela e maior que este inicio.
    """

    __tablename__ = "varredura_pr"

    repo_id: Mapped[int] = mapped_column(ForeignKey("repo.id"), primary_key=True)
    ate: Mapped[datetime.datetime] = mapped_column(DataComFuso())
