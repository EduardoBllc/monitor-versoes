"""PostgresEstado: traduz modelo ORM <-> dataclass do dominio na fronteira."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import NoReturn

from sqlalchemy import delete, select
from sqlalchemy.exc import DatabaseError, OperationalError
from sqlalchemy.orm import Session

from motor.adapters.estado import models
from motor.domain.types import Atribuicao, Exclusion, RepoInfo, VersaoInfo, VersionType
from motor.errors import MotorError

_TIPO_PARA_TEXTO = {
    VersionType.FECHADA: "fechada",
    VersionType.AJUSTADA: "ajustada",
    VersionType.CLIENTE: "cliente",
}
_TEXTO_PARA_TIPO = {v: k for k, v in _TIPO_PARA_TEXTO.items()}


@dataclass
class PostgresEstado:
    sessao: Session

    def resolver_repo(self, basename: str) -> RepoInfo:
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
            raise MotorError(
                f"repo '{basename}' desconhecido. Cadastre com:\n"
                f"  insert into repo (nome, tickio_sistema_id) "
                f"values ('{basename}', <id do sistema no tickio>);"
            )
        return RepoInfo(nome=linha.nome, tickio_sistema_id=linha.tickio_sistema_id)

    def registrar_versao(self, repo: str, info: VersaoInfo) -> None:
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
        self, repo: str, liberadas: dict[str, datetime.datetime]
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

    def versao(self, repo: str, numero: str) -> VersaoInfo | None:
        linha = self._versao(self._repo_id(repo), numero)
        if linha is None:
            return None
        tipo = _TEXTO_PARA_TIPO.get(linha.tipo)
        if tipo is None:
            raise MotorError(
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

    def atribuicoes(self, repo: str, versao: str) -> list[Atribuicao]:
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
        self, repo: str, versao: str, novas: list[Atribuicao]
    ) -> None:
        linha = self._versao(self._repo_id(repo), versao)
        if linha is None:
            raise MotorError(f"versao {versao} nao registrada no estado")
        # A recusa nao pode depender so da trigger: se a versao ja estiver
        # liberada mas o snapshot atual estiver vazio e `novas` tambem vier
        # vazia, os deletes afetam 0 linhas e nenhum insert dispara a trigger
        # — o commit passaria em silencio. Checa aqui, a trigger fica so como
        # cinto-e-suspensorio para SQL escrito a mao.
        if linha.liberada_em is not None:
            raise MotorError(f"versao {versao} liberada e imutavel")
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
        except DatabaseError as e:
            self._traduzir_erro(e)

    def exclusoes(self, repo: str) -> list[Exclusion]:
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

    def sem_entrega(self, repo: str) -> dict[str, str]:
        repo_id = self._repo_id(repo)
        return {
            s.chamado: s.motivo
            for s in self._scalars(
                select(models.SemEntrega)
                .where(models.SemEntrega.repo_id == repo_id)
                .order_by(models.SemEntrega.chamado)
            )
        }

    # -- internos --------------------------------------------------------

    def _repo_id(self, repo: str) -> int:
        linha = self._scalar(select(models.Repo).where(models.Repo.nome == repo))
        if linha is None:
            raise MotorError(f"repo '{repo}' nao encontrado no estado")
        return linha.id

    def _versao(self, repo_id: int, numero: str) -> models.Versao | None:
        return self._scalar(
            select(models.Versao).where(
                models.Versao.repo_id == repo_id, models.Versao.numero == numero
            )
        )

    def _scalar(self, stmt):
        """Le uma linha (ou None). Ler tambem pode achar o banco fora do ar
        — sem isso todo metodo de escrita, que abre com uma leitura, vazaria
        um OperationalError crua antes de chegar perto de um commit."""
        try:
            return self.sessao.scalar(stmt)
        except DatabaseError as e:
            self._traduzir_erro(e)

    def _scalars(self, stmt):
        try:
            return self.sessao.scalars(stmt)
        except DatabaseError as e:
            self._traduzir_erro(e)

    def _versao_id(self, repo: str, numero: str) -> int | None:
        linha = self._versao(self._repo_id(repo), numero)
        return None if linha is None else linha.id

    def _commit(self) -> None:
        """Traduz erro do banco em MotorError.

        A trigger de congelamento chega aqui como DatabaseError; deixa-la subir
        crua imprimiria traceback de psycopg em vez de mensagem util.
        """
        try:
            self.sessao.commit()
        except DatabaseError as e:
            self._traduzir_erro(e)

    def _traduzir_erro(self, e: DatabaseError) -> NoReturn:
        self.sessao.rollback()
        if isinstance(e, OperationalError):
            raise MotorError(
                f"banco inacessivel: {e.orig}. Suba com: docker compose up -d"
            ) from e
        if "imutavel" in str(e.orig):
            raise MotorError(
                "versao liberada e imutavel — remarque a tarefa para a proxima versao"
            ) from e
        raise MotorError(f"erro do banco: {e.orig}") from e
