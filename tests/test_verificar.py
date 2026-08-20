from __future__ import annotations

import datetime

import pytest

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import Atribuicao, CommitRef, RepoInfo, VersaoInfo, VersionType
from motor.engine.deps import Deps
from motor.engine.verificar import verificar
from motor.errors import MotorError
from motor.ports import MergePrediction

D = datetime.datetime(2026, 1, 1)


def _deps(git, tasks, commits, estado) -> Deps:
    return Deps(git=git, tasks=tasks, estado=estado, repo="r", _commit_source=commits)


def _estado_com_repo() -> FakeEstado:
    return FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})


class _GitQueTagueiaNoFetch(FakeGit):
    """FakeGit em que a tag da 13.34.0 so existe DEPOIS do fetch.

    E o unico jeito de pinar a ordem: no git de verdade `fetch` e o ponto em
    que a tag criada em outra maquina entra no ref store local. Se o verificar
    ler as refs antes de buscar, esta tag e invisivel no run inteiro.
    """

    def fetch(self, remote: str) -> None:
        super().fetch(remote)
        self.tags["13.34.0"] = True


class _GitComTagAntesDaBranch(FakeGit):
    """A tag ficou em m0, mas a branch avancou depois da liberacao."""

    def resolve_ref(self, ref: str) -> str:
        if ref == "refs/tags/13.34.0":
            return "m0"
        return super().resolve_ref(ref)


class _GitComPrevisaoEncadeada(FakeGit):
    def predict_merge(self, parent: str, branch_tip: str, commit: str):
        return MergePrediction(
            conflita=commit == "a1" and branch_tip != "arvore-a0",
            arquivos_conflito=[],
            arvore_resultante=f"arvore-{commit}",
        )


def _git(tags: dict[str, bool] | None = None, classe=FakeGit) -> FakeGit:
    """Grafo: m0 e a raiz; a0 e um commit que so existe no master.

    As versoes ficam em m0, entao a0 e faltante em todas elas — e o que
    permite afirmar que o commit foi cobrado, e nao herdado da base.
    """
    git = classe(tags=tags or {})
    git.add_commit("m0", "", "raiz", D)
    git.add_commit("a0", "m0", "ch123123 alfa", D)
    git.set_branch("master", "a0")
    git.set_branch("origin/master", "a0")
    for versao in ("13.33.1", "13.34.0", "14.0.0"):
        git.set_branch(versao, "m0")
    return git


def test_verificar_une_tarefas_das_versoes_abertas_menores():
    git = _git()
    tasks = FakeTaskSource(chamados={"13.33.1": ["123123"], "14.0.0": []})
    commits = FakeCommitSource(por_chamado={
        "123123": [CommitRef(hash_origem="a0", parent="m0", chamado="123123",
                             commit_date=D, msg="ch123123 alfa")]
    })
    estado = _estado_com_repo()
    # base gravada na criacao: m0. Sem isso o BaseResolver resolveria "master",
    # que hoje aponta para a0 — e o commit apareceria como ja presente.
    estado.registrar_versao("r", VersaoInfo(numero="14.0.0", tipo=VersionType.FECHADA,
                                            base_ref="master", base_commit="m0"))

    status = verificar(_deps(git, tasks, commits, estado), "14.0.0")

    # marcada para 13.33.1, cobrada na 14.0.0
    assert [c.hash_origem for c in status.faltantes] == ["a0"]
    assert git.fetched == ["origin"]
    # sem branch remota nao ha o que puxar
    assert git.pulled == []
    assert git.removed_worktrees == ["14.0.0"]


