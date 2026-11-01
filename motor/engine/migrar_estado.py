"""Copia o estado completo de um banco para outro (SQLite <-> Postgres).

Comando explicito: nao troca `DATABASE_BACKEND` nem altera a origem. Copia as
tabelas de `Base.metadata` (tudo menos `alembic_version`) numa transacao so, com
os ids preservados. Destino com qualquer linha de estado e recusado, e falha no
meio da copia nao deixa destino parcial.

O congelamento (ADR 011) recusa escrita de atribuicao em versao liberada nos dois
backends, e a copia respeita isso: `versao` entra com `liberada_em` nulo, as
atribuicoes entram, e so no fim as datas voltam — a mesma via de escape que o
`reconstruir-estado` usa, dentro da transacao.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, Engine, Table, func, insert, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, DBAPIError
from sqlalchemy.orm import Session

from motor.adapters.estado.engine import (
    aplicar_migracoes,
    criar_engine,
    normalizar_url,
)
from motor.adapters.estado.models import Base
from motor.adapters.estado.postgres import PostgresEstado
from motor.errors import ErroDeEntrada, MotorError

_LOTE = 500
_SCHEMAS = ("sqlite", "postgresql+psycopg")


@dataclass
class ResumoMigracao:
    """Linhas copiadas por tabela, na ordem da copia."""

    linhas: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.linhas.values())


def _validar_url(url: str, rotulo: str) -> str:
    normalizada = normalizar_url(url)
    try:
        parsed = make_url(normalizada)
    except ArgumentError:
        raise ErroDeEntrada(
            f"{rotulo}: URL invalida (use sqlite:///<caminho> ou postgresql://...)"
        ) from None
    if parsed.drivername not in _SCHEMAS:
        raise ErroDeEntrada(
            f"{rotulo}: esquema de URL desconhecido {parsed.drivername!r} "
            "(use sqlite:///<caminho> ou postgresql://...)"
        )
    if parsed.drivername == "sqlite" and not parsed.database:
        raise ErroDeEntrada(f"{rotulo}: informe o caminho do arquivo SQLite")
    return normalizada


def _arquivo(url: str) -> str | None:
    """Caminho absoluto do arquivo se a URL for SQLite."""
    parsed = make_url(url)
    if parsed.drivername != "sqlite" or parsed.database is None:
        return None
    return os.path.abspath(os.path.expanduser(parsed.database))


def _mesmo_banco(a: str, b: str) -> bool:
    arquivo_a, arquivo_b = _arquivo(a), _arquivo(b)
    if arquivo_a is not None or arquivo_b is not None:
        return arquivo_a == arquivo_b
    return make_url(a) == make_url(b)


def _tabelas() -> list[Table]:
    return [t for t in Base.metadata.sorted_tables if t.name != "alembic_version"]


def _tem_linhas(conexao: Connection) -> list[str]:
    return [t.name for t in _tabelas() if conexao.execute(select(t).limit(1)).first()]


def _revisao(url: str) -> str | None:
    engine = criar_engine(url)
    try:
        with Session(engine) as sessao:
            return PostgresEstado(sessao=sessao).revisao_migracao()
    finally:
        engine.dispose()


def _em_lotes(linhas: Iterator[Any]) -> Iterator[list[dict[str, Any]]]:
    lote: list[dict[str, Any]] = []
    for linha in linhas:
        lote.append(dict(linha._mapping))
        if len(lote) >= _LOTE:
            yield lote
            lote = []
    if lote:
        yield lote


def _copiar_tabela(
    origem: Connection, destino: Connection, tabela: Table
) -> tuple[int, dict[Any, Any]]:
    """Copia a tabela. Devolve (linhas, datas de liberacao retiradas de `versao`)."""
    total = 0
    liberacoes: dict[Any, Any] = {}
    resultado = origem.execute(select(tabela))
    for lote in _em_lotes(iter(resultado)):
        if tabela.name == "versao":
            for linha in lote:
                if linha["liberada_em"] is not None:
                    liberacoes[linha["id"]] = linha["liberada_em"]
                    linha["liberada_em"] = None
        destino.execute(insert(tabela), lote)
        total += len(lote)
    return total, liberacoes


def _reposicionar_sequences(destino: Connection) -> None:
    if destino.dialect.name != "postgresql":
        return
    for tabela in _tabelas():
        chaves = list(tabela.primary_key.columns)
        if len(chaves) != 1 or chaves[0].name != "id":
            continue
        maior = destino.execute(select(func.max(tabela.c.id))).scalar()
        destino.execute(
            text("select setval(pg_get_serial_sequence(:t, 'id'), :v, :usado)"),
            {"t": tabela.name, "v": maior or 1, "usado": maior is not None},
        )


def _remover_arquivo_criado(arquivo: str | None) -> None:
    if arquivo is None:
        return
    for sufixo in ("", "-journal", "-wal", "-shm"):
        with contextlib.suppress(FileNotFoundError):
            os.remove(arquivo + sufixo)


def _validar_entrada(de_url: str, para_url: str) -> tuple[str, str]:
    origem_url = _validar_url(de_url, "--de")
    destino_url = _validar_url(para_url, "--para")
    if _mesmo_banco(origem_url, destino_url):
        raise ErroDeEntrada("--de e --para apontam para o mesmo banco")
    arquivo_origem = _arquivo(origem_url)
    if arquivo_origem is not None and not os.path.isfile(arquivo_origem):
        # Nao cria: abrir um SQLite inexistente o criaria vazio e a copia
        # "funcionaria" com zero linhas.
        raise ErroDeEntrada(f"--de: arquivo SQLite inexistente: {arquivo_origem}")
    if _revisao(origem_url) is None:
        raise ErroDeEntrada("--de: banco sem esquema (nada a migrar)")
    return origem_url, destino_url


def _copiar(origem: Engine, destino: Engine) -> ResumoMigracao:
    with origem.connect() as con_origem, destino.begin() as con_destino:
        if ocupadas := _tem_linhas(con_destino):
            raise ErroDeEntrada(
                "--para: destino nao esta vazio "
                f"({', '.join(ocupadas)}); migrar-estado nao mescla estado"
            )
        resumo = ResumoMigracao()
        liberacoes: dict[Any, Any] = {}
        for tabela in _tabelas():
            n, liberadas = _copiar_tabela(con_origem, con_destino, tabela)
            resumo.linhas[tabela.name] = n
            liberacoes.update(liberadas)
        versao = Base.metadata.tables["versao"]
        for versao_id, quando in liberacoes.items():
            con_destino.execute(
                update(versao)
                .where(versao.c.id == versao_id)
                .values(liberada_em=quando)
            )
        _reposicionar_sequences(con_destino)
    return resumo


def migrar_estado(de_url: str, para_url: str) -> ResumoMigracao:
    """Copia o estado de `de_url` para `para_url`. Ver o docstring do modulo."""
    origem_url, destino_url = _validar_entrada(de_url, para_url)
    arquivo_destino = _arquivo(destino_url)
    criou_arquivo = arquivo_destino is not None and not os.path.exists(arquivo_destino)
    if criou_arquivo and arquivo_destino is not None:
        os.makedirs(os.path.dirname(arquivo_destino), exist_ok=True)

    origem = criar_engine(origem_url)
    destino = criar_engine(destino_url)
    try:
        # Esquema antes e fora da transacao da copia (DDL). Se qualquer passo
        # falhar, o arquivo recem-criado tambem some.
        if _revisao(destino_url) is None:
            aplicar_migracoes(destino_url)
        return _copiar(origem, destino)
    except BaseException as erro:
        origem.dispose()
        destino.dispose()
        if criou_arquivo:
            _remover_arquivo_criado(arquivo_destino)
        if isinstance(erro, DBAPIError):
            raise MotorError(f"migrar-estado falhou: {erro.orig}") from erro
        raise
    finally:
        origem.dispose()
        destino.dispose()
