"""GitlabPrs: plugin `HostPr` do GitLab (`[prs] fonte = "gitlab"`).

Só fala com a API: varredura, índice, casamento com a referência, cache e
filtro pela principal são do núcleo (`PrCommitSource`,
docs/decisoes/036-fonte-de-pr-plugavel.md).

Montar não é usar: o construtor não lê token nem toca o git. O token e o
caminho do projeto (da URL do `origin`) saem na primeira chamada.
"""

from __future__ import annotations

import datetime
import os
import re
from collections.abc import Callable, Mapping
from enum import StrEnum
from urllib.parse import quote, urlsplit

import httpx

from monitor_versoes_gitlab.api import (
    CAMINHO_EU,
    CAMPO_TOKEN,
    CHAVE_URL,
    URL_PADRAO,
    ApiGitlab,
    VarGitlab,
    caminho_projeto,
)
from motor.config import Tabela
from motor.config_edicao import Campo, Escopo, TipoCampo
from motor.domain.types import SEM_DATA, CommitRef, PrIndex
from motor.errors import ErroDeEntrada, RespostaInvalida

# usuario@host:grupo/sub/nome(.git)
_PADRAO_SCP = re.compile(r"^[^@/:]+@[^/:]+:(.+)$")
_ESQUEMA_SSH = "ssh"
_ESQUEMA_HTTPS = "https"
_SUFIXO_GIT = ".git"
_MIN_SEGMENTOS = 2


class ChavePrs(StrEnum):
    """Chaves do `[prs]` que este plugin lê."""

    URL = CHAVE_URL


class _Campo(StrEnum):
    """Campos do JSON de merge requests."""

    IID = "iid"
    TITLE = "title"
    SOURCE_BRANCH = "source_branch"
    UPDATED_AT = "updated_at"
    SQUASH_COMMIT_SHA = "squash_commit_sha"
    ID = "id"
    PARENT_IDS = "parent_ids"
    COMMITTED_DATE = "committed_date"
    MESSAGE = "message"


class _Param(StrEnum):
    STATE = "state"
    UPDATED_AFTER = "updated_after"


class _Estado(StrEnum):
    MERGED = "merged"


def _caminho_do_projeto(remote: str, base: str) -> str:
    """Caminho do projeto (`grupo/sub/nome`) na URL do `origin`, SSH ou HTTPS."""
    remote = remote.strip()
    partes = urlsplit(remote)
    scp = _PADRAO_SCP.match(remote)
    if partes.scheme in (_ESQUEMA_SSH, _ESQUEMA_HTTPS):
        caminho = partes.path
    elif scp is not None:
        caminho = scp.group(1)
    else:
        raise RespostaInvalida(f"não consegui extrair o projeto de {remote!r}")
    if partes.scheme == _ESQUEMA_HTTPS:
        # Instância em subcaminho: ele faz parte da URL, não do projeto.
        b = urlsplit(base)
        prefixo = b.path.rstrip("/")
        mesma = (partes.scheme, partes.hostname, partes.port) == (
            b.scheme,
            b.hostname,
            b.port,
        )
        if mesma and prefixo and caminho.startswith(prefixo + "/"):
            caminho = caminho[len(prefixo) :]
    caminho = caminho.strip("/").removesuffix(_SUFIXO_GIT)
    segmentos = caminho.split("/")
    if len(segmentos) < _MIN_SEGMENTOS or "" in segmentos:
        raise RespostaInvalida(f"não consegui extrair o projeto de {remote!r}")
    return caminho


def _objeto(item: object, o_que: str) -> Mapping[str, object]:
    if not isinstance(item, dict):
        raise RespostaInvalida(f"{o_que} do GitLab em formato inesperado: {item!r}")
    return item


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


def _pais(commit: Mapping[str, object]) -> list[str]:
    pais = commit.get(_Campo.PARENT_IDS) or []
    if not isinstance(pais, list) or not all(isinstance(p, str) for p in pais):
        raise RespostaInvalida(f"parent_ids do GitLab em formato inesperado: {pais!r}")
    return pais


def _ref(commit: Mapping[str, object]) -> CommitRef:
    pais = _pais(commit)
    return CommitRef(
        hash_origem=_texto(commit, _Campo.ID),
        parent=pais[0] if pais else "",
        commit_date=_data(commit.get(_Campo.COMMITTED_DATE)),
        msg=_texto(commit, _Campo.MESSAGE),
    )