def test_verificar_congela_versao_quando_a_tag_aparece():
    git = _git(tags={"13.34.0": True})
    estado = _estado_com_repo()
    estado.registrar_versao("r", VersaoInfo(numero="13.34.0", tipo=VersionType.AJUSTADA,
                                            base_ref="13.33.0", base_commit="m0"))
    estado.substituir_atribuicoes("r", "13.34.0", [
        Atribuicao(chamado="123456", marcada="13.34.0", estado="aplicado",
                   commits=["a0"])
    ])

    status = verificar(_deps(git, FakeTaskSource(), FakeCommitSource(), estado),
                       "13.34.0")

    assert estado.versao("r", "13.34.0").liberada_em is not None
    # devolve o snapshot congelado, nao recalcula
    assert status.verde is True
    assert status.tasks_novas == []
    # e o snapshot carrega o que so o banco registra (spec §4): sem a data e os
    # chamados a saida sai byte-a-byte igual a de uma versao verde em
    # construcao, e um snapshot vazio imprime "verde: True" porque all([]) e
    # True — o operador nao distingue "fez o trabalho" de "nao recalculou".
    assert status.liberada_em == estado.versao("r", "13.34.0").liberada_em
    assert status.chamados == ["123456"]


def test_verificar_nao_grava_em_versao_liberada():
    git = _git(tags={"13.34.0": True})
    estado = _estado_com_repo()
    estado.registrar_versao("r", VersaoInfo(numero="13.34.0", tipo=VersionType.AJUSTADA,
                                            base_ref="13.33.0", base_commit="m0"))
    tasks = FakeTaskSource(chamados={"13.34.0": ["999111"]})

    verificar(_deps(git, tasks, FakeCommitSource(), estado), "13.34.0")

    # a trava do fake nao disparou => nao tentou escrever
    assert estado.atribuicoes("r", "13.34.0") == []


def test_auditar_versao_liberada_compara_a_tag_sem_mudar_snapshot():
    git = _git(tags={"13.34.0": True}, classe=_GitComTagAntesDaBranch)
    # A branch recebeu a0 depois da tag. Auditar a branch daria falso-verde;
    # o artefato liberado na tag ainda nao contem esse commit.
    git.set_branch("13.34.0", "a0")
    estado = _estado_com_repo()
    estado.registrar_versao(
        "r",
        VersaoInfo(
            numero="13.34.0",
            tipo=VersionType.AJUSTADA,
            base_ref="13.33.0",
            base_commit="m0",
        ),
    )
    estado.marcar_liberadas("r", {"13.34.0": D})
    tasks = FakeTaskSource(chamados={"13.34.0": ["123123"]})
    commits = FakeCommitSource(
        por_chamado={
            "123123": [
                CommitRef(
                    hash_origem="a0",
                    parent="m0",
                    chamado="123123",
                    commit_date=D,
                    msg="ch123123 alfa",
                )
            ]
        }
    )

    status = verificar(
        _deps(git, tasks, commits, estado), "13.34.0", auditar=True
    )

    assert [c.hash_origem for c in status.faltantes] == ["a0"]
    assert estado.atribuicoes("r", "13.34.0") == []
    assert git.pulled == []
    assert git.removed_worktrees == []


def test_auditar_recusa_versao_ainda_aberta():
    git = _git()
    estado = _estado_com_repo()
    estado.registrar_versao(
        "r",
        VersaoInfo(
            numero="13.34.0",
            tipo=VersionType.AJUSTADA,
            base_ref="13.33.0",
            base_commit="m0",
        ),
    )

    with pytest.raises(MotorError, match="liberada"):
        verificar(
            _deps(git, FakeTaskSource(), FakeCommitSource(), estado),
            "13.34.0",
            auditar=True,
        )


