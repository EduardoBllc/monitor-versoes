"""O canal de progresso: quem relata, o que relata, e o silencio por default.

Um relator e so uma funcao que recebe Progresso. `relatos.append` serve de
double — nao ha mock aqui, os asserts sao sobre os eventos de verdade.
"""

from __future__ import annotations

import datetime
import io

from motor.adapters.commitsource.bitbucket import BitbucketPRCommitSource
from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.commitsource.grep import GrepCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import (
    Atribuicao,
    CommitRef,
    RepoInfo,
    VersaoInfo,
    VersionType,
)
from motor.engine.atualizar import atualizar
from motor.engine.consultar import consultar
from motor.engine.deps import Deps
from motor.engine.reconstruir_estado import reconstruir_estado
from motor.engine.verificar import verificar
from rich.console import Console

from motor.__main__ import _escrever_progresso, _relator_do_cli
from motor.progresso import Progresso, SlotProgresso, silencioso
from motor.services.target_resolver import TargetResolver
from motor.tui import renderizar_progresso

D = datetime.datetime(2026, 1, 1)


def _fases(relatos: list[Progresso]) -> list[tuple[str, int, int]]:
    return [(p.fase, p.feito, p.total) for p in relatos]


def _renderizado(renderable, *, estilos: bool = False) -> str:
    # com estilos quando o que muda e cor, nao caractere: e o caso do pulso.
    console = Console(record=True, width=80, color_system="truecolor" if estilos else None)
    console.print(renderable)
    return console.export_text(styles=estilos)


def test_resolver_relata_uma_fase_por_versao_consultada():
    relatos: list[Progresso] = []
    resolver = TargetResolver(
        tasks=FakeTaskSource(chamados={"13.33.0": ["1"], "13.34.0": ["2"]}),
        commits=FakeCommitSource(),
        progresso=relatos.append,
    )

    resolver.resolve("13.34.0", ["13.33.0", "13.34.0"])

    assert _fases(relatos) == [
        ("chamados marcados no Tickio", 1, 2),
        ("chamados marcados no Tickio", 2, 2),
    ]


def test_grep_relata_a_varredura_sem_contagem():
    """Um `git log --grep` unico nao sabe dizer quanto falta: total = 0, e a
    TUI desenha spinner em vez de barra parada em 0%.
    """
    git = FakeGit()
    git.add_commit("a1", "m0", "ch1 algo", D)
    git.set_branch("master", "a1")
    relatos: list[Progresso] = []

    GrepCommitSource(git=git, ref="master", progresso=relatos.append).resolve(["1"])

    assert _fases(relatos) == [("commits dos chamados no histórico", 0, 0)]


def test_bitbucket_relata_a_varredura_e_depois_os_chamados():
    """A varredura e a unica espera de rede que sobrou — e ela nao tem total
    conhecido antes, entao vem como fase sem contagem. Os chamados continuam
    contados: e o que o operador usa para saber quanto falta.
    """
    import httpx

    from motor.adapters.estado.fake import FakeEstado
    from motor.domain.types import RepoInfo

    def sem_prs(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"values": [], "next": ""})

    relatos: list[Progresso] = []
    fonte = BitbucketPRCommitSource(
        base_url="http://testserver",
        token="t",
        email="e@x",
        workspace="acme",
        repo="monitor",
        git=FakeGit(),
        client=httpx.Client(transport=httpx.MockTransport(sem_prs)),
        progresso=relatos.append,
        estado=FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)}),
        repo_estado="r",
    )

    fonte.resolve(["1", "2", "3"])

    assert _fases(relatos) == [
        ("varrendo PRs do Bitbucket", 0, 0),
        ("commits dos chamados no Bitbucket", 1, 3),
        ("commits dos chamados no Bitbucket", 2, 3),
        ("commits dos chamados no Bitbucket", 3, 3),
    ]


