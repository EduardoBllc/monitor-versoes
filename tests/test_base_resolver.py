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


def test_bug_do_adapter_propaga_e_nao_vira_base_nao_encontrada():
    """O `except` do laco captura `MotorError` para tentar o candidato seguinte,
    e no fim relata "nao achei a base". Excecao fora do contrato nao pode entrar
    nesse fluxo: seria um bug do adapter saindo como `NaoEncontrado`, mandando o
    operador procurar uma base que existe.

    Forma de codigo propria — laco de duas tentativas, `raise` fora do `except`
    —, por isso tem teste proprio e nao herda o do oraculo de presenca.
    """
    tentativas: list[str] = []

    class _GitComBug(FakeGit):
        def resolve_ref(self, ref: str, /) -> str:
            tentativas.append(ref)
            raise RuntimeError("bug no adapter")

    g = _GitComBug()
    g.add_commit("hash136", "", "base", datetime.datetime.now(datetime.timezone.utc))
    g.set_branch("13.6.0", "hash136")

    with pytest.raises(RuntimeError, match="bug no adapter"):
        BaseResolver(git=g).resolve("13.7.0")

    # curto-circuita no primeiro: insistir no segundo candidato depois de um bug
    # so troca a excecao util por "resolvendo ref 13.6.0: ...".
    assert tentativas == ["13.6.0"], f"tentou de novo apos o bug: {tentativas}"


def test_base_de_versao_existente_e_o_ponto_de_corte_nao_o_tip_da_base():
    """A base de uma versao que JA existe e onde ela foi cortada, nao onde a
    ref-base esta agora.

    `X.0.0` sai do master, e o master anda todo dia. Resolver o nome puro dava
    o tip do momento em que o motor viu a versao pela primeira vez — na 15.0.0
    do vendabemweb, 20 dias depois do corte real. O corte e o que decide quais
    liberadas voltam a ser fonte de alvo (`liberadas_no_alvo`, spec §2): com o
    corte 20 dias adiantado, dez versoes 14.x liberadas nesse intervalo sairam
    do alvo em silencio, levando 85 chamados junto.
    """
    agora = datetime.datetime.now(datetime.timezone.utc)
    g = FakeGit()
    g.add_commit("corte", "", "master no ponto de corte", agora)
    g.add_commit("master_depois", "corte", "master andou depois do corte", agora)
    g.add_commit("trabalho_15", "corte", "commit da 15.0.0", agora)
    g.set_branch("master", "master_depois")
    g.set_branch("15.0.0", "trabalho_15")

    base = BaseResolver(git=g).resolve("15.0.0")

    assert (base.ref, base.commit) == ("master", "corte"), (
        f"base = {base!r}; quer o ponto de corte 'corte', nao o tip 'master_depois'"
    )


def test_base_de_versao_que_ainda_nao_existe_e_o_tip_da_ref_base():
    """O outro lado da mesma regra, e o caso do `criar`: a versao vai nascer
    agora, entao o tip da ref-base E o ponto de corte. Sem esta metade, `criar`
    quebraria — nao ha ref da versao para cruzar com a base.
    """
    agora = datetime.datetime.now(datetime.timezone.utc)
    g = FakeGit()
    g.add_commit("corte", "", "master no ponto de corte", agora)
    g.add_commit("master_depois", "corte", "master andou depois do corte", agora)
    g.set_branch("master", "master_depois")

    base = BaseResolver(git=g).resolve("15.0.0")

    assert base.commit == "master_depois", (
        f"base.commit = {base.commit!r}; versao inexistente corta do tip"
    )


def test_base_de_ajustada_e_o_corte_mesmo_com_commit_novo_na_anterior():
    """Vale tambem para a ajustada, que e a maioria: a 14.9.0 recebe um hotfix
    depois de a 14.10.0 ter sido cortada dela, e resolver a tag daria esse
    hotfix como base — um commit que a 14.10.0 nunca teve.
    """
    agora = datetime.datetime.now(datetime.timezone.utc)
    g = FakeGit(tags={"14.9.0": True})
    g.add_commit("corte", "", "tip da 14.9.0 no corte", agora)
    g.add_commit("hotfix_149", "corte", "hotfix na 14.9.0 depois do corte", agora)
    g.add_commit("trabalho_1410", "corte", "commit da 14.10.0", agora)
    g.set_branch("14.9.0", "hotfix_149")
    g.set_branch("14.10.0", "trabalho_1410")

    base = BaseResolver(git=g).resolve("14.10.0")

    assert (base.ref, base.commit) == ("14.9.0", "corte"), (
        f"base = {base!r}; quer o corte 'corte', nao o hotfix 'hotfix_149'"
    )