def test_verificar_commit_sumido_do_estado_nunca_entra_em_conflitantes():
    """Invariante documentada em VersionStatus: `conflitantes` e subconjunto de
    `faltantes` (lado alvo), nunca de `commits_sumidos`. Commit que so o estado
    conhecia e que sumiu do alvo nao e candidato a cherry-pick, entao
    predict_merge nao pode nem ser consultado para ele.

    Herdado do teste equivalente contra o lock: sem ele a guarda
    `hash_ in candidatos_conflito` do verificar fica sem cobertura. Os dois
    commits tem conflito plantado de proposito — assim a assercao distingue
    "a guarda funciona" de "nenhum commit conflita".
    """
    git = _git()
    git.add_commit("sumido", "", "ch999999 tarefa que saiu do Tickio", D)
    git.merge_predictions["a0"] = MergePrediction(conflita=True, arquivos_conflito=[])
    git.merge_predictions["sumido"] = MergePrediction(
        conflita=True, arquivos_conflito=[]
    )
    tasks = FakeTaskSource(chamados={"14.0.0": ["123123"]})
    commits = FakeCommitSource(por_chamado={
        "123123": [CommitRef(hash_origem="a0", parent="m0", chamado="123123",
                             commit_date=D, msg="ch123123 alfa")]
    })
    estado = _estado_com_repo()
    estado.registrar_versao("r", VersaoInfo(numero="14.0.0", tipo=VersionType.FECHADA,
                                            base_ref="master", base_commit="m0"))
    estado.substituir_atribuicoes("r", "14.0.0", [
        Atribuicao(chamado="999999", marcada="14.0.0", estado="aplicado",
                   commits=["sumido"])
    ])

    status = verificar(_deps(git, tasks, commits, estado), "14.0.0")

    assert status.commits_sumidos == ["sumido"]
    assert status.estado_integro is False
    assert [c.hash_origem for c in status.conflitantes] == ["a0"]


def test_verificar_prediz_conflitos_na_ordem_do_cherry_pick():
    git = _git(classe=_GitComPrevisaoEncadeada)
    git.add_commit("a1", "a0", "ch123123 beta", D + datetime.timedelta(seconds=1))
    git.set_branch("master", "a1")
    git.set_branch("origin/master", "a1")
    tasks = FakeTaskSource(chamados={"14.0.0": ["123123"]})
    commits = FakeCommitSource(
        por_chamado={
            "123123": [
                CommitRef(
                    hash_origem="a0",
                    parent="m0",
                    chamado="123123",
                    commit_date=D,
                    msg="ch123123 alfa",
                ),
                CommitRef(
                    hash_origem="a1",
                    parent="a0",
                    chamado="123123",
                    commit_date=D + datetime.timedelta(seconds=1),
                    msg="ch123123 beta",
                ),
            ]
        }
    )
    estado = _estado_com_repo()
    estado.registrar_versao(
        "r",
        VersaoInfo(
            numero="14.0.0",
            tipo=VersionType.FECHADA,
            base_ref="master",
            base_commit="m0",
        ),
    )

    status = verificar(_deps(git, tasks, commits, estado), "14.0.0")

    assert [c.hash_origem for c in status.faltantes] == ["a0", "a1"]
    assert status.conflitantes == []


def test_verificar_ignora_tag_de_versao_que_o_motor_nunca_viu():
    """13.99.0 existe como tag e nao resolve para commit nenhum no fake. E isso
    que faz o teste discriminar: com a guarda `conhecida is not None`, o
    verificar nunca toca no git por causa dela; sem a guarda, o
    resolve_ref("refs/tags/13.99.0") estoura e o comando morre por causa de uma
    versao que nao e nem o alvo.

    Assertar so que `estado.versao(...)` continua None nao provava nada: so
    registrar_versao cria linha, e o verificar so registra a versao alvo.
    """
    git = _git(tags={"13.99.0": True})
    estado = _estado_com_repo()
    estado.registrar_versao("r", VersaoInfo(numero="14.0.0", tipo=VersionType.FECHADA,
                                            base_ref="master", base_commit="m0"))

    status = verificar(_deps(git, FakeTaskSource(), FakeCommitSource(), estado),
                       "14.0.0")

    assert status.verde is True
    # nada a congelar: sem linha no estado, nao ha snapshot para proteger
    assert estado.versao("r", "13.99.0") is None


