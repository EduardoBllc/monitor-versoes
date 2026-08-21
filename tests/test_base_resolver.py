"""Porte de internal/services/base_resolver_test.go."""

import datetime

import pytest

from motor.adapters.git.fake import FakeGit
from motor.errors import NaoEncontrado
from motor.services.base_resolver import BaseResolver


def test_base_resolver_resolve():
    g = FakeGit()
    g.add_commit("hash136", "", "base 13.6.0", datetime.datetime.now(datetime.timezone.utc))
    g.set_branch("13.6.0", "hash136")

    resolver = BaseResolver(git=g)
    base = resolver.resolve("13.7.0")

    assert base.ref == "13.6.0" and base.commit == "hash136", f"base = {base!r}, quer ref=13.6.0 commit=hash136"


def test_base_resolver_usa_a_ref_de_rastreamento_quando_nao_ha_head_local():
    """Base cortada em outra maquina: chega no fetch como
    refs/remotes/origin/13.6.0, sem head local e sem tag.
    `list_version_branches` ja a enxerga (por isso `inferir_base` a escolhe),
    mas `git rev-parse 13.6.0` nunca consulta refs/remotes/<remoto>/X — sem a
    segunda tentativa a base correta viraria erro.
    """
    g = FakeGit(remote_refs={"13.6.0": "hash136"})
    g.add_commit("hash136", "", "base 13.6.0", datetime.datetime.now(datetime.timezone.utc))

    base = BaseResolver(git=g).resolve("13.7.0")

    assert (base.ref, base.commit) == ("13.6.0", "hash136")


def test_base_resolver_prefere_o_head_local_a_ref_de_rastreamento():
    """A ordem dos candidatos e load-bearing e permanente.

    `git fetch` nao fast-forwarda head local, entao local e ref de rastreamento
    ROTINEIRAMENTE discordam para uma versao-base. A base resolvida aqui e
    gravada uma vez em `versao.base_commit` e todo julgamento de presenca
    posterior e feito contra ela: inverter esta ordem grava outro SHA e envenena
    o oraculo pela vida inteira da versao, sem nada ficar vermelho.
    """
    g = FakeGit(
        branches={"13.6.0": "local136"},
        remote_refs={"13.6.0": "remoto136"},
    )
    for h in ("local136", "remoto136"):
        g.add_commit(h, "", f"base 13.6.0 em {h}", datetime.datetime.now(datetime.timezone.utc))

    base = BaseResolver(git=g).resolve("13.7.0")

    assert base.commit == "local136", (
        f"base.commit = {base.commit!r}; o head local tem de vencer a ref de "
        "rastreamento — ver a ordem de `candidatos` em base_resolver.py"
    )


def test_ref_que_nao_resolve_em_nenhum_candidato_e_nao_encontrado():
    """Nao esta propagando erro de porta: as duas tentativas (nome puro e ref de
    rastreamento) falharam, e isso e um fato novo — "nao achei a base".

    list_version_branches sobrescrita simula uma listagem defasada (a ref
    apareceu na varredura mas nao existe mais nem como head local nem como
    ref de rastreamento) - com FakeGit padrao as duas fontes sao sempre
    consistentes, e o cenario nunca ocorreria.
    """

    class _GitComListagemDesatualizada(FakeGit):
        def list_version_branches(self) -> list[str]:
            return ["13.6.0"]

    git = _GitComListagemDesatualizada()

    with pytest.raises(NaoEncontrado, match="resolvendo ref"):
        BaseResolver(git=git).resolve("13.7.0")