def _git_verificar() -> FakeGit:
    """Mesmo grafo do test_verificar: m0 e a raiz, a0 so existe no master."""
    git = FakeGit()
    git.add_commit("m0", "", "raiz", D)
    git.add_commit("a0", "m0", "ch123123 alfa", D)
    git.set_branch("master", "a0")
    git.set_branch("origin/master", "a0")
    for versao in ("13.33.1", "13.34.0", "14.0.0"):
        git.set_branch(versao, "m0")
    return git


def test_verificar_relata_suas_fases_na_ordem():
    """A ordem e o contrato: quem desenha a barra confia que 'gravando estado'
    e a ultima coisa, e que as fases contaveis chegam com feito <= total.
    """
    git = _git_verificar()
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})
    estado.registrar_versao(
        "r",
        VersaoInfo(
            numero="14.0.0",
            tipo=VersionType.FECHADA,
            base_ref="master",
            base_commit="m0",
        ),
    )
    relatos: list[Progresso] = []
    deps = Deps(
        git=git,
        tasks=FakeTaskSource(chamados={"13.33.1": ["123123"]}),
        estado=estado,
        repo="r",
        commit_source=FakeCommitSource(
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
        ),
        progresso=relatos.append,
    )

    verificar(deps, "14.0.0")

    assert _fases(relatos) == [
        ("buscando refs do origin", 0, 0),
        ("preparando worktree", 0, 0),
        ("chamados marcados no Tickio", 1, 3),
        ("chamados marcados no Tickio", 2, 3),
        ("chamados marcados no Tickio", 3, 3),
        ("presença dos commits", 1, 1),
        ("simulando conflitos", 1, 1),
        ("gravando estado", 0, 0),
    ]


def test_atualizar_conta_o_lote_de_cherry_pick_e_a_publicacao():
    """O lote e a unica fase em que o motor escreve na branch: se a barra parar
    no meio, o operador precisa saber em qual commit foi.
    """
    git = FakeGit()
    git.add_commit("m0", "", "raiz", D)
    git.add_commit("a0", "m0", "ch255514 corrige logs", D)
    git.add_commit("a1", "a0", "ch255515 outra correcao", D + datetime.timedelta(minutes=1))
    git.set_branch("master", "a1")
    git.set_branch("origin/master", "a1")
    git.set_branch("13.6.0", "m0")
    git.set_branch("13.7.0", "m0")
    relatos: list[Progresso] = []
    deps = Deps(
        git=git,
        tasks=FakeTaskSource(chamados={"13.7.0": ["255514", "255515"]}),
        estado=FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)}),
        repo="r",
        commit_source=FakeCommitSource(
            por_chamado={
                "255514": [
                    CommitRef(hash_origem="a0", parent="m0", chamado="255514",
                              commit_date=D, msg="ch255514 corrige logs")
                ],
                "255515": [
                    CommitRef(hash_origem="a1", parent="a0", chamado="255515",
                              commit_date=D + datetime.timedelta(minutes=1),
                              msg="ch255515 outra correcao")
                ],
            }
        ),
        progresso=relatos.append,
    )

    atualizar(deps, "13.7.0")

    assert _fases(relatos)[0] == ("conferindo se a versão já saiu", 0, 0)
    assert _fases(relatos)[-3:] == [
        ("cherry-pick", 1, 2),
        ("cherry-pick", 2, 2),
        ("publicando na origin", 0, 0),
    ]


def test_consultar_conta_os_chamados_do_snapshot():
    """Cada chamado custa um `git commit_meta` por commit — em versao grande a
    consulta e lenta o bastante para a lista aparecer travada sem isso.
    """
    git = FakeGit()
    git.add_commit("a1", "", "ch9 antigo", D)
    git.add_commit("b1", "", "ch25 novo", D)
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})
    estado.registrar_versao("r", VersaoInfo(numero="13.34.0"))
    estado.substituir_atribuicoes(
        "r",
        "13.34.0",
        [
            Atribuicao(chamado="9", marcada="13.34.0", commits=["a1"]),
            Atribuicao(chamado="25", marcada="13.34.0", commits=["b1"]),
        ],
    )
    relatos: list[Progresso] = []

    consultar(
        Deps(
            git=git,
            tasks=FakeTaskSource(),
            estado=estado,
            repo="r",
            progresso=relatos.append,
        ),
        "13.34.0",
    )

    # Uma fase sem contagem, nao uma por chamado: os commits saem todos de uma
    # varredura git so (ver consultar).
    assert _fases(relatos) == [("lendo commits do snapshot", 0, 0)]


