"""GithubPrs: plugin `HostPr` do GitHub (`[prs] fonte = "github"`).

Só fala com a API: varredura, índice, casamento com a referência, cache e
filtro pela principal são do núcleo (`PrCommitSource`,
docs/decisoes/036-fonte-de-pr-plugavel.md).

Montar não é usar: o construtor não lê token nem toca o git. O token e o
`dono/nome` (da URL do `origin`) saem na primeira chamada.
"""

from __future__ import annotations

import datetime
import os
import re
from collections.abc import Callable, Mapping
from enum import StrEnum

import httpx

from monitor_versoes_github.api import (
    API_PADRAO,
    CAMINHO_EU,
    CAMPO_TOKEN,
    CHAVE_API_URL,
    ApiGithub,
    VarGithub,
)
from motor.config import Tabela
from motor.config_edicao import Campo, Escopo, TipoCampo
from motor.domain.types import SEM_DATA, CommitRef, PrIndex
from motor.errors import ErroDeEntrada, RespostaInvalida

# git@github.com:dono/nome.git  |  https://usuario@github.com/dono/nome(.git)
_PADRAO_REMOTE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")

_PARAMS_PRS = {"state": "closed", "sort": "updated", "direction": "desc"}
# Acima disso a API não lista os commits do PR: o rebase não é reconhecível.
_MAX_COMMITS_PR = 250


class ChavePrs(StrEnum):
    """Chaves do `[prs]` que este plugin lê."""

    API_URL = CHAVE_API_URL


class _Campo(StrEnum):
    """Campos do JSON de pull requests."""

    NUMBER = "number"
    TITLE = "title"
    HEAD = "head"
    REF = "ref"
    MERGED_AT = "merged_at"
    UPDATED_AT = "updated_at"
    MERGE_COMMIT_SHA = "merge_commit_sha"
    COMMITS = "commits"
    SHA = "sha"
    PARENTS = "parents"
    COMMIT = "commit"
    MESSAGE = "message"
    AUTHOR = "author"
    COMMITTER = "committer"
    DATE = "date"


def parse_dono_repo(url: str) -> tuple[str, str]:
    """Extrai (dono, nome) da URL do remote origin, SSH ou HTTPS."""
    m = _PADRAO_REMOTE.search(url.strip())
    if m is None:
        raise RespostaInvalida(f"não consegui extrair dono/nome de {url!r}")
    return m.group(1), m.group(2)


def _objeto(item: object, o_que: str) -> Mapping[str, object]:
    if not isinstance(item, dict):
        raise RespostaInvalida(f"{o_que} do GitHub em formato inesperado: {item!r}")
    return item


def _sub(item: Mapping[str, object], chave: str) -> Mapping[str, object]:
    """Objeto aninhado; ausente ou de outro tipo vale como vazio."""
    valor = item.get(chave)
    return valor if isinstance(valor, dict) else {}


def _texto(item: Mapping[str, object], chave: str) -> str:
    valor = item.get(chave)
    return valor if isinstance(valor, str) else ""


def _data(bruto: object) -> datetime.datetime:
    """Data ISO da API; ausente ou inválida vira `SEM_DATA`, como no Bitbucket."""
    if not isinstance(bruto, str) or not bruto:
        return SEM_DATA
    try:
        return datetime.datetime.fromisoformat(bruto)
    except ValueError:
        return SEM_DATA


def _numero(pr: Mapping[str, object]) -> int | None:
    numero = pr.get(_Campo.NUMBER)
    if not isinstance(numero, int) or isinstance(numero, bool):
        return None
    return numero


def _pais(commit: Mapping[str, object]) -> list[str]:
    pais = commit.get(_Campo.PARENTS) or []
    if not isinstance(pais, list):
        raise RespostaInvalida(f"parents do GitHub em formato inesperado: {pais!r}")
    return [_texto(_objeto(p, "parent"), _Campo.SHA) for p in pais]


def _ref(commit: Mapping[str, object], dados: Mapping[str, object]) -> CommitRef:
    """`dados` é o próprio commit no `git/commits` e o `commit` no item do PR."""
    pais = _pais(commit)
    return CommitRef(
        hash_origem=_texto(commit, _Campo.SHA),
        parent=pais[0] if pais else "",
        commit_date=_data(_sub(dados, _Campo.COMMITTER).get(_Campo.DATE)),
        msg=_texto(dados, _Campo.MESSAGE),
    )


def _ref_git(commit: Mapping[str, object]) -> CommitRef:
    return _ref(commit, commit)


def _ref_do_pr(item: Mapping[str, object]) -> CommitRef:
    return _ref(item, _sub(item, _Campo.COMMIT))


def _autoria(dados: Mapping[str, object]) -> tuple[str, datetime.datetime] | None:
    """Mensagem e data de autoria; sem uma das duas, não serve para comparar."""
    mensagem = dados.get(_Campo.MESSAGE)
    data = _data(_sub(dados, _Campo.AUTHOR).get(_Campo.DATE))
    if not isinstance(mensagem, str) or data == SEM_DATA:
        return None
    return mensagem, data


def _eh_rebase(merge: Mapping[str, object], ultimo: Mapping[str, object]) -> bool:
    """O rebase recria o último commit com a mesma mensagem e a mesma autoria."""
    autoria = _autoria(merge)
    return autoria is not None and autoria == _autoria(_sub(ultimo, _Campo.COMMIT))