class GitlabPrs:
    """`HostPr` do GitLab."""

    campos_config = (
        Campo(
            Escopo.GERAL,
            Tabela.PRS,
            ChavePrs.URL,
            TipoCampo.TEXTO,
            "URL do GitLab",
            descricao="Só muda em GitLab self-managed",
            padrao=URL_PADRAO,
            exemplo="https://gitlab.empresa.com",
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
        self._caminho: str | None = None
        self._api = ApiGitlab(
            url=prs.get(ChavePrs.URL),
            tabela=Tabela.PRS,
            token=self._token,
            client=client,
            reaproveitar=True,
            dica_projeto=self._dica_projeto,
        )

    def __repr__(self) -> str:
        # Sem credencial: o repr aparece com --debug e em exceção.
        return "GitlabPrs()"

    def _token(self) -> str:
        env = os.environ if self._env is None else self._env
        token = env.get(VarGitlab.TOKEN, "").strip()
        if not token:
            lida = " e ".join(self._arquivos) or "nenhuma"
            raise ErroDeEntrada(
                f'[{Tabela.PRS}] fonte = "gitlab" sem {VarGitlab.TOKEN}: defina-a no '
                f"[ambiente] do config.toml central ou no shell (config lida: {lida})"
            )
        return token

    @staticmethod
    def _dica_projeto(caminho: str) -> str:
        return (
            f"confira o remote origin (caminho derivado: {caminho!r}) "
            f"e o {VarGitlab.TOKEN}"
        )

    def _projeto(self) -> str:
        # Token antes do remote: a falta dele é o erro que o operador precisa ver primeiro.
        self._token()
        if self._caminho is None:
            self._caminho = _caminho_do_projeto(self._remote_url(), self._api.base())
        return self._caminho

    def prs_mergeadas(self, desde: datetime.datetime | None, /) -> list[PrIndex]:
        projeto = self._projeto()
        params: dict[str, str] = {_Param.STATE: _Estado.MERGED}
        if desde is not None:
            params[_Param.UPDATED_AFTER] = desde.isoformat()
        itens = self._api.listar(
            f"{caminho_projeto(projeto)}/merge_requests", params, projeto
        )
        assert itens is not None  # sem `ausente`, 404 levanta
        indices: list[PrIndex] = []
        for item in itens:
            mr = _objeto(item, "MR")
            iid = mr.get(_Campo.IID)
            if not isinstance(iid, int) or isinstance(iid, bool):
                continue
            indices.append(
                PrIndex(
                    pr_id=iid,
                    titulo=_texto(mr, _Campo.TITLE),
                    branch=_texto(mr, _Campo.SOURCE_BRANCH),
                    updated_on=_data(mr.get(_Campo.UPDATED_AT)),
                )
            )
        return indices

    def commits_da_pr(self, pr_id: int, /) -> list[CommitRef]:
        """Os commits do MR; com squash, só o commit de squash.

        404 em qualquer consulta devolve vazio: o projeto já foi achado na
        varredura, então o MR ou commit é que sumiu, e o chamado cai no grep.
        """
        projeto = self._projeto()
        raiz = f"{caminho_projeto(projeto)}/merge_requests/{pr_id}"
        resp = self._api.get(self._api.url(raiz), None, projeto, ausente=True)
        if resp is None:
            return []
        mr = _objeto(self._api.json(resp), "MR")
        sha = _texto(mr, _Campo.SQUASH_COMMIT_SHA)
        if sha:
            commit = self._commit(projeto, sha)
            return [] if commit is None else [_ref(commit)]
        itens = self._api.listar(f"{raiz}/commits", {}, projeto, ausente=True)
        if itens is None:
            return []
        commits: list[Mapping[str, object]] = []
        for item in itens:
            id_ = _texto(_objeto(item, "commit do MR"), _Campo.ID)
            if not id_:
                raise RespostaInvalida(f"commit do MR sem id: {item!r}")
            # A lista não traz `parent_ids` de forma confiável: cada commit é pedido.
            commit = self._commit(projeto, id_)
            if commit is None:
                return []
            commits.append(commit)
        return [_ref(c) for c in commits if len(_pais(c)) <= 1]

    def _commit(self, projeto: str, sha: str) -> Mapping[str, object] | None:
        """Commit do repositório; None se a API não o encontra."""
        caminho = f"{caminho_projeto(projeto)}/repository/commits/{quote(sha, safe='')}"
        resp = self._api.get(self._api.url(caminho), None, projeto, ausente=True)
        return None if resp is None else _objeto(self._api.json(resp), "commit")

    def verificar_credenciais(self) -> str | None:
        """Chamada autenticada que não depende de projeto (`GET /user`)."""
        self._token()
        self._api.obter(self._api.url(CAMINHO_EU), None, None)
        return None

    def fechar(self) -> None:
        """Fecha o cliente próprio; o injetado é de quem injetou."""
        self._api.fechar()