def test_reconstruir_estado_relata_as_tres_bordas():
    """Recuperacao roda com o operador olhando: as tres bordas lentas (fetch,
    base, varredura da branch) tem de aparecer, mesmo sem contagem.
    """
    git = FakeGit(tags={"13.33.0": True})
    git.add_commit("base", "", "raiz", D)
    git.add_commit("p1", "base", "ch123456 alfa", D)
    git.set_branch("13.33.0", "base")
    git.set_branch("13.34.0", "p1")
    relatos: list[Progresso] = []

    reconstruir_estado(
        Deps(
            git=git,
            tasks=FakeTaskSource(),
            estado=FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)}),
            repo="r",
            progresso=relatos.append,
        ),
        "13.34.0",
    )

    assert _fases(relatos) == [
        ("buscando refs do origin", 0, 0),
        ("resolvendo a base da versão", 0, 0),
        ("reconstruindo atribuições a partir do git", 0, 0),
    ]


# --- borda do CLI ----------------------------------------------------------


def test_relator_do_terminal_escreve_a_contagem_em_stderr():
    """stderr, nao stdout: a saida do comando e canalizavel (`motor consulta |
    grep`) e uma barra no meio dela quebraria o pipe de quem consome.
    """
    saida = io.StringIO()

    _escrever_progresso(Progresso("cherry-pick", 3, 7), saida)

    assert saida.getvalue() == "\r\x1b[Kcherry-pick 3/7"


def test_relator_do_terminal_omite_a_contagem_de_fase_indeterminada():
    saida = io.StringIO()

    _escrever_progresso(Progresso("buscando refs do origin"), saida)

    assert saida.getvalue() == "\r\x1b[Kbuscando refs do origin"


def test_progresso_do_cli_fica_silencioso_fora_do_terminal():
    """Redirecionado para arquivo ou pipe, a barra viraria lixo com \\r no log."""

    class _NaoTerminal(io.StringIO):
        def isatty(self) -> bool:
            return False

    assert _relator_do_cli(desligado=False, saida=_NaoTerminal()) is silencioso


def test_sem_progresso_desliga_mesmo_no_terminal():
    class _Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    assert _relator_do_cli(desligado=True, saida=_Terminal()) is silencioso
    assert _relator_do_cli(desligado=False, saida=_Terminal()) is not silencioso


# --- borda da TUI ----------------------------------------------------------


def test_slot_guarda_so_o_ultimo_progresso():
    """A TUI amostra, nao consome: o motor relata mais rapido que 10 Hz e o que
    interessa e sempre o evento mais novo.
    """
    slot = SlotProgresso()

    slot.relatar(Progresso("presença dos commits", 1, 9))
    slot.relatar(Progresso("presença dos commits", 2, 9))

    assert slot.ultimo == Progresso("presença dos commits", 2, 9)


def test_slot_limpa_para_nao_vazar_a_fase_do_comando_anterior():
    slot = SlotProgresso()
    slot.relatar(Progresso("gravando estado"))

    slot.limpar()

    assert slot.ultimo is None


def test_pulso_da_fase_indeterminada_anda_entre_quadros():
    """O pintor redesenha a 10 Hz; se o pulso nao andar com o quadro, a barra
    indeterminada sai congelada — indistinguivel de barra travada.
    """
    fase = Progresso("buscando refs do origin")

    primeiro = _renderizado(renderizar_progresso(fase, quadro=0), estilos=True)
    depois = _renderizado(renderizar_progresso(fase, quadro=7), estilos=True)

    assert primeiro != depois


def test_barra_contavel_mostra_a_contagem_ao_lado():
    texto = _renderizado(renderizar_progresso(Progresso("cherry-pick", 3, 8)))

    assert "cherry-pick" in texto
    assert "3/8" in texto
