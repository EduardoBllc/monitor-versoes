"""Double em memoria de EstadoRepo. Mantem a suite rodando sem banco."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from motor.domain.types import Atribuicao, Exclusion, RepoInfo, VersaoInfo
from motor.errors import MotorError


@dataclass
class FakeEstado:
    repos: dict[str, RepoInfo] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)  # alias -> nome canonico
    versoes: dict[tuple[str, str], VersaoInfo] = field(default_factory=dict)
    _atribuicoes: dict[tuple[str, str], list[Atribuicao]] = field(default_factory=dict)
    _exclusoes: dict[str, list[Exclusion]] = field(default_factory=dict)
    _sem_entrega: dict[str, dict[str, str]] = field(default_factory=dict)

    def resolver_repo(self, basename: str) -> RepoInfo:
        nome = self.aliases.get(basename, basename)
        info = self.repos.get(nome)
        if info is None:
            raise MotorError(
                f"repo '{basename}' desconhecido. Cadastre com:\n"
                f"  insert into repo (nome, tickio_sistema_id) "
                f"values ('{basename}', <id do sistema no tickio>);"
            )
        return info

    def registrar_versao(self, repo: str, info: VersaoInfo) -> None:
        # Idempotente e nao-destrutivo: base e liberada_em so entram na
        # primeira gravacao. A base e o ponto onde a branch foi cortada, nao
        # algo a recomputar.
        if (repo, info.numero) in self.versoes:
            return
        self.versoes[(repo, info.numero)] = info

    def marcar_liberadas(
        self, repo: str, liberadas: dict[str, datetime.datetime]
    ) -> None:
        for numero, quando in liberadas.items():
            atual = self.versoes.get((repo, numero))
            if atual is None or atual.liberada_em is not None:
                continue
            self.versoes[(repo, numero)] = VersaoInfo(
                numero=atual.numero,
                tipo=atual.tipo,
                base_ref=atual.base_ref,
                base_commit=atual.base_commit,
                liberada_em=quando,
            )

    def versao(self, repo: str, numero: str) -> VersaoInfo | None:
        return self.versoes.get((repo, numero))

    def atribuicoes(self, repo: str, versao: str) -> list[Atribuicao]:
        return list(self._atribuicoes.get((repo, versao), []))

    def substituir_atribuicoes(
        self, repo: str, versao: str, novas: list[Atribuicao]
    ) -> None:
        # Espelha a trigger do Postgres: o fake nao pode aceitar o que o banco
        # recusa, senao os testes de engine validam um comportamento que nao
        # existe em producao.
        atual = self.versao(repo, versao)
        if atual is None:
            raise MotorError(f"versao {versao} nao registrada")
        if atual.liberada_em is not None:
            raise MotorError(f"versao {versao} liberada e imutavel")
        self._atribuicoes[(repo, versao)] = list(novas)

    def exclusoes(self, repo: str) -> list[Exclusion]:
        return list(self._exclusoes.get(repo, []))

    def sem_entrega(self, repo: str) -> dict[str, str]:
        return dict(self._sem_entrega.get(repo, {}))