class GithubPrs:
    """`HostPr` do GitHub."""

    campos_config = (
        Campo(
            Escopo.GERAL,
            Tabela.PRS,
            ChavePrs.API_URL,
            TipoCampo.TEXTO,
            "URL da API do GitHub",
            descricao="Só muda no GitHub Enterprise Server",
            padrao=API_PADRAO,
            exemplo="https://github.empresa.com/api/v3",
        ),
        CAMPO_TOKEN,
    )

    def __init__(
        self,
        *,
        prs: Mapping[str, object],
        arquivos: tuple[str, ...],
        remote_url: Callable[[], str],
        env: Mapping[str, str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._arquivos = arquivos
        self._remote_url = remote_url
        self._env = env
        self._dono_repo: str | None = None
        self._api = ApiGithub(
            api_url=prs.get(ChavePrs.API_URL),
            tabela=Tabela.PRS,
            token=self._token,
            client=client,
            reaproveitar=True,
            dica_repo=self._dica_repo,
        )

    def __repr__(self) -> str:
        # Sem credencial: o repr aparece com --debug e em exceção.
        return "GithubPrs()"

    def _token(self) -> str:
        env = os.environ if self._env is None else self._env
        token = env.get(VarGithub.TOKEN, "").strip()
        if not token:
            lida = " e ".join(self._arquivos) or "nenhuma"
            raise ErroDeEntrada(
                f'[{Tabela.PRS}] fonte = "github" sem {VarGithub.TOKEN}: defina-a no '
                f"[ambiente] do config.toml central ou no shell (config lida: {lida})"
            )
        return token

    @staticmethod
    def _dica_repo(repo: str) -> str:
        return (
            f"confira o remote origin (dono/nome derivado: {repo!r}) "
            f"e o {VarGithub.TOKEN}"
        )

    def _repo(self) -> str:
        # Token antes do remote: a falta dele é o erro que o operador precisa ver primeiro.
        self._token()
        if self._dono_repo is None:
            dono, nome = parse_dono_repo(self._remote_url())
            self._dono_repo = f"{dono}/{nome}"
        return self._dono_repo

    def prs_mergeadas(self, desde: datetime.datetime | None, /) -> list[PrIndex]:
        repo = self._repo()
        indices: list[PrIndex] = []
        for pagina in self._api.paginas(f"/repos/{repo}/pulls", _PARAMS_PRS, repo):
            passou = False
            for item in pagina:
                pr = _objeto(item, "PR")
                atualizado = _data(pr.get(_Campo.UPDATED_AT))
                # Lista em ordem de atualização decrescente: daqui em diante é antigo.
                if desde is not None and atualizado < desde:
                    passou = True
                    continue
                numero = _numero(pr)
                if numero is None or not pr.get(_Campo.MERGED_AT):
                    continue
                indices.append(
                    PrIndex(
                        pr_id=numero,
                        titulo=_texto(pr, _Campo.TITLE),
                        branch=_texto(_sub(pr, _Campo.HEAD), _Campo.REF),
                        updated_on=atualizado,
                    )
                )
            if passou:
                break
        return indices

    def commits_da_pr(self, pr_id: int, /) -> list[CommitRef]:
        """Os commits do PR que chegaram à principal, pelo modo de merge inferido.

        Na dúvida entre rebase e squash vale squash: só devolve o commit que o
        próprio PR produziu, nunca um de outro PR.
        """
        repo = self._repo()
        base = self._api.base()
        pr = _objeto(
            self._api.json(
                self._api.obter(f"{base}/repos/{repo}/pulls/{pr_id}", None, repo)
            ),
            "PR",
        )
        sha = _texto(pr, _Campo.MERGE_COMMIT_SHA)
        merge = self._commit(repo, sha) if sha else None
        if merge is None:
            # Sem o commit na principal, o chamado cai no grep.
            return []
        if len(_pais(merge)) > 1:
            return [
                _ref_do_pr(c)
                for c in self._commits_do_pr(repo, pr_id)
                if len(_pais(c)) <= 1
            ]
        total = pr.get(_Campo.COMMITS)
        if isinstance(total, int) and total > _MAX_COMMITS_PR:
            return [_ref_git(merge)]
        do_pr = self._commits_do_pr(repo, pr_id)
        if do_pr and _eh_rebase(merge, do_pr[-1]):
            return self._caminho_do_rebase(repo, merge, len(do_pr))
        return [_ref_git(merge)]

    def _commit(self, repo: str, sha: str) -> Mapping[str, object] | None:
        """Commit pelo `git/commits`; None se a API não o encontra."""
        url = f"{self._api.base()}/repos/{repo}/git/commits/{sha}"
        resp = self._api.get(url, None, repo, ausente=True)
        return None if resp is None else _objeto(self._api.json(resp), "commit")

    def _commits_do_pr(self, repo: str, pr_id: int) -> list[Mapping[str, object]]:
        itens = self._api.listar(f"/repos/{repo}/pulls/{pr_id}/commits", {}, repo)
        return [_objeto(c, "commit do PR") for c in itens]

    def _caminho_do_rebase(
        self, repo: str, merge: Mapping[str, object], total: int
    ) -> list[CommitRef]:
        """Os `total` commits da principal que terminam em `merge`, pelo primeiro pai.

        Merge commit ou commit não encontrado encerra o caminho: devolve o já
        percorrido.
        """
        caminho = [merge]
        while len(caminho) < total:
            pais = _pais(caminho[-1])
            anterior = self._commit(repo, pais[0]) if pais else None
            if anterior is None or len(_pais(anterior)) > 1:
                break
            caminho.append(anterior)
        return [_ref_git(c) for c in reversed(caminho)]

    def verificar_credenciais(self) -> None:
        """Chamada autenticada que não depende de repo (`GET /user`)."""
        self._token()
        self._api.obter(self._api.base() + CAMINHO_EU, None, None)

    def fechar(self) -> None:
        """Fecha o cliente próprio; o injetado é de quem injetou."""
        self._api.fechar()
