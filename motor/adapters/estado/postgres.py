"""PostgresEstado: traduz modelo ORM <-> dataclass do dominio na fronteira."""

from __future__ import annotations

import datetime
from collections.abc import Iterable
from dataclasses import dataclass
from typing import NoReturn, TypeVar

from sqlalchemy import Select, delete, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from motor.adapters.estado import models
from motor.domain.types import (
    Atribuicao,
    CommitRef,
    Exclusion,
    RepoInfo,
    VersaoInfo,
    VersionType,
)
from motor.errors import (
    BackendIndisponivel,
    MotorError,
    NaoEncontrado,
    RecusaDeInvariante,
    RespostaInvalida,
)

# Levantado pela trigger trava_versao_liberada; ver a migracao que a define.
ERRCODE_VERSAO_CONGELADA = "MV001"

_TIPO_PARA_TEXTO = {
    VersionType.FECHADA: "fechada",
    VersionType.AJUSTADA: "ajustada",
    VersionType.CLIENTE: "cliente",
}
_TEXTO_PARA_TIPO = {v: k for k, v in _TIPO_PARA_TEXTO.items()}

# A linha que o select devolve. Amarra o retorno de _scalar/_scalars ao modelo
# pedido no statement, em vez de espalhar Any por todo metodo que os chama.
_Linha = TypeVar("_Linha")


