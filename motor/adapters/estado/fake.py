"""Double em memoria de EstadoRepo. Mantem a suite rodando sem banco."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from motor.domain.types import Atribuicao, CommitRef, Exclusion, RepoInfo, VersaoInfo
from motor.errors import NaoEncontrado, RecusaDeInvariante


@dataclass
class FakeEstado:
    repos: dict[str, RepoInfo] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)  # alias -> nome canonico
    versoes: dict[tuple[str, str], VersaoInfo] = field(default_factory=dict)
    _atribuicoes: dict[tuple[str, str], list[Atribuicao]] = field(default_factory=dict)
    _exclusoes: dict[str, list[Exclusion]] = field(default_factory=dict)
    _sem_entrega: dict[str, dict[str, str]] = field(default_factory=dict)
    # (repo, pr_id) -> hash -> commit. Dict por hash, nao lista: o adapter
    # real usa merge, entao regravar o mesmo hash sobrescreve em vez de somar.
    _pr_commits: dict[tuple[str, int], dict[str, CommitRef]] = field(
        default_factory=dict
    )

    def registrar_repo(self, nome: str, tickio_sistema_id: int, /) -> None:
        if nome in self.repos or nome in self.aliases:
            raise RecusaDeInvariante(f"repo '{nome}' ja cadastrado")
        self.repos[nome] = RepoInfo(
            nome=nome, tickio_sistema_id=tickio_sistema_id
        )

    def resolver_repo(self, basename: str, /) -> RepoInfo:
        nome = self.aliases.get(basename, basename)
        info = self.repos.get(nome)
        if info is None:
            raise NaoEncontrado(
                f"repo '{basename}' desconhecido. Cadastre com:\n"
                f"  uv run motor repo adicionar '{basename}' "
                f"--tickio-sistema-id <id>"
            )
        return info

    def listar_repos(self) -> list[RepoInfo]:
        return [self.repos[nome] for nome in sorted(self.repos)]

    def registrar_versao(self, repo: str, info: VersaoInfo, /) -> None:
        # Idempotente e nao-destrutivo: base e liberada_em so entram na
        # primeira gravacao. A base e o ponto onde a branch foi cortada, nao
        # algo a recomputar.
        self._exigir_repo(repo)
        if (repo, info.numero) in self.versoes:
            return
        self.versoes[(repo, info.numero)] = info

    def marcar_liberadas(
        self, repo: str, liberadas: dict[str, datetime.datetime], /
    ) -> None:
        self._exigir_repo(repo)
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

    def versao(self, repo: str, numero: str, /) -> VersaoInfo | None:
        self._exigir_repo(repo)
        return self.versoes.get((repo, numero))

    def atribuicoes(self, repo: str, versao: str, /) -> list[Atribuicao]:
        self._exigir_repo(repo)
        # Ordenado por chamado e por hash dentro de cada chamado: o adapter real
        # usa ORDER BY nas duas dimensoes. O dict aqui devolveria ordem de
        # insercao por acidente se nao normalizasse.
        #
        # Reconstroi cada Atribuicao em vez de devolver a armazenada: `commits`
        # e list mutavel dentro de uma dataclass frozen, entao devolver a
        # instancia guardada compartilharia a lista por referencia e o chamador
        # poderia corromper o estado do fake. O Postgres materializa linha nova
        # a cada query e nunca tem esse problema.
        return [
            Atribuicao(
                chamado=a.chamado,
                marcada=a.marcada,
                estado=a.estado,
                commits=sorted(a.commits),
            )
            for a in sorted(
                self._atribuicoes.get((repo, versao), []), key=lambda a: a.chamado
            )
        ]

    def substituir_atribuicoes(
        self, repo: str, versao: str, novas: list[Atribuicao], /
    ) -> None:
        # Espelha a trigger do Postgres: o fake nao pode aceitar o que o banco
        # recusa, senao os testes de engine validam um comportamento que nao
        # existe em producao.
        atual = self.versao(repo, versao)
        if atual is None:
            raise NaoEncontrado(f"versao {versao} nao registrada no estado")
        if atual.liberada_em is not None:
            raise RecusaDeInvariante(f"versao {versao} liberada e imutavel")
        self._atribuicoes[(repo, versao)] = list(novas)

    def exclusoes(self, repo: str, /) -> list[Exclusion]:
        self._exigir_repo(repo)
        return list(self._exclusoes.get(repo, []))

    def sem_entrega(self, repo: str, /) -> dict[str, str]:
        self._exigir_repo(repo)
        return dict(self._sem_entrega.get(repo, {}))

    def commits_de_pr(self, repo: str, pr_ids: list[int], /) -> dict[int, list[CommitRef]]:
        self._exigir_repo(repo)
        achados: dict[int, list[CommitRef]] = {}
        for pr_id in pr_ids:
            guardados = self._pr_commits.get((repo, pr_id))
            # ausencia != vazio: PR nunca consultada nao entra no dict, senao a
            # fonte a trataria como "PR sem commit" e nunca mais iria na API.
            if guardados is None:
                continue
            achados[pr_id] = sorted(
                guardados.values(), key=lambda c: (c.commit_date, c.hash_origem)
            )
        return achados

    def gravar_commits_de_pr(
        self, repo: str, commits: dict[int, list[CommitRef]], /
    ) -> None:
        self._exigir_repo(repo)
        for pr_id, refs in commits.items():
            alvo = self._pr_commits.setdefault((repo, pr_id), {})
            for c in refs:
                alvo[c.hash_origem] = c

    # -- internos --------------------------------------------------------

    def _exigir_repo(self, repo: str) -> None:
        """Recusa repo desconhecido, como o PostgresEstado._repo_id faz.

        Sem isto o fake era mais permissivo que o banco: devolvia None/[]/{} ou
        gravava versao pendurada num repo inexistente, onde o adapter real
        levanta. Fake mais leniente que o real e o modo de falha que este
        projeto pagou tres vezes — a suite fica verde num caminho que quebra em
        producao. Toma o nome canonico, nao alias: o `resolver_repo` ja traduziu.
        """
        if repo not in self.repos:
            raise NaoEncontrado(f"repo '{repo}' nao encontrado no estado")