def test_verificar_busca_antes_de_ler_as_refs_e_congela_tag_nova_no_mesmo_run():
    """A 13.34.0 foi liberada em outra maquina: a tag so aparece no fetch.

    Pina a ORDEM, nao so o comportamento. Com o fetch depois da leitura das
    refs, `tags` sai vazia, o congelamento e pulado, e o substituir_atribuicoes
    do fim reescreve o snapshot de uma versao ja liberada — a trava do banco
    nao salva, porque `liberada_em` ainda esta NULL.
    """
    git = _git(classe=_GitQueTagueiaNoFetch)
    estado = _estado_com_repo()
    estado.registrar_versao("r", VersaoInfo(numero="13.34.0", tipo=VersionType.AJUSTADA,
                                            base_ref="13.33.0", base_commit="m0"))
    estado.substituir_atribuicoes("r", "13.34.0", [
        Atribuicao(chamado="123456", marcada="13.34.0", estado="aplicado",
                   commits=["a0"])
    ])
    # tarefa nova no Tickio: e com ela que o run reescreveria o snapshot
    tasks = FakeTaskSource(chamados={"13.34.0": ["999111"]})

    status = verificar(_deps(git, tasks, FakeCommitSource(), estado), "13.34.0")

    assert git.fetched == ["origin"]
    assert estado.versao("r", "13.34.0").liberada_em is not None
    # o snapshot da versao liberada continua intacto, sem a tarefa nova
    assert [a.chamado for a in estado.atribuicoes("r", "13.34.0")] == ["123456"]
    assert status.verde is True


def test_verificar_registra_a_base_na_primeira_vez_que_ve_a_versao():
    """Nada pre-registrado: e o unico teste que entra no ramo `info is None`.

    Pre-registrar a versao no arrange (o que os outros fazem) e exatamente o
    que impede este ramo de rodar. Ele tambem prova a ordem
    registrar_versao -> substituir_atribuicoes: sem o registro, o
    substituir_atribuicoes do fim levantaria MotorError("nao registrada").
    """
    git = _git()
    git.remotes["14.0.0"] = True  # branch ja publicada: exercita o pull
    tasks = FakeTaskSource(chamados={"14.0.0": ["123123"]})
    commits = FakeCommitSource(por_chamado={
        "123123": [CommitRef(hash_origem="a0", parent="m0", chamado="123123",
                             commit_date=D, msg="ch123123 alfa")]
    })
    estado = _estado_com_repo()

    verificar(_deps(git, tasks, commits, estado), "14.0.0")

    gravada = estado.versao("r", "14.0.0")
    assert gravada is not None
    # 14.0.0 e X.0.0, logo a base e master, que aponta para a0
    assert (gravada.base_ref, gravada.base_commit) == ("master", "a0")
    assert gravada.tipo == VersionType.FECHADA
    # escreveu as atribuicoes, ou seja o registro veio antes
    assert [a.chamado for a in estado.atribuicoes("r", "14.0.0")] == ["123123"]
    assert git.fetched == ["origin"]
    assert git.pulled == ["14.0.0"]


def test_verificar_reporta_suspeita_de_cherry_pick_manual_sem_x():
    """Nivel 4 do oraculo: pick manual sem `-x` cujo conteudo mudou na
    resolucao do conflito. O patch-id diverge, entao o nivel 3 nao pega, mas
    mensagem + arquivos batem. Sai em suspeitos_conteudo E continua em
    faltantes — suspeita nao conta como presente.

    Cobre o append em verificar.py e o repasse em reconcile.py. Sem isto,
    `atualizar` levanta MotorError num campo que a suite nunca preenche.
    """
    git = _git()
    git.add_commit("alvo0", "m0", "ch123123 alfa", D)  # mesma msg que a0
    git.set_branch("14.0.0", "alvo0")
    git.file_changes["a0"] = frozenset({"a.txt"})
    git.file_changes["alvo0"] = frozenset({"a.txt"})
    tasks = FakeTaskSource(chamados={"14.0.0": ["123123"]})
    commits = FakeCommitSource(por_chamado={
        "123123": [CommitRef(hash_origem="a0", parent="m0", chamado="123123",
                             commit_date=D, msg="ch123123 alfa")]
    })
    estado = _estado_com_repo()
    estado.registrar_versao("r", VersaoInfo(numero="14.0.0", tipo=VersionType.FECHADA,
                                            base_ref="master", base_commit="m0"))

    status = verificar(_deps(git, tasks, commits, estado), "14.0.0")

    assert [c.hash_origem for c in status.suspeitos_conteudo] == ["a0"]
    assert [c.hash_origem for c in status.faltantes] == ["a0"]
    assert status.verde is False