@dataclass
class PostgresEstado:
    sessao: Session

    def registrar_repo(self, nome: str, tickio_sistema_id: int, /) -> None:
        # Nome canonico e alias dividem o mesmo espaco de nomes, entao as duas
        # tabelas contam para "ja cadastrado". Sao duas consultas so quando a
        # primeira nao acha nada: o `or` curto-circuita.
        ja_cadastrado = (
            self._scalar(select(models.Repo).where(models.Repo.nome == nome))
            is not None
            or self._scalar(
                select(models.RepoAlias).where(models.RepoAlias.nome == nome)
            )
            is not None
        )
        if ja_cadastrado:
            raise RecusaDeInvariante(f"repo '{nome}' ja cadastrado")
        self.sessao.add(
            models.Repo(nome=nome, tickio_sistema_id=tickio_sistema_id)
        )
        self._commit()

    def resolver_repo(self, basename: str, /) -> RepoInfo:
        linha = self._scalar(select(models.Repo).where(models.Repo.nome == basename))
        if linha is None:
            alias = self._scalar(
                select(models.RepoAlias).where(models.RepoAlias.nome == basename)
            )
            if alias is not None:
                linha = self._scalar(
                    select(models.Repo).where(models.Repo.id == alias.repo_id)
                )
        if linha is None:
            raise NaoEncontrado(
                f"repo '{basename}' desconhecido. Cadastre com:\n"
                f"  uv run motor repo adicionar '{basename}' "
                f"--tickio-sistema-id <id>"
            )
        return RepoInfo(nome=linha.nome, tickio_sistema_id=linha.tickio_sistema_id)

    def listar_repos(self) -> list[RepoInfo]:
        return [
            RepoInfo(nome=linha.nome, tickio_sistema_id=linha.tickio_sistema_id)
            for linha in self._scalars(select(models.Repo).order_by(models.Repo.nome))
        ]

    def registrar_versao(self, repo: str, info: VersaoInfo, /) -> None:
        # Idempotente e nao-destrutivo: a base e o ponto onde a branch foi
        # cortada, gravado uma vez. Reescreve-la faria a base de uma X.0.0
        # seguir o tip atual do master.
        repo_id = self._repo_id(repo)
        if self._versao(repo_id, info.numero) is not None:
            return
        self.sessao.add(
            models.Versao(
                repo_id=repo_id,
                numero=info.numero,
                tipo=_TIPO_PARA_TEXTO[info.tipo],
                base_ref=info.base_ref,
                base_commit=info.base_commit,
                liberada_em=info.liberada_em,
            )
        )
        self._commit()

    def marcar_liberadas(
        self, repo: str, liberadas: dict[str, datetime.datetime], /
    ) -> None:
        repo_id = self._repo_id(repo)
        for numero, quando in liberadas.items():
            linha = self._versao(repo_id, numero)
            # ignora versao ausente do estado e nao reescreve data ja gravada:
            # a primeira observacao da tag e a boa.
            if linha is None or linha.liberada_em is not None:
                continue
            linha.liberada_em = quando
        self._commit()

    def versao(self, repo: str, numero: str, /) -> VersaoInfo | None:
        linha = self._versao(self._repo_id(repo), numero)
        if linha is None:
            return None
        tipo = _TEXTO_PARA_TIPO.get(linha.tipo)
        if tipo is None:
            raise RespostaInvalida(
                f"tipo de versao invalido no banco: '{linha.tipo}' "
                f"(esperado fechada, ajustada ou cliente)"
            )
        return VersaoInfo(
            numero=linha.numero,
            tipo=tipo,
            base_ref=linha.base_ref,
            base_commit=linha.base_commit,
            liberada_em=linha.liberada_em,
        )

    def atribuicoes(self, repo: str, versao: str, /) -> list[Atribuicao]:
        versao_id = self._versao_id(repo, versao)
        if versao_id is None:
            return []
        commits: dict[str, list[str]] = {}
        for linha in self._scalars(
            select(models.AtribuicaoCommit)
            .where(models.AtribuicaoCommit.versao_id == versao_id)
            .order_by(models.AtribuicaoCommit.chamado, models.AtribuicaoCommit.hash_origem)
        ):
            commits.setdefault(linha.chamado, []).append(linha.hash_origem)
        return [
            Atribuicao(
                chamado=a.chamado,
                marcada=a.marcada,
                estado=a.estado,
                commits=sorted(commits.get(a.chamado, [])),
            )
            for a in self._scalars(
                select(models.Atribuicao)
                .where(models.Atribuicao.versao_id == versao_id)
                .order_by(models.Atribuicao.chamado)
            )
        ]

    def substituir_atribuicoes(
        self, repo: str, versao: str, novas: list[Atribuicao], /
    ) -> None:
        linha = self._versao(self._repo_id(repo), versao)
        if linha is None:
            raise NaoEncontrado(f"versao {versao} nao registrada no estado")
        # A recusa nao pode depender so da trigger: se a versao ja estiver
        # liberada mas o snapshot atual estiver vazio e `novas` tambem vier
        # vazia, os deletes afetam 0 linhas e nenhum insert dispara a trigger
        # — o commit passaria em silencio. Checa aqui, a trigger fica so como
        # cinto-e-suspensorio para SQL escrito a mao.
        if linha.liberada_em is not None:
            raise RecusaDeInvariante(f"versao {versao} liberada e imutavel")
        versao_id = linha.id

        # As duas deletes sao statements Core enviados na hora (nao esperam
        # o flush do commit): se a versao estiver congelada, a trigger dispara
        # aqui mesmo. Por isso o bloco inteiro — deletes, inserts e commit —
        # vai dentro do mesmo try, nao so o commit final.
        try:
            self.sessao.execute(
                delete(models.AtribuicaoCommit).where(
                    models.AtribuicaoCommit.versao_id == versao_id
                )
            )
            self.sessao.execute(
                delete(models.Atribuicao).where(
                    models.Atribuicao.versao_id == versao_id
                )
            )
            for a in novas:
                self.sessao.add(
                    models.Atribuicao(
                        versao_id=versao_id,
                        chamado=a.chamado,
                        marcada=a.marcada,
                        estado=a.estado,
                    )
                )
                for hash_origem in a.commits:
                    self.sessao.add(
                        models.AtribuicaoCommit(
                            versao_id=versao_id,
                            chamado=a.chamado,
                            hash_origem=hash_origem,
                        )
                    )
            self.sessao.commit()
        except DBAPIError as e:
            self._traduzir_erro(e)

    def exclusoes(self, repo: str, /) -> list[Exclusion]:
        repo_id = self._repo_id(repo)
        return [
            Exclusion(
                hash_origem=e.hash_origem,
                versao_numero=e.versao_numero,
                motivo=e.motivo,
            )
            for e in self._scalars(
                select(models.Exclusao)
                .where(models.Exclusao.repo_id == repo_id)
                .order_by(models.Exclusao.id)
            )
        ]

    def sem_entrega(self, repo: str, /) -> dict[str, str]:
        repo_id = self._repo_id(repo)
        return {
            s.chamado: s.motivo
            for s in self._scalars(
                select(models.SemEntrega)
                .where(models.SemEntrega.repo_id == repo_id)
                .order_by(models.SemEntrega.chamado)
            )
        }

    def commits_de_pr(self, repo: str, pr_ids: list[int], /) -> dict[int, list[CommitRef]]:
        repo_id = self._repo_id(repo)
        achados: dict[int, list[CommitRef]] = {}
        for linha in self._scalars(
            select(models.PrCommitCache)
            .where(
                models.PrCommitCache.repo_id == repo_id,
                models.PrCommitCache.pr_id.in_(pr_ids),
            )
            # hash_origem no ORDER BY tambem: dois commits com o mesmo segundo
            # sairiam em ordem arbitraria, e o fake nao teria como concordar.
            .order_by(
                models.PrCommitCache.pr_id,
                models.PrCommitCache.commit_date,
                models.PrCommitCache.hash_origem,
            )
        ):
            achados.setdefault(linha.pr_id, []).append(
                CommitRef(
                    hash_origem=linha.hash_origem,
                    parent=linha.parent,
                    commit_date=linha.commit_date,
                    msg=linha.msg,
                )
            )
        return achados

    def gravar_commits_de_pr(
        self, repo: str, commits: dict[int, list[CommitRef]], /
    ) -> None:
        repo_id = self._repo_id(repo)
        for pr_id, refs in commits.items():
            for c in refs:
                # merge e nao add: a fonte regrava a mesma PR quando o cache
                # dela saiu vazio (PR so de merge commit), e um add duplicaria
                # a chave.
                self.sessao.merge(
                    models.PrCommitCache(
                        repo_id=repo_id,
                        pr_id=pr_id,
                        hash_origem=c.hash_origem,
                        parent=c.parent,
                        commit_date=c.commit_date,
                        msg=c.msg,
                    )
                )
        self._commit()

    # -- internos --------------------------------------------------------

    def _repo_id(self, repo: str) -> int:
        linha = self._scalar(select(models.Repo).where(models.Repo.nome == repo))
        if linha is None:
            raise NaoEncontrado(f"repo '{repo}' nao encontrado no estado")
        return linha.id

    def _versao(self, repo_id: int, numero: str) -> models.Versao | None:
        return self._scalar(
            select(models.Versao).where(
                models.Versao.repo_id == repo_id, models.Versao.numero == numero
            )
        )

    def _scalar(self, stmt: Select[tuple[_Linha]]) -> _Linha | None:
        """Le uma linha (ou None). Ler tambem pode achar o banco fora do ar
        — sem isso todo metodo de escrita, que abre com uma leitura, vazaria
        um OperationalError crua antes de chegar perto de um commit."""
        try:
            return self.sessao.scalar(stmt)
        except DBAPIError as e:
            self._traduzir_erro(e)

    def _scalars(self, stmt: Select[tuple[_Linha]]) -> Iterable[_Linha]:
        try:
            return self.sessao.scalars(stmt)
        except DBAPIError as e:
            self._traduzir_erro(e)

    def _versao_id(self, repo: str, numero: str) -> int | None:
        linha = self._versao(self._repo_id(repo), numero)
        return None if linha is None else linha.id

    def _commit(self) -> None:
        """Traduz erro do banco em MotorError.

        A trigger de congelamento chega aqui como DBAPIError; deixa-la subir
        crua imprimiria traceback de psycopg em vez de mensagem util.

        DBAPIError e nao DatabaseError: InterfaceError (conexao que morreu no
        meio do comando) e irmao de DatabaseError, nao filho — com o catch mais
        estreito ele escapava como "Erro interno fatal (bug)" com traceback de
        psycopg, que e justamente a confusao operador-vs-bug que o motor
        promete nao fazer.
        """
        try:
            self.sessao.commit()
        except DBAPIError as e:
            self._traduzir_erro(e)

    def _traduzir_erro(self, e: DBAPIError) -> NoReturn:
        """Decide a mensagem pelo SQLSTATE, nao pelo tipo nem pelo texto.

        Antes ramificava por `isinstance(e, OperationalError)`, que e mais largo
        do que a mensagem promete: psycopg mapeia deadlock (40P01) e statement
        timeout (57014) para OperationalError tambem, e os dois saiam como
        "banco inacessivel ... docker compose up -d" — banco que respondeu, e a
        resposta foi um erro de execucao.

        E identificava o congelamento por `"imutavel" in str(e.orig)`, o que
        acoplava o adapter a um texto que vive nas migracoes: reescrever a
        mensagem da trigger quebrava esta traducao em silencio. Agora a trigger
        levanta com `errcode = 'MV001'` e o match e no codigo.

        Sem SQLSTATE = o servidor nunca respondeu (recusa de conexao, conexao
        morta no meio do comando). E o unico caso que "suba o container" ajuda.
        """
        self.sessao.rollback()
        sqlstate = getattr(e.orig, "sqlstate", None)
        if sqlstate == ERRCODE_VERSAO_CONGELADA or (
            # fallback para banco que ainda nao rodou a migracao do errcode
            sqlstate is not None
            and "imutavel" in str(e.orig)
        ):
            raise RecusaDeInvariante(
                "versao liberada e imutavel — remarque a tarefa para a proxima versao"
            ) from e
        if sqlstate is None:
            raise BackendIndisponivel(
                f"banco inacessivel: {e.orig}. Suba com: docker compose up -d"
            ) from e
        raise MotorError(f"erro do banco: {e.orig}") from e
