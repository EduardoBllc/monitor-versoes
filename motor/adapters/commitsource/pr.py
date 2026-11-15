"""PrCommitSource: descobre commits de uma tarefa pelas PRs mergeadas no host.

Mais robusto que o grep de mensagem: associa commit->chamado pela PR (título
que começa com a referência da tarefa, ou nome da branch de origem que a
contém — caixa ignorada nos dois), não pela formatação do trailer que o dev
pode errar. Só commits que já estão em `origin/<principal>` (is_ancestor)
entram.

O host é um plugin (`HostPr`) que só sabe perguntar ao serviço; varredura,
índice, casamento, cache e filtro ficam aqui, no núcleo
(docs/decisoes/036-fonte-de-pr-plugavel.md).
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace

from motor.domain.referencia import FonteReferencia, Referencia, regex_do_chamado
from motor.domain.types import CommitRef, PrIndex
from motor.ports import EstadoRepo, GitRepo, HostPr
from motor.progresso import Progresso, RelatorProgresso, silencioso

# Requisições simultâneas ao host: teto fixo para não encostar no limite de taxa.
_TETO_HOST = 4


def _padrao_do_chamado(ref: Referencia, chamado: str) -> re.Pattern[str]:
    """A referência do chamado com fronteira só pelo alfabeto, sem olhar caixa.

    A fronteira é o conserto de um bug antigo: com `startswith`/`in` crus, o
    chamado 255514 casava com a PR de 2555145 — nada via onde o ID terminava,
    e o chamado curto roubava a entrega do longo. Só pelo alfabeto (e não pelo
    `\\w` do domínio) porque branch cola a referência em letra: com `ch{id}`, a
    ponta `c` de `ch` fica livre e a direita vira o `(?!\\d)` de sempre.

    `IGNORECASE` é o conserto do segundo: a PR "CH254473 - ..." não casava, e
    como a PR anterior do mesmo chamado casava, a cadeia (§ChainCommitSource)
    dava o chamado por resolvido e nem o grep via a segunda entrega. A
    referência é digitada à mão; a caixa dela não é dado.
    """
    return regex_do_chamado(ref, chamado, so_alfabeto=True)


def _casa(pr: PrIndex, padrao: re.Pattern[str]) -> bool:
    # match no título (ancorado, como o startswith de antes) e search na branch,
    # onde o termo pode estar em qualquer posição.
    return padrao.match(pr.titulo) is not None or padrao.search(pr.branch) is not None


@dataclass
class PrCommitSource:
    host: HostPr
    # A chave do estado (o valor de `[prs] fonte`): índice, marca e cache só
    # valem para o host que os gravou.
    nome_host: str
    git: GitRepo
    # Obrigatórios: o índice local de PRs vive no estado, e sem ele esta fonte
    # não tem o que ler. Quem não tem banco monta só o grep (ver montagem.py).
    # `repo_estado` é o nome canônico no banco, não o repo no host.
    estado: EstadoRepo = field(kw_only=True)
    repo_estado: str = field(kw_only=True)
    referencia: FonteReferencia = field(kw_only=True)
    # `origin/<principal>`, não o head local: `git fetch` avança a ref de
    # rastreamento e NUNCA o head local, então filtrar pela principal local
    # esconderia toda PR mergeada depois do último checkout+pull da máquina
    # (chamado 257270, PR 1174). É a mesma ref que o GrepCommitSource lê.
    # Fonte, não valor: a principal sai do esquema, que só se resolve na
    # primeira busca — montar não é usar.
    ref_principal: Callable[[], str] = field(kw_only=True)
    progresso: RelatorProgresso = field(default=silencioso, kw_only=True)
    _principal: str = field(default="", init=False, repr=False)

    def _ref_principal(self) -> str:
        """Avaliada uma vez por instância, na primeira busca."""
        if not self._principal:
            self._principal = self.ref_principal()
        return self._principal

    def resolve(self, chamados: list[str], /) -> dict[str, list[CommitRef]]:
        resultado: dict[str, list[CommitRef]] = {}
        # Antes da varredura: a falta de padrão não pode custar rede nem
        # escrita no índice. Sem chamado a casar, não há o que exigir.
        ref = self.referencia() if any(chamados) else None

        self.progresso(Progresso("varrendo PRs"))
        self._varrer()
        indice = self.estado.prs_indexadas(self.repo_estado)
        prs_do_chamado: dict[str, list[int]] = {}
        if ref is not None:
            for chamado in filter(None, chamados):
                padrao = _padrao_do_chamado(ref, chamado)
                prs_do_chamado[chamado] = [
                    pr.pr_id for pr in indice if _casa(pr, padrao)
                ]
        por_pr = self._commits_das_prs(
            list(dict.fromkeys(p for ids in prs_do_chamado.values() for p in ids))
        )

        for posicao, chamado in enumerate(chamados, start=1):
            # Relata antes de filtrar: o total é o tamanho do lote pedido, e
            # uma barra que pula números por causa de chamado vazio confunde
            # mais do que informa.
            self.progresso(
                Progresso("commits dos chamados nas PRs", posicao, len(chamados))
            )
            if not chamado:  # sem ID não tem como casar PR
                continue
            commits = self._commits_do_chamado(chamado, prs_do_chamado[chamado], por_pr)
            if commits:
                resultado[chamado] = commits
        return resultado

    def _varrer(self) -> None:
        """Uma passada que descobre tudo que mergeou desde a última.

        Substitui uma busca por chamado (27 requests numa versão real) por uma
        pergunta só. O que responde "quais PRs casam com ch1234" passa a ser o
        índice local, não o host.
        """
        # Marca = início da varredura, não o maior `updated_on` visto. PR
        # mergeada DURANTE esta varredura pode não aparecer nela; com o início
        # como marca, o `updated_on` dela é maior e a próxima janela a pega.
        inicio = datetime.datetime.now(datetime.UTC)
        # Sem marca (nunca varrido, ou varrido por outro host) = histórico
        # inteiro. Filtrar por data aqui deixaria de fora toda PR anterior, e o
        # chamado com PR antiga apareceria como sem entrega.
        marca = self.estado.marca_varredura(self.repo_estado, self.nome_host)
        # PR sem id é descartada, não um erro de forma.
        prs = [pr for pr in self.host.prs_mergeadas(marca) if pr.pr_id]
        # Índice e marca na mesma escrita: paginação que levantou no meio nunca
        # chega aqui, então a marca não avança por cima de um índice furado.
        self.estado.gravar_varredura(self.repo_estado, self.nome_host, prs, inicio)

    def _commits_das_prs(self, pr_ids: list[int]) -> dict[int, list[CommitRef]]:
        """Commits das PRs do lote: do cache, e o que faltar do host em paralelo."""
        # Só as PRs que casam com um chamado pedido vão ao host. O índice tem
        # 1118 PRs num repo real; buscar os commits de todas encostaria no limite
        # de taxa para responder pergunta que ninguém fez.
        por_pr = self.estado.commits_de_pr(self.repo_estado, pr_ids)
        faltam = [pr_id for pr_id in pr_ids if pr_id not in por_pr]
        if not faltam:
            return por_pr
        novas: dict[int, list[CommitRef]] = {}
        with ThreadPoolExecutor(max_workers=_TETO_HOST) as pool:
            futuros = {pool.submit(self.host.commits_da_pr, p): p for p in faltam}
            try:
                for posicao, futuro in enumerate(as_completed(futuros), start=1):
                    novas[futuros[futuro]] = futuro.result()
                    # No thread principal: o relator não é seguro entre threads.
                    self.progresso(Progresso("commits das PRs", posicao, len(faltam)))
            except BaseException:
                pool.shutdown(cancel_futures=True)
                raise
        # Só depois de todas: lote parcial no cache faria o próximo run dar o
        # chamado por resolvido sem a PR que falhou.
        # ponytail: PR cujos commits são todos merge commit grava vazio e vira
        # miss em todo run. Custa 1 request por run e não tem PR assim na
        # prática; se aparecer, o conserto é uma linha-sentinela por PR.
        self.estado.gravar_commits_de_pr(self.repo_estado, novas)
        return por_pr | novas

    def _commits_do_chamado(
        self, chamado: str, pr_ids: list[int], por_pr: dict[int, list[CommitRef]]
    ) -> list[CommitRef]:
        vistos: set[str] = set()
        commits: list[CommitRef] = []
        for pr_id in pr_ids:
            for c in por_pr.get(pr_id, []):
                if c.hash_origem in vistos:
                    continue
                # is_ancestor fica FORA do cache: é volátil. PR mergeada numa
                # branch que ainda não chegou na principal viraria commit
                # escondido para sempre se o filtro fosse gravado junto.
                if not self.git.is_ancestor(c.hash_origem, self._ref_principal()):
                    continue
                vistos.add(c.hash_origem)
                # o chamado vem do casamento, não da PR: duas tarefas podem
                # apontar para a mesma PR, então ele é carimbado aqui.
                commits.append(replace(c, chamado=chamado))
        return commits
