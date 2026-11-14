import asyncio
import dataclasses
import datetime
import enum
import io
import json
from functools import partial
from pathlib import Path
from threading import Event

import pytest
from rich.console import Console
from textual.widgets import Button, Checkbox, Input, OptionList, Select, Static

import motor.novidades as modulo_novidades
import motor.tui as tui
from motor.domain.types import CommitRef, JulgamentoOrfao, VersionStatus
from motor.engine.atualizar import AtualizarResult, AtualizarStatus
from motor.engine.consultar import ChamadoConsultado
from motor.engine.orfaos import OrfaoDaVersao
from motor.errors import MotorError
from motor.inscricoes import (
    INTERVALO_PADRAO,
    Inscricao,
    carregar,
    inscrever,
    parse_intervalo,
)
from motor.instalacao import PACOTE_MOTOR
from motor.novidades import Cache, Novidade
from motor.operacoes import (
    RepoOption,
    Runners,
    VersionOption,
    runners_com_progresso,
)
from motor.progresso import Progresso, SlotProgresso
from motor.services.versionamento import versionamento_padrao
from motor.tui import (
    MotorTUI,
    OrfaosModal,
    PainelProgresso,
    renderizar_chamado,
    renderizar_status,
)
from tests.versionamento import ESCALONADO_COMPOSTA

_MENSAGEM_ERRO = "falhou"


def _nunca_executa(repo: RepoOption, versao: str, auditar: bool) -> VersionStatus:
    """Runner de verificacao para teste que nao chega a disparar verificacao.

    Levanta em vez de devolver None: se um dia o fluxo passar por aqui, o teste
    falha dizendo isso, em vez de seguir com um status vazio.
    """
    raise AssertionError("este teste nao deveria executar verificacao")


def _texto(renderable) -> str:
    console = Console(file=io.StringIO(), record=True, width=120, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_app_exibe_loading_enquanto_carrega_repos():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    iniciou = Event()
    liberar = Event()

    def carregar_repos() -> list[RepoOption]:
        iniciou.set()
        liberar.wait(timeout=2)
        return [repo]

    async def executar_fluxo() -> None:
        app = MotorTUI(Runners(carregar_repos, lambda opcao: [], _nunca_executa))
        async with app.run_test(size=(120, 36)):
            assert await asyncio.to_thread(iniciou.wait, 1)

            scroll = app.query_one("#resultado-scroll")
            assert scroll.loading

            liberar.set()
            await app.workers.wait_for_complete()
            assert not scroll.loading

    asyncio.run(executar_fluxo())


def test_renderizar_status_mostra_o_culpado_abaixo_dos_faltantes():
    com_culpado = CommitRef(
        hash_origem="f5d02b45aaaa", chamado="255105", msg="Altera os testes"
    )
    sem_culpado = CommitRef(
        hash_origem="c0ffee123456", chamado="255106", msg="Outro conflito"
    )
    status = VersionStatus(
        verde=False,
        estado_integro=True,
        faltantes=[com_culpado, sem_culpado],
        conflitantes=[com_culpado, sem_culpado],
        conflito_causado_por={"f5d02b45aaaa": ["257056"]},
    )

    linhas = _texto(renderizar_status(status)).splitlines()

    tabela = [i for i, linha in enumerate(linhas) if "CONFLITANTE" in linha]
    culpado = [i for i, linha in enumerate(linhas) if "Conflito em" in linha]
    assert [linhas[i].strip() for i in culpado] == [
        "Conflito em f5d02b45 depende de: #257056"
    ]
    assert tabela and culpado[0] > max(tabela)
    assert not any("257056" in linhas[i] for i in tabela)


def test_renderizar_status_agrupa_pendencias_e_exibe_alertas():
    commit = CommitRef(
        hash_origem="deadbeefcafe",
        chamado="255514",
        msg="Ajusta pagamento\ncorpo",
    )
    outro_commit = CommitRef(
        hash_origem="c0ffee123456",
        chamado="255514",
        msg="Ajusta revisão",
    )
    status = VersionStatus(
        verde=False,
        tasks_novas=["255514"],
        tasks_removidas=["200000"],
        estado_integro=False,
        tasks_ambiguas=["300000"],
        commits_sumidos=["badc0ffee000"],
        faltantes=[commit, outro_commit],
        conflitantes=[commit],
        suspeitos_conteudo=[commit],
        tasks_sem_commits=["400000"],
    )

    texto = _texto(renderizar_status(status))

    for esperado in (
        "Pendências encontradas",
        "Escopo",
        "Git",
        "#255514",
        "deadbeef",
        "c0ffee12",
        "CONFLITANTE",
        "SUSPEITO",
        "300000",
        "400000",
        "badc0ffe",
    ):
        assert esperado in texto
    assert texto.count("#255514") == 1
    assert "REQUER ATENÇÃO" not in texto
    assert "Tasks novas" not in texto
    assert "Tasks removidas" not in texto


def test_renderizar_snapshot_liberado_explica_que_esta_congelado():
    status = VersionStatus(
        verde=True,
        estado_integro=True,
        liberada_em=datetime.datetime(2026, 8, 7, 14, 22),
        chamados=["255514", "256308"],
    )

    texto = _texto(renderizar_status(status))

    assert "SNAPSHOT CONGELADO" in texto
    assert "2026-08-07 14:22" in texto
    assert "255514" in texto and "256308" in texto


def test_renderizar_snapshot_liberado_preserva_saude_nao_verde():
    status = VersionStatus(
        verde=False,
        estado_integro=True,
        liberada_em=datetime.datetime(2026, 8, 7, 14, 22),
    )

    texto = _texto(renderizar_status(status))

    assert "Pendências encontradas" in texto
    assert "SNAPSHOT CONGELADO" in texto
    assert "Chamados:" not in texto


def test_renderizar_auditoria_nomeia_recalculo_sem_alterar_snapshot():
    texto = _texto(
        renderizar_status(VersionStatus(verde=True, estado_integro=True), auditado=True)
    )

    assert "AUDITORIA DA TAG" in texto
    assert "snapshot não alterado" in texto


def test_renderizar_atualizacao_agrupa_commits_aplicados_por_chamado():
    aplicados = [
        CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro"),
        CommitRef(hash_origem="c0ffee123456", chamado="255514", msg="Segundo"),
    ]

    texto = _texto(
        tui.renderizar_atualizacao(
            AtualizarResult(status=AtualizarStatus.DONE, aplicados=aplicados)
        )
    )

    assert "Atualização concluída" in texto
    assert texto.count("#255514") == 1
    assert "deadbeef" in texto and "c0ffee12" in texto


def test_renderizar_atualizacao_bloqueada_orienta_continuacao():
    texto = _texto(
        tui.renderizar_atualizacao(
            AtualizarResult(
                status=AtualizarStatus.BLOCKED,
                blocked_commit="deadbeefcafe",
                arquivos_conflito=["motor/tui.py", "tests/test_tui.py"],
            )
        )
    )

    assert "Atualização bloqueada" in texto
    assert "deadbeef" in texto
    assert "motor/tui.py" in texto and "tests/test_tui.py" in texto
    assert "Continuar" in texto and "Abortar" in texto
    assert "Depende de" not in texto


def test_renderizar_atualizacao_bloqueada_mostra_o_culpado():
    texto = _texto(
        tui.renderizar_atualizacao(
            AtualizarResult(
                status=AtualizarStatus.BLOCKED,
                blocked_commit="f5d02b45aaaa",
                arquivos_conflito=["integracoes/tests.py"],
                culpados=["257056"],
            )
        )
    )

    assert "Depende de: #257056" in texto


def test_renderizar_atualizacao_mostra_ja_presentes_e_alertas_da_versao():
    texto = _texto(
        tui.renderizar_atualizacao(
            AtualizarResult(
                status=AtualizarStatus.DONE,
                ja_presentes=3,
                status_versao=VersionStatus(
                    verde=False, estado_integro=True, tasks_sem_commits=["255514"]
                ),
            )
        )
    )

    assert "Branch já estava atualizada" in texto
    assert "3 commits já presentes no histórico" in texto
    assert "Chamados sem commits: 255514" in texto


def test_renderizar_atualizacao_omite_alertas_de_versao_sem_pendencia():
    texto = _texto(
        tui.renderizar_atualizacao(
            AtualizarResult(
                status=AtualizarStatus.DONE,
                status_versao=VersionStatus(verde=True, estado_integro=True),
            )
        )
    )

    assert "Atualização concluída" in texto
    assert "Chamados" not in texto
    assert "já presentes" not in texto


def test_run_tui_liga_os_runners_reais_e_compartilha_o_slot(monkeypatch):
    apps: list[MotorTUI] = []

    def capturar(app: MotorTUI) -> None:
        apps.append(app)

    monkeypatch.setattr(MotorTUI, "run", capturar)

    tui.run_tui()

    [app] = apps
    esperado = runners_com_progresso(app._slot.relatar)
    ligados = [
        (app._carregar_repos, esperado.carregar_repos),
        (app._carregar_versoes, esperado.carregar_versoes),
        (app._executar, esperado.executar),
        (app._atualizar, esperado.atualizar_repo),
        (app._previa, esperado.previa_atualizacao),
        (app._continuar, esperado.continuar_repo),
        (app._abortar, esperado.abortar_repo),
        (app._consultar, esperado.consultar_versao),
        (app._criar, esperado.criar_repo),
        (app._listar_orfaos, esperado.listar_orfaos),
        (app._julgar_orfao, esperado.julgar_orfao),
    ]
    for obtido, previsto in ligados:
        assert isinstance(obtido, partial) and isinstance(previsto, partial)
        assert (obtido.func, obtido.keywords) == (previsto.func, previsto.keywords)


def test_app_seleciona_repo_tag_e_executa_auditoria():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=True)
    chamadas: list[tuple[RepoOption, str, bool]] = []

    def executar(opcao: RepoOption, numero: str, auditar: bool) -> VersionStatus:
        chamadas.append((opcao, numero, auditar))
        return VersionStatus(verde=True, estado_integro=True)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [repo, RepoOption(nome="beta", caminho=None)],
                carregar_versoes=lambda opcao: [versao],
                executar=executar,
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            assert app.query_one("#auditar", Checkbox).display
            assert not app.query_one("#auditar", Checkbox).value
            app.query_one("#auditar", Checkbox).value = True
            assert not app.query_one("#verificar", Button).disabled
            await pilot.click("#verificar")
            await app.workers.wait_for_complete()

            assert chamadas == [(repo, "14.0.0", True)]
            assert "VERDE" in _texto(app.query_one("#resultado", Static).content)

    asyncio.run(executar_fluxo())


def test_app_pula_placeholders_dos_selects():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [repo],
                carregar_versoes=lambda opcao: [versao],
                executar=lambda repo, versao, auditar: VersionStatus(),
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()

            repos = app.query_one("#repo", Select)
            await pilot.click("#repo")
            await pilot.press("home", "enter")
            assert repos.selection == repo

            await app.workers.wait_for_complete()
            versoes = app.query_one("#versao", Select)
            await pilot.click("#versao")
            await pilot.press("home", "enter")
            assert versoes.selection == versao

    asyncio.run(executar_fluxo())


def test_app_consulta_snapshot_ao_selecionar_versao():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    consultas: list[tuple[RepoOption, str]] = []

    def consultar_runner(opcao: RepoOption, numero: str) -> list[ChamadoConsultado]:
        consultas.append((opcao, numero))
        return [
            ChamadoConsultado(
                chamado="255514",
                estado="aplicado",
                commits=[
                    CommitRef(
                        hash_origem="deadbeefcafe",
                        chamado="255514",
                        msg="Título " + "muito longo " * 20 + "\ncorpo oculto",
                    )
                ],
            ),
            ChamadoConsultado(
                chamado="256308",
                estado="pendente",
                commits=[
                    CommitRef(
                        hash_origem="c0ffee123456",
                        chamado="256308",
                        msg="Corrige pedido",
                    )
                ],
            ),
        ]

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [repo],
                carregar_versoes=lambda opcao: [versao],
                executar=lambda repo, versao, auditar: VersionStatus(),
                consultar_versao=consultar_runner,
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            await app.workers.wait_for_complete()

            assert consultas == [(repo, "14.0.0")]
            assert app.query_one("#consulta-painel").display
            assert not app.query_one("#resultado-scroll").display

            lista = app.query_one("#consulta-chamados", OptionList)
            detalhe = app.query_one("#consulta-detalhe", Static)
            assert lista.option_count == 2
            assert lista.highlighted == 0
            texto = _texto(detalhe.content)
            assert "255514" in texto and "APLICADO" in texto
            assert "deadbeef" in texto and "…" in texto
            assert "256308" not in texto and "corpo oculto" not in texto

            lista.highlighted = 1
            await pilot.pause()
            texto = _texto(detalhe.content)
            assert "256308" in texto and "PENDENTE" in texto
            assert "c0ffee12" in texto and "255514" not in texto

    asyncio.run(executar_fluxo())


def test_app_mantem_verificar_e_atualizar_visiveis_e_atualiza_pendencias():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    commits = [
        CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro"),
        CommitRef(hash_origem="c0ffee123456", chamado="255514", msg="Segundo"),
    ]
    atualizacoes: list[tuple[RepoOption, str]] = []

    def atualizar_runner(opcao: RepoOption, numero: str) -> AtualizarResult:
        atualizacoes.append((opcao, numero))
        return AtualizarResult(status=AtualizarStatus.DONE, aplicados=commits)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [repo],
                carregar_versoes=lambda opcao: [versao],
                executar=lambda repo, versao, auditar: VersionStatus(
                    verde=False,
                    estado_integro=True,
                    faltantes=commits,
                ),
                atualizar_repo=atualizar_runner,
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()

            verificar = app.query_one("#verificar", Button)
            atualizar_botao = app.query_one("#atualizar", Button)
            assert not verificar.disabled
            # Versao selecionada e nao liberada ja basta: o Atualizar nao espera
            # um Verificar manual (ele roda o seu antes de aplicar).
            assert not atualizar_botao.disabled

            await pilot.click("#verificar")
            await app.workers.wait_for_complete()

            assert not atualizar_botao.disabled
            assert "2" in _texto(atualizar_botao.label)
            assert atualizar_botao.variant == "warning"

            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert atualizacoes == []

            await pilot.click("#confirmar-sim")
            await app.workers.wait_for_complete()

            assert atualizacoes == [(repo, "14.0.0")]
            assert "Atualização concluída" in _texto(
                app.query_one("#resultado", Static).content
            )
            # Segue habilitado: o lote acabou, mas rodar de novo e legitimo (e
            # cai na previa de "nada faltando" se nao houver nada).
            assert not atualizar_botao.disabled
            assert _texto(atualizar_botao.label).strip() == "Atualizar"

    asyncio.run(executar_fluxo())


_REPO_PREVIA = RepoOption(nome="alpha", caminho="/projetos/alpha")
_VERSAO_PREVIA = VersionOption(numero="14.0.0", liberada=False)


def _app_para_previa(
    status: VersionStatus, atualizar_runner, versao: VersionOption = _VERSAO_PREVIA
) -> MotorTUI:
    """App de um repo e uma versao, com verificacao de resultado fixo."""
    return MotorTUI(
        Runners(
            carregar_repos=lambda: [_REPO_PREVIA],
            carregar_versoes=lambda opcao: [versao],
            executar=lambda repo, numero, auditar: status,
            atualizar_repo=atualizar_runner,
        )
    )


async def _selecionar_previa(
    app, pilot, versao: VersionOption = _VERSAO_PREVIA
) -> None:
    await app.workers.wait_for_complete()
    app.query_one("#repo", Select).value = _REPO_PREVIA
    await pilot.pause()
    await app.workers.wait_for_complete()
    app.query_one("#versao", Select).value = versao
    await pilot.pause()


class _RunnerChamado(enum.Enum):
    PREVIA = enum.auto()
    EXECUTAR = enum.auto()


@pytest.mark.parametrize(
    ("com_previa", "esperado"),
    [(True, _RunnerChamado.PREVIA), (False, _RunnerChamado.EXECUTAR)],
    ids=["com_previa", "sem_previa"],
)
def test_atualizar_usa_o_runner_de_previa(com_previa, esperado):
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")
    status = VersionStatus(verde=True, estado_integro=True, faltantes=[commit])
    chamadas: list[_RunnerChamado] = []

    def executar(repo, numero, auditar) -> VersionStatus:
        chamadas.append(_RunnerChamado.EXECUTAR)
        return status

    def previa(repo, numero) -> VersionStatus:
        chamadas.append(_RunnerChamado.PREVIA)
        return status

    def atualizar_runner(repo, numero) -> AtualizarResult:
        return AtualizarResult(status=AtualizarStatus.DONE, aplicados=[commit])

    async def clicar() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [_REPO_PREVIA],
                carregar_versoes=lambda opcao: [_VERSAO_PREVIA],
                executar=executar,
                atualizar_repo=atualizar_runner,
                previa_atualizacao=previa if com_previa else None,
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot)
            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()
            await pilot.pause()

    asyncio.run(clicar())
    assert chamadas == [esperado]


def test_app_atualizar_sem_verificar_antes_pede_confirmacao_e_aplica():
    """O fluxo que a exigencia de Verificar antes cobrava sem precisar.

    Um clique so: o Atualizar roda a verificacao dele, mostra o lote e aplica
    depois do sim. A previa mostra a mesma tabela do Verificar, entao as secoes
    vermelhas estao na tela no momento da decisao.
    """
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")
    verificacoes = 0
    atualizacoes: list[str] = []

    def executar(repo, numero, auditar) -> VersionStatus:
        nonlocal verificacoes
        verificacoes += 1
        return VersionStatus(
            verde=False,
            estado_integro=True,
            faltantes=[commit],
            tasks_ambiguas=["999999"],
        )

    def atualizar_runner(repo, numero) -> AtualizarResult:
        atualizacoes.append(numero)
        return AtualizarResult(status=AtualizarStatus.DONE, aplicados=[commit])

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [_REPO_PREVIA],
                carregar_versoes=lambda opcao: [_VERSAO_PREVIA],
                executar=executar,
                atualizar_repo=atualizar_runner,
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot)

            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert verificacoes == 1
            assert atualizacoes == []
            previa = _texto(app.screen.query_one("#modal-conteudo", Static).content)
            assert "deadbeef" in previa
            assert "999999" in previa

            await pilot.click("#confirmar-sim")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert atualizacoes == ["14.0.0"]
            assert "Atualização concluída" in _texto(
                app.query_one("#resultado", Static).content
            )

    asyncio.run(executar_fluxo())


def test_app_previa_cancelada_nao_aplica_nada():
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")
    atualizacoes: list[str] = []

    def atualizar_runner(repo, numero) -> AtualizarResult:
        atualizacoes.append(numero)
        return AtualizarResult(status=AtualizarStatus.DONE)

    async def executar_fluxo() -> None:
        app = _app_para_previa(
            VersionStatus(verde=False, estado_integro=True, faltantes=[commit]),
            atualizar_runner,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot)

            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            await app.workers.wait_for_complete()

            assert atualizacoes == []
            # Segue oferecido, agora com a contagem que a previa apurou.
            botao = app.query_one("#atualizar", Button)
            assert not botao.disabled
            assert "1" in _texto(botao.label)

    asyncio.run(executar_fluxo())


def test_app_previa_sem_faltantes_nao_pergunta_nada():
    """Lote vazio nao merece confirmacao: nao ha nada para aplicar.

    Cai no caminho de resultado normal — o mesmo que o Verificar mostraria —
    em vez de perguntar "aplicar 0 commits?".
    """

    def atualizar_runner(repo, numero) -> AtualizarResult:
        raise AssertionError("lote vazio nao pode chamar o atualizar")

    async def executar_fluxo() -> None:
        app = _app_para_previa(
            VersionStatus(verde=True, estado_integro=True), atualizar_runner
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot)

            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert not app.screen.query("#confirmar-sim")
            assert "VERDE" in _texto(app.query_one("#resultado", Static).content)

    asyncio.run(executar_fluxo())


def test_app_previa_com_suspeitos_nao_pergunta_nada():
    """`suspeitos_conteudo` o motor recusa na entrada (RecusaDeInvariante).

    Perguntar aqui levaria um sim direto para uma recusa, gastando a varredura
    do `atualizar` para nada. A tabela com os suspeitos vai para a tela, que e
    onde a decisao (excluir do estado, conferir na mao) e tomada.
    """
    suspeito = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")

    def atualizar_runner(repo, numero) -> AtualizarResult:
        raise AssertionError("lote com suspeitos nao pode chamar o atualizar")

    async def executar_fluxo() -> None:
        app = _app_para_previa(
            VersionStatus(
                verde=False,
                estado_integro=True,
                faltantes=[suspeito],
                suspeitos_conteudo=[suspeito],
            ),
            atualizar_runner,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot)

            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert not app.screen.query("#confirmar-sim")
            assert "deadbeef" in _texto(app.query_one("#resultado", Static).content)

    asyncio.run(executar_fluxo())


def test_app_versao_liberada_nao_oferece_atualizar():
    """Versao com tag nao aceita escrita (docs/decisoes/010-travas-publicada-e-liberada.md):
    o botao nem chega a perguntar."""

    async def executar_fluxo() -> None:
        liberada = VersionOption(numero="14.0.0", liberada=True)
        app = _app_para_previa(
            VersionStatus(verde=True, estado_integro=True),
            lambda repo, numero: AtualizarResult(status=AtualizarStatus.DONE),
            versao=liberada,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot, liberada)

            assert app.query_one("#atualizar", Button).disabled

    asyncio.run(executar_fluxo())


def test_app_resolucao_vazia_vira_registrar_vazio_e_confirma():
    """Pick que nao deixou alteracao: o botao vira "Registrar vazio", e so o
    clique nele manda o `allow_empty`.

    O rotulo distinto e a confirmacao. Com "Continuar" no botao, o operador
    assinaria um commit vazio — que marca o commit como aplicado para sempre no
    oraculo de presenca — achando que so estava retomando o lote.
    """
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")
    continuacoes: list[bool] = []

    def continuar_runner(
        opcao: RepoOption, numero: str, *, allow_empty: bool = False
    ) -> AtualizarResult:
        continuacoes.append(allow_empty)
        if not allow_empty:
            return AtualizarResult(
                status=AtualizarStatus.VAZIO, blocked_commit="deadbeefcafe"
            )
        return AtualizarResult(status=AtualizarStatus.DONE, vazios=[commit])

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [repo],
                carregar_versoes=lambda opcao: [versao],
                executar=lambda repo, versao, auditar: VersionStatus(
                    verde=False, estado_integro=True, faltantes=[commit]
                ),
                atualizar_repo=lambda opcao, numero: AtualizarResult(
                    status=AtualizarStatus.BLOCKED,
                    blocked_commit="deadbeefcafe",
                    arquivos_conflito=["motor/tui.py"],
                ),
                continuar_repo=continuar_runner,
                abortar_repo=lambda opcao, numero: None,
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()

            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.click("#confirmar-sim")
            await app.workers.wait_for_complete()

            # Bloqueado por conflito: o primeiro Continuar vai sem allow_empty.
            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()

            assert continuacoes == [False]
            botao = app.query_one("#atualizar", Button)
            assert _texto(botao.label).strip() == "Registrar vazio"
            assert not botao.disabled
            assert app.query_one("#abortar", Button).display, (
                "descartar o commit e a outra saida: o Abortar tem de estar na tela"
            )
            painel = _texto(app.query_one("#resultado", Static).content)
            assert "Resolução sem alteração" in painel, painel

            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()

            assert continuacoes == [False, True], (
                "o clique em Registrar vazio tem de mandar allow_empty=True; "
                "sem isso o motor devolve VAZIO de novo e o operador fica em loop"
            )
            painel = _texto(app.query_one("#resultado", Static).content)
            assert "commit vazio" in painel, painel
            assert _texto(botao.label).strip() == "Atualizar"

    asyncio.run(executar_fluxo())


def _app_criar(
    criar_runner,
    versoes: list[VersionOption] | None = None,
    versionamento_repo=lambda repo: ESCALONADO_COMPOSTA(),
) -> MotorTUI:
    return MotorTUI(
        Runners(
            carregar_repos=lambda: [_REPO_PREVIA],
            carregar_versoes=lambda opcao: (
                [_VERSAO_PREVIA] if versoes is None else versoes
            ),
            executar=_nunca_executa,
            criar_repo=criar_runner,
            versionamento_repo=versionamento_repo,
        )
    )


def test_criar_modal_previa_mostra_tipo_e_base():
    """Numero certo com base errada e o erro caro do criar: a base entra em
    `versao.base_commit` e fica definitiva. Por isso a previa e viva, enquanto
    digita, e nao um resumo depois do sim.
    """

    async def executar_fluxo() -> None:
        app = _app_criar(
            lambda repo, numero: AtualizarResult(status=AtualizarStatus.DONE)
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot)

            await pilot.press("c")
            await pilot.pause()
            app.screen.query_one("#criar-numero", Input).value = "14.0.1"
            await pilot.pause()

            previa = _texto(app.screen.query_one("#criar-previa", Static).content)
            assert "cliente" in previa
            assert "14.0.0" in previa

    asyncio.run(executar_fluxo())


@pytest.mark.parametrize(
    ("versionamento", "previa_esperada"),
    [
        (versionamento_padrao(), "base main"),
        (ESCALONADO_COMPOSTA(), "ajustada · base 2.2.0"),
    ],
    ids=["semver", "escalonado"],
)
def test_criar_modal_previa_segue_o_esquema_do_repo(versionamento, previa_esperada):
    existente = VersionOption(numero="2.2.0", liberada=False)

    async def executar_fluxo() -> None:
        app = _app_criar(
            lambda repo, numero: AtualizarResult(status=AtualizarStatus.DONE),
            versoes=[existente],
            versionamento_repo=lambda repo: versionamento,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot, existente)

            await pilot.press("c")
            await pilot.pause()
            app.screen.query_one("#criar-numero", Input).value = "2.3.0"
            await pilot.pause()

            previa = _texto(app.screen.query_one("#criar-previa", Static).content)
            assert previa.strip() == previa_esperada

    asyncio.run(executar_fluxo())


def test_criar_modal_sugestao_preenche_o_campo_sem_submeter():
    criacoes: list[str] = []

    def criar_runner(repo: RepoOption, numero: str) -> AtualizarResult:
        criacoes.append(numero)
        return AtualizarResult(status=AtualizarStatus.DONE)

    async def executar_fluxo() -> None:
        app = _app_criar(criar_runner)
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot)

            await pilot.press("c")
            await pilot.pause()
            # A ajustada: 14.0.0 existe, entao 14.1.0 sai da base 14.0.0.
            await pilot.click("#criar-sugestao-1")
            await pilot.pause()

            assert app.screen.query_one("#criar-numero", Input).value == "14.1.0"
            assert "ajustada" in _texto(
                app.screen.query_one("#criar-previa", Static).content
            )
            assert criacoes == []

    asyncio.run(executar_fluxo())


def test_criar_modal_recusa_numero_que_ja_existe():
    """Recusa aqui, nao no motor: o `criar` tambem recusa (por tag ou branch
    remota), mas so depois de um fetch — e branch que existe so local nem chega
    la, morre no `worktree_add`.
    """

    def nao_deve_criar(repo, numero) -> AtualizarResult:
        raise AssertionError("numero existente nao pode chamar o criar")

    async def executar_fluxo() -> None:
        app = _app_criar(nao_deve_criar)
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot)

            await pilot.press("c")
            await pilot.pause()
            app.screen.query_one("#criar-numero", Input).value = "14.0.0"
            await pilot.pause()
            await pilot.click("#criar-ok")
            await pilot.pause()

            assert "ja existe" in _texto(
                app.screen.query_one("#criar-erro", Static).content
            )

    asyncio.run(executar_fluxo())


def test_criar_modal_recusa_formato_invalido():
    async def executar_fluxo() -> None:
        app = _app_criar(
            lambda repo, numero: AtualizarResult(status=AtualizarStatus.DONE)
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot)

            await pilot.press("c")
            await pilot.pause()
            app.screen.query_one("#criar-numero", Input).value = "14.0"
            await pilot.pause()
            await pilot.click("#criar-ok")
            await pilot.pause()

            assert "X.Y.Z" in _texto(
                app.screen.query_one("#criar-erro", Static).content
            )

    asyncio.run(executar_fluxo())


def test_app_criar_seleciona_a_versao_nova_e_consulta_ela():
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")
    criacoes: list[tuple[RepoOption, str]] = []
    consultas: list[str] = []

    def criar_runner(repo: RepoOption, numero: str) -> AtualizarResult:
        criacoes.append((repo, numero))
        return AtualizarResult(status=AtualizarStatus.DONE, aplicados=[commit])

    def consultar_runner(repo: RepoOption, numero: str) -> list[ChamadoConsultado]:
        consultas.append(numero)
        return [
            ChamadoConsultado(chamado="255514", estado="aplicado", commits=[commit])
        ]

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [_REPO_PREVIA],
                carregar_versoes=lambda opcao: [_VERSAO_PREVIA],
                executar=_nunca_executa,
                consultar_versao=consultar_runner,
                criar_repo=criar_runner,
                versionamento_repo=lambda repo: ESCALONADO_COMPOSTA(),
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot)
            await app.workers.wait_for_complete()
            assert consultas == ["14.0.0"]

            await pilot.press("c")
            await pilot.pause()
            await pilot.click("#criar-sugestao-1")
            await pilot.pause()
            await pilot.click("#criar-ok")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert criacoes == [(_REPO_PREVIA, "14.1.0")]
            assert "Atualização concluída" in _texto(
                app.screen.query_one("#modal-conteudo", Static).content
            )

            await pilot.press("escape")
            await pilot.pause()
            await app.workers.wait_for_complete()

            # A versao nova entrou na lista, esta selecionada e e ela que a
            # consulta recarregada leu.
            assert app.query_one("#versao", Select).selection == VersionOption(
                numero="14.1.0", liberada=False
            )
            assert consultas == ["14.0.0", "14.1.0"]

    asyncio.run(executar_fluxo())


def test_app_criar_com_lote_bloqueado_retoma_na_versao_nova():
    """Lote do `criar` que trava tem de deixar Continuar apontando para a versao
    recem-criada — o pick pendente esta na worktree dela, nao na que estava
    selecionada quando o modal abriu.
    """
    continuacoes: list[str] = []

    def criar_runner(repo: RepoOption, numero: str) -> AtualizarResult:
        return AtualizarResult(
            status=AtualizarStatus.BLOCKED,
            blocked_commit="deadbeefcafe",
            arquivos_conflito=["motor/tui.py"],
        )

    def continuar_runner(
        repo: RepoOption, numero: str, /, *, allow_empty: bool = False
    ) -> AtualizarResult:
        continuacoes.append(numero)
        return AtualizarResult(status=AtualizarStatus.DONE)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [_REPO_PREVIA],
                carregar_versoes=lambda opcao: [_VERSAO_PREVIA],
                executar=_nunca_executa,
                atualizar_repo=lambda repo, numero: AtualizarResult(
                    status=AtualizarStatus.DONE
                ),
                continuar_repo=continuar_runner,
                criar_repo=criar_runner,
                versionamento_repo=lambda repo: ESCALONADO_COMPOSTA(),
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot)

            await pilot.press("c")
            await pilot.pause()
            await pilot.click("#criar-sugestao-1")
            await pilot.pause()
            await pilot.click("#criar-ok")
            await app.workers.wait_for_complete()
            await pilot.pause()

            botao = app.query_one("#atualizar", Button)
            assert _texto(botao.label).strip() == "Continuar"

            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()

            assert continuacoes == ["14.1.0"]

    asyncio.run(executar_fluxo())


def test_app_sem_runner_de_criacao_ignora_o_atalho():
    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [_REPO_PREVIA],
                carregar_versoes=lambda opcao: [_VERSAO_PREVIA],
                executar=_nunca_executa,
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot)

            await pilot.press("c")
            await pilot.pause()

            assert not app.screen.query("#criar-numero")

    asyncio.run(executar_fluxo())


def test_app_bloqueio_transforma_atualizar_em_continuar():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")
    continuacoes: list[tuple[RepoOption, str]] = []

    def atualizar_runner(opcao: RepoOption, numero: str) -> AtualizarResult:
        return AtualizarResult(
            status=AtualizarStatus.BLOCKED,
            blocked_commit="deadbeefcafe",
            arquivos_conflito=["motor/tui.py"],
        )

    def continuar_runner(
        opcao: RepoOption, numero: str, *, allow_empty: bool = False
    ) -> AtualizarResult:
        continuacoes.append((opcao, numero))
        return AtualizarResult(status=AtualizarStatus.DONE, aplicados=[commit])

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [repo],
                carregar_versoes=lambda opcao: [versao],
                executar=lambda repo, versao, auditar: VersionStatus(
                    verde=False, estado_integro=True, faltantes=[commit]
                ),
                atualizar_repo=atualizar_runner,
                continuar_repo=continuar_runner,
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()

            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.click("#confirmar-sim")
            await app.workers.wait_for_complete()

            botao = app.query_one("#atualizar", Button)
            assert _texto(botao.label).strip() == "Continuar"
            assert not botao.disabled
            assert continuacoes == []

            # Continuar nao passa pela previa: o lote ja esta aberto na worktree.
            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()

            assert continuacoes == [(repo, "14.0.0")]
            assert "Atualização concluída" in _texto(
                app.query_one("#resultado", Static).content
            )
            assert _texto(botao.label).strip() == "Atualizar"
            assert not botao.disabled

    asyncio.run(executar_fluxo())


def _app_bloqueada(
    repo: RepoOption,
    versao: VersionOption,
    commit: CommitRef,
    abortar_runner,
) -> MotorTUI:
    return MotorTUI(
        Runners(
            carregar_repos=lambda: [repo],
            carregar_versoes=lambda opcao: [versao],
            executar=lambda repo, versao, auditar: VersionStatus(
                verde=False, estado_integro=True, faltantes=[commit]
            ),
            atualizar_repo=lambda opcao, numero: AtualizarResult(
                status=AtualizarStatus.BLOCKED,
                blocked_commit="deadbeefcafe",
                arquivos_conflito=["motor/tui.py"],
            ),
            continuar_repo=lambda opcao, numero, *, allow_empty=False: AtualizarResult(
                status=AtualizarStatus.DONE
            ),
            abortar_repo=abortar_runner,
        )
    )


async def _ate_o_bloqueio(app, pilot, repo, versao) -> None:
    await app.workers.wait_for_complete()
    app.query_one("#repo", Select).value = repo
    await pilot.pause()
    await app.workers.wait_for_complete()
    app.query_one("#versao", Select).value = versao
    await pilot.pause()
    await pilot.click("#verificar")
    await app.workers.wait_for_complete()
    await pilot.click("#atualizar")
    await app.workers.wait_for_complete()
    await pilot.pause()
    await pilot.click("#confirmar-sim")
    await app.workers.wait_for_complete()


def test_app_bloqueio_oferece_abortar_sob_confirmacao():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")
    abortos: list[tuple[RepoOption, str]] = []

    async def executar_fluxo() -> None:
        app = _app_bloqueada(
            repo, versao, commit, lambda opcao, numero: abortos.append((opcao, numero))
        )
        async with app.run_test(size=(120, 36)) as pilot:
            botao = app.query_one("#abortar", Button)
            assert not botao.display

            await _ate_o_bloqueio(app, pilot, repo, versao)
            assert botao.display and not botao.disabled

            await pilot.click("#abortar")
            await pilot.pause()
            assert abortos == []

            await pilot.click("#abortar-sim")
            await pilot.pause()
            await app.workers.wait_for_complete()

            assert abortos == [(repo, "14.0.0")]
            assert "abortada" in _texto(app.query_one("#resultado", Static).content)
            assert not botao.display
            rotulo = _texto(app.query_one("#atualizar", Button).label).strip()
            assert rotulo == "Atualizar"

    asyncio.run(executar_fluxo())


def test_app_abortar_cancelado_nao_toca_no_cherry_pick():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")
    abortos: list[tuple[RepoOption, str]] = []

    async def executar_fluxo() -> None:
        app = _app_bloqueada(
            repo, versao, commit, lambda opcao, numero: abortos.append((opcao, numero))
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _ate_o_bloqueio(app, pilot, repo, versao)

            await pilot.click("#abortar")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

            assert abortos == []
            # segue bloqueada: Continuar continua na mesa
            assert app.query_one("#abortar", Button).display
            rotulo = _texto(app.query_one("#atualizar", Button).label).strip()
            assert rotulo == "Continuar"

    asyncio.run(executar_fluxo())


def test_app_troca_de_versao_esquece_o_bloqueio():
    """Continuar so vale para a versao que travou.

    O cherry-pick pendente esta na worktree daquela versao; se o botao
    sobrevivesse a troca, o clique seguinte mandaria `atualizar_continue` para a
    versao errada.
    """
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao_a = VersionOption(numero="14.0.0", liberada=False)
    versao_b = VersionOption(numero="14.0.1", liberada=False)
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [repo],
                carregar_versoes=lambda opcao: [versao_a, versao_b],
                executar=lambda repo, versao, auditar: VersionStatus(
                    verde=False, estado_integro=True, faltantes=[commit]
                ),
                atualizar_repo=lambda opcao, numero: AtualizarResult(
                    status=AtualizarStatus.BLOCKED,
                    blocked_commit="deadbeefcafe",
                    arquivos_conflito=["motor/tui.py"],
                ),
                continuar_repo=lambda opcao, numero, *, allow_empty=False: (
                    AtualizarResult(status=AtualizarStatus.DONE)
                ),
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao_a
            await pilot.pause()
            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.click("#confirmar-sim")
            await app.workers.wait_for_complete()

            botao = app.query_one("#atualizar", Button)
            assert _texto(botao.label).strip() == "Continuar"

            app.query_one("#versao", Select).value = versao_b
            await pilot.pause()

            assert _texto(botao.label).strip() == "Atualizar"
            # Habilitado de novo, mas para um lote novo da 14.0.1: o clique agora
            # cai na previa, nao no `atualizar_continue` da 14.0.0.
            assert not botao.disabled
            assert not app.query_one("#abortar", Button).display

    asyncio.run(executar_fluxo())


def test_app_atualizar_nao_aplica_quando_a_previa_falha():
    """Verificacao que falha no caminho do Atualizar nao chega a aplicar nada.

    Era o teste da revogacao do botao (`_pode_atualizar` caia quando a
    rechecagem falhava). Nao ha mais flag para revogar: a previa e a propria
    verificacao do clique, e falhar nela mata o clique — o runner de atualizacao
    nunca e chamado, sem depender de estado guardado entre as duas telas.
    """
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514")
    verificacoes = 0
    atualizacoes: list[str] = []

    def verificar_runner(repo, versao, auditar):
        nonlocal verificacoes
        verificacoes += 1
        if verificacoes == 2:
            raise MotorError("rechecagem falhou")
        return VersionStatus(
            verde=False,
            estado_integro=True,
            faltantes=[commit],
        )

    def atualizar_runner(repo, numero) -> AtualizarResult:
        atualizacoes.append(numero)
        return AtualizarResult(status=AtualizarStatus.DONE)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                lambda: [repo],
                lambda opcao: [versao],
                verificar_runner,
                atualizar_runner,
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()

            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            assert not app.query_one("#atualizar", Button).disabled

            await pilot.pause()
            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert verificacoes == 2

            assert atualizacoes == []
            assert "rechecagem falhou" in _texto(
                app.query_one("#resultado", Static).content
            )

    asyncio.run(executar_fluxo())


def test_app_troca_versao_limpa_resultado_anterior():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao_a = VersionOption(numero="14.0.0", liberada=False)
    versao_b = VersionOption(numero="14.0.1", liberada=False)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [repo],
                carregar_versoes=lambda opcao: [versao_a, versao_b],
                executar=lambda repo, versao, auditar: VersionStatus(
                    verde=True, estado_integro=True
                ),
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao_a
            await pilot.pause()
            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            assert "VERDE" in _texto(app.query_one("#resultado", Static).content)

            app.query_one("#versao", Select).value = versao_b
            await pilot.pause()

            texto = _texto(app.query_one("#resultado", Static).content)
            assert "VERDE" not in texto
            assert "14.0.1" in texto

    asyncio.run(executar_fluxo())


def test_app_substitui_carregamento_apos_listar_versoes():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [repo],
                carregar_versoes=lambda opcao: [versao],
                executar=lambda repo, versao, auditar: VersionStatus(
                    verde=True, estado_integro=True
                ),
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()

            texto = _texto(app.query_one("#resultado", Static).content)
            assert texto.strip() == "Selecione uma versão."

    asyncio.run(executar_fluxo())


def test_app_troca_repo_limpa_erro_anterior():
    repo_a = RepoOption(nome="alpha", caminho="/projetos/alpha")
    repo_b = RepoOption(nome="beta", caminho="/projetos/beta")
    versao = VersionOption(numero="14.0.0", liberada=False)
    liberar_b = Event()

    def carregar_versoes(repo: RepoOption) -> list[VersionOption]:
        if repo == repo_b:
            liberar_b.wait(timeout=2)
        return [versao]

    def falhar(repo, numero, auditar):
        raise MotorError("falha anterior")

    async def executar_fluxo() -> None:
        app = MotorTUI(Runners(lambda: [repo_a, repo_b], carregar_versoes, falhar))
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo_a
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            assert "falha anterior" in _texto(
                app.query_one("#resultado", Static).content
            )

            app.query_one("#repo", Select).value = repo_b
            await pilot.pause()

            texto = _texto(app.query_one("#resultado", Static).content)
            assert "falha anterior" not in texto
            assert "Carregando versões de beta" in texto
            liberar_b.set()
            await app.workers.wait_for_complete()

    asyncio.run(executar_fluxo())


def test_app_exibe_motor_error_sem_traceback():
    def falhar():
        raise MotorError("banco inacessível")

    async def executar_fluxo() -> None:
        app = MotorTUI(Runners(falhar, lambda repo: [], _nunca_executa))
        async with app.run_test(size=(120, 36)):
            await app.workers.wait_for_complete()
            assert "banco inacessível" in _texto(
                app.query_one("#resultado", Static).content
            )

    asyncio.run(executar_fluxo())


def test_app_exibe_nota_do_motor_error_junto_com_a_causa():
    """__notes__ so aparece em traceback renderizado, e MotorError nunca
    renderiza traceback aqui — sem concatenar a nota no painel, o contexto
    agregado via add_note (task 7) se perdia por completo para o operador.
    """

    def falhar():
        erro = MotorError("rastreador respondeu 503")
        erro.add_note("buscando tasks da versao 13.34.0")
        raise erro

    async def executar_fluxo() -> None:
        app = MotorTUI(Runners(falhar, lambda repo: [], _nunca_executa))
        async with app.run_test(size=(120, 36)):
            await app.workers.wait_for_complete()
            texto = _texto(app.query_one("#resultado", Static).content)
            assert "buscando tasks da versao 13.34.0" in texto
            assert "rastreador respondeu 503" in texto

    asyncio.run(executar_fluxo())


def test_app_esconde_erro_interno_e_registra_traceback(caplog):
    def falhar():
        raise RuntimeError("bug secreto")

    async def executar_fluxo() -> None:
        app = MotorTUI(Runners(falhar, lambda repo: [], _nunca_executa))
        async with app.run_test(size=(120, 36)):
            await app.workers.wait_for_complete()
            texto = _texto(app.query_one("#resultado", Static).content)
            assert "Erro interno fatal" in texto
            assert "bug secreto" not in texto

    asyncio.run(executar_fluxo())
    assert "Erro interno fatal na TUI" in caplog.text
    assert "Traceback" in caplog.text


def test_app_centra_aviso_e_alinha_resultado_no_canto():
    """Aviso de uma linha centrado; resultado de verdade encostado no canto."""
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [repo],
                carregar_versoes=lambda opcao: [versao],
                executar=lambda repo, versao, auditar: VersionStatus(),
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            resultado = app.query_one("#resultado", Static)
            assert resultado.has_class("aviso")

            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert "Selecione uma versão." in _texto(resultado.content)
            assert resultado.has_class("aviso")

            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            app.query_one("#verificar", Button).press()
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert not resultado.has_class("aviso")

    asyncio.run(executar_fluxo())


def test_app_exibe_loading_enquanto_carrega_versoes():
    """O fetch do origin e a espera mais longa da TUI — sem loading aqui o
    painel ficava com uma linha de texto parada, sem o pulso das outras fases.
    """
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    iniciou = Event()
    liberar = Event()

    def carregar_versoes(opcao):
        iniciou.set()
        liberar.wait(timeout=2)
        return [VersionOption(numero="14.0.0", liberada=False)]

    async def executar_fluxo() -> None:
        def nao_chamado(opcao, numero, auditar):
            raise AssertionError("verificar nao devia rodar neste fluxo")

        app = MotorTUI(Runners(lambda: [repo], carregar_versoes, nao_chamado))
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            assert await asyncio.to_thread(iniciou.wait, 1)

            scroll = app.query_one("#resultado-scroll")
            assert scroll.loading

            liberar.set()
            await app.workers.wait_for_complete()
            assert not scroll.loading

    asyncio.run(executar_fluxo())


def test_app_exibe_loading_apenas_durante_verificacao():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    iniciou = Event()
    liberar = Event()

    def executar(opcao, numero, auditar):
        iniciou.set()
        liberar.wait(timeout=2)
        return VersionStatus(verde=True, estado_integro=True)

    async def executar_fluxo() -> None:
        app = MotorTUI(Runners(lambda: [repo], lambda opcao: [versao], executar))
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            await pilot.click("#verificar")
            assert await asyncio.to_thread(iniciou.wait, 1)

            resultado = app.query_one("#resultado", Static)
            scroll = app.query_one("#resultado-scroll")
            assert scroll.loading
            assert "Verificando alpha 14.0.0" in _texto(resultado.content)

            liberar.set()
            await app.workers.wait_for_complete()
            assert not scroll.loading

    asyncio.run(executar_fluxo())


def test_app_nao_inicia_execucoes_concorrentes():
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    iniciou = Event()
    liberar = Event()
    chamadas: list[str] = []

    def executar(opcao, numero, auditar):
        chamadas.append(numero)
        iniciou.set()
        liberar.wait(timeout=2)
        return VersionStatus(verde=True, estado_integro=True)

    async def executar_fluxo() -> None:
        app = MotorTUI(Runners(lambda: [repo], lambda opcao: [versao], executar))
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            await pilot.click("#verificar")
            assert await asyncio.to_thread(iniciou.wait, 1)
            assert app.query_one("#verificar", Button).disabled
            await pilot.click("#verificar")
            liberar.set()
            await app.workers.wait_for_complete()

    asyncio.run(executar_fluxo())
    assert chamadas == ["14.0.0"]


def test_app_descarta_versoes_obsoletas_sem_liberar_repo_atual():
    repo_a = RepoOption(nome="alpha", caminho="/projetos/alpha")
    repo_b = RepoOption(nome="beta", caminho="/projetos/beta")
    versao_anterior = VersionOption(numero="12.0.0", liberada=False)
    versao_a = VersionOption(numero="13.0.0", liberada=False)
    versao_b = VersionOption(numero="14.0.0", liberada=False)
    iniciou_a = Event()
    liberar_a = Event()
    iniciou_b = Event()
    liberar_b = Event()
    cargas_b = 0

    def carregar_versoes(repo: RepoOption) -> list[VersionOption]:
        nonlocal cargas_b
        if repo == repo_a:
            iniciou_a.set()
            liberar_a.wait(timeout=2)
            return [versao_a]
        cargas_b += 1
        if cargas_b == 1:
            return [versao_anterior]
        iniciou_b.set()
        liberar_b.wait(timeout=2)
        return [versao_b]

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [repo_a, repo_b],
                carregar_versoes=carregar_versoes,
                executar=_nunca_executa,
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo_b
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao_anterior
            await pilot.pause()

            app.query_one("#repo", Select).value = repo_a
            await pilot.pause()
            assert await asyncio.to_thread(iniciou_a.wait, 1)
            app.query_one("#repo", Select).value = repo_b
            await pilot.pause()
            assert await asyncio.to_thread(iniciou_b.wait, 1)

            liberar_a.set()
            await pilot.pause()
            versoes = app.query_one("#versao", Select)
            assert versoes.disabled
            assert app.query_one("#repo", Select).disabled

            liberar_b.set()
            await app.workers.wait_for_complete()
            versoes.value = versao_b
            await pilot.pause()
            assert versoes.selection == versao_b

    asyncio.run(executar_fluxo())


def test_app_mantem_repo_sem_checkout_visivel_mas_inexecutavel():
    repo = RepoOption(nome="beta", caminho=None)

    def nao_deve_rodar(*args):
        raise AssertionError("repo indisponivel nao pode chamar uma borda")

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [repo],
                carregar_versoes=nao_deve_rodar,
                executar=nao_deve_rodar,
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()

            assert app.query_one("#versao", Select).disabled
            assert app.query_one("#verificar", Button).disabled
            assert app.query_one("#atualizar", Button).disabled
            assert "checkout local não encontrado" in _texto(
                app.query_one("#resultado", Static).content
            )

    asyncio.run(executar_fluxo())


def _app_com_consulta(**extra) -> MotorTUI:
    """Base dos testes de modal: repo e versão únicos, lista de chamados visível."""
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = extra.pop("versao", VersionOption(numero="14.0.0", liberada=False))
    return MotorTUI(
        Runners(
            carregar_repos=lambda: [repo],
            carregar_versoes=lambda opcao: [versao],
            **extra,
        )
    )


async def _selecionar(app: MotorTUI, pilot) -> None:
    await app.workers.wait_for_complete()
    repos = app.query_one("#repo", Select)
    repos.value = repos._options[1][1]
    await pilot.pause()
    await app.workers.wait_for_complete()
    versoes = app.query_one("#versao", Select)
    versoes.value = versoes._options[1][1]
    await pilot.pause()
    await app.workers.wait_for_complete()


def test_app_verificar_com_lista_visivel_abre_modal_e_recarrega_chamados():
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")
    consultas = 0

    def consultar_runner(opcao: RepoOption, numero: str) -> list[ChamadoConsultado]:
        nonlocal consultas
        consultas += 1
        return [
            ChamadoConsultado(
                chamado="255514",
                estado="pendente" if consultas == 1 else "aplicado",
                commits=[commit],
            )
        ]

    async def executar_fluxo() -> None:
        app = _app_com_consulta(
            executar=lambda repo, versao, auditar: VersionStatus(
                verde=False, estado_integro=True, faltantes=[commit]
            ),
            consultar_versao=consultar_runner,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar(app, pilot)
            assert consultas == 1

            base = app.screen_stack[0]
            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert isinstance(app.screen, tui.ResultadoModal)
            assert base.query_one("#consulta-painel").display
            assert not base.query_one("#resultado-scroll").display
            assert "FALTANTE" in _texto(
                app.screen.query_one("#modal-conteudo", Static).content
            )

            await pilot.press("escape")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert not isinstance(app.screen, tui.ResultadoModal)
            assert consultas == 2
            assert "APLICADO" in _texto(
                app.query_one("#consulta-detalhe", Static).content
            )

    asyncio.run(executar_fluxo())


def test_app_primeira_verificacao_sem_snapshot_abre_modal_e_carrega_lista():
    """Versão nunca verificada: a consulta inicial vem vazia, então a lista não
    está na tela. O resultado ainda é transitório — o verificar acabou de gravar
    o snapshot — logo vai para o modal e ao fechar traz a lista."""
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")
    consultas = 0

    def consultar_runner(opcao: RepoOption, numero: str) -> list[ChamadoConsultado]:
        nonlocal consultas
        consultas += 1
        if consultas == 1:
            return []
        return [
            ChamadoConsultado(chamado="255514", estado="pendente", commits=[commit])
        ]

    async def executar_fluxo() -> None:
        app = _app_com_consulta(
            executar=lambda repo, versao, auditar: VersionStatus(
                verde=False, estado_integro=True, faltantes=[commit]
            ),
            consultar_versao=consultar_runner,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar(app, pilot)
            assert consultas == 1
            base = app.screen_stack[0]
            assert not base.query_one("#consulta-painel").display

            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert isinstance(app.screen, tui.ResultadoModal)
            assert "FALTANTE" in _texto(
                app.screen.query_one("#modal-conteudo", Static).content
            )

            await pilot.press("escape")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert consultas == 2
            assert app.query_one("#consulta-painel").display
            assert not app.query_one("#resultado-scroll").display

    asyncio.run(executar_fluxo())


def test_app_auditoria_nao_recarrega_lista_de_chamados():
    consultas = 0

    def consultar_runner(opcao: RepoOption, numero: str) -> list[ChamadoConsultado]:
        nonlocal consultas
        consultas += 1
        return [ChamadoConsultado(chamado="255514", estado="aplicado", commits=[])]

    async def executar_fluxo() -> None:
        app = _app_com_consulta(
            versao=VersionOption(numero="14.0.0", liberada=True),
            executar=lambda repo, versao, auditar: VersionStatus(
                verde=True, estado_integro=True
            ),
            consultar_versao=consultar_runner,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar(app, pilot)
            app.query_one("#auditar", Checkbox).value = True
            await pilot.pause()

            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "AUDITORIA DA TAG" in _texto(
                app.screen.query_one("#modal-conteudo", Static).content
            )

            await pilot.press("escape")
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert consultas == 1

    asyncio.run(executar_fluxo())


def test_app_falha_ao_verificar_preserva_lista_de_chamados():
    consultas = 0

    def consultar_runner(opcao: RepoOption, numero: str) -> list[ChamadoConsultado]:
        nonlocal consultas
        consultas += 1
        return [ChamadoConsultado(chamado="255514", estado="pendente", commits=[])]

    def falhar(repo, numero, auditar):
        raise MotorError("verificação falhou")

    async def executar_fluxo() -> None:
        app = _app_com_consulta(executar=falhar, consultar_versao=consultar_runner)
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar(app, pilot)

            base = app.screen_stack[0]
            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert "verificação falhou" in _texto(
                app.screen.query_one("#modal-conteudo", Static).content
            )
            assert base.query_one("#consulta-painel").display

            await pilot.press("escape")
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert consultas == 1

    asyncio.run(executar_fluxo())


def test_app_atualizar_com_lista_visivel_recarrega_chamados():
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")
    consultas = 0

    def consultar_runner(opcao: RepoOption, numero: str) -> list[ChamadoConsultado]:
        nonlocal consultas
        consultas += 1
        return [
            ChamadoConsultado(chamado="255514", estado="pendente", commits=[commit])
        ]

    async def executar_fluxo() -> None:
        app = _app_com_consulta(
            executar=lambda repo, versao, auditar: VersionStatus(
                verde=False, estado_integro=True, faltantes=[commit]
            ),
            atualizar_repo=lambda repo, numero: AtualizarResult(
                status=AtualizarStatus.DONE, aplicados=[commit]
            ),
            consultar_versao=consultar_runner,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar(app, pilot)

            await pilot.click("#verificar")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert consultas == 2

            await pilot.click("#atualizar")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.click("#confirmar-sim")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "Atualização concluída" in _texto(
                app.screen.query_one("#modal-conteudo", Static).content
            )

            await pilot.press("escape")
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert consultas == 3

    asyncio.run(executar_fluxo())


def test_app_exibe_loading_na_lista_durante_verificacao():
    iniciou = Event()
    liberar = Event()

    def executar(opcao, numero, auditar):
        iniciou.set()
        liberar.wait(timeout=2)
        return VersionStatus(verde=True, estado_integro=True)

    async def executar_fluxo() -> None:
        app = _app_com_consulta(
            executar=executar,
            consultar_versao=lambda opcao, numero: [
                ChamadoConsultado(chamado="255514", estado="pendente", commits=[])
            ],
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar(app, pilot)

            painel = app.query_one("#consulta-painel")
            await pilot.click("#verificar")
            assert await asyncio.to_thread(iniciou.wait, 1)
            await pilot.pause()

            assert painel.display
            assert painel.loading

            liberar.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not painel.loading

    asyncio.run(executar_fluxo())


def test_app_desenha_a_fase_e_a_contagem_do_motor_no_lugar_do_spinner():
    """O spinner generico nao diz nada num verificar de 40s. O painel que cobre
    o resultado passa a mostrar a fase do motor e, quando ela e contavel, a
    barra de verdade.
    """
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    slot = SlotProgresso()
    liberar = Event()

    def executar(opcao: RepoOption, numero: str, auditar: bool) -> VersionStatus:
        slot.relatar(Progresso("presença dos commits", 3, 8))
        liberar.wait(5)
        return VersionStatus(verde=True, estado_integro=True)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [repo],
                carregar_versoes=lambda opcao: [versao],
                executar=executar,
            ),
            slot=slot,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            await pilot.click("#verificar")
            for _ in range(50):
                if slot.ultimo is not None:
                    break
                await pilot.pause()
            # chama o pintor direto em vez de esperar o set_interval: prender o
            # teste no relogio de 10 Hz o deixaria intermitente sem provar nada.
            app._pintar_progresso()
            await pilot.pause()

            # O painel de loading e um "cover widget": o Textual o pendura fora
            # da arvore de nos, entao query_one a partir do app nao o acha.
            painel = app._painel_progresso
            assert isinstance(painel, PainelProgresso)
            assert painel.progresso == Progresso("presença dos commits", 3, 8)
            # e chegou na tela, nao so no atributo
            assert "presença dos commits" in _texto(painel.content)
            assert "3/8" in _texto(painel.content)

            liberar.set()
            await app.workers.wait_for_complete()

    asyncio.run(executar_fluxo())


def test_app_volta_para_o_indeterminado_em_fase_sem_contagem():
    """Fase de I/O (fetch, push) nao sabe quanto falta: barra parada em 0% mente,
    barra indeterminada nao.
    """
    repo = RepoOption(nome="alpha", caminho="/projetos/alpha")
    versao = VersionOption(numero="14.0.0", liberada=False)
    slot = SlotProgresso()
    liberar = Event()

    def executar(opcao: RepoOption, numero: str, auditar: bool) -> VersionStatus:
        slot.relatar(Progresso("presença dos commits", 3, 8))
        liberar.wait(5)
        slot.relatar(Progresso("gravando estado"))
        return VersionStatus(verde=True, estado_integro=True)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [repo],
                carregar_versoes=lambda opcao: [versao],
                executar=executar,
            ),
            slot=slot,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#repo", Select).value = repo
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.query_one("#versao", Select).value = versao
            await pilot.pause()
            await pilot.click("#verificar")
            for _ in range(50):
                if slot.ultimo is not None:
                    break
                await pilot.pause()
            app._pintar_progresso()
            await pilot.pause()

            slot.relatar(Progresso("gravando estado"))
            app._pintar_progresso()
            await pilot.pause()

            painel = app._painel_progresso
            assert painel is not None
            assert painel.progresso == Progresso("gravando estado")
            # sem contagem na tela: a barra virou pulso
            assert "3/8" not in _texto(painel.content)

            liberar.set()
            await app.workers.wait_for_complete()

    asyncio.run(executar_fluxo())


def test_renderizar_chamado_separa_sem_commits_de_pendente():
    """Estado gravado nao distingue os dois — a lista de commits sim.

    Sem isso, chamado que o verificar acusou em `sem_commits` reaparece no
    snapshot como "pendente", indistinguivel de quem tem commit esperando
    cherry-pick.
    """
    sem_commits = renderizar_chamado(
        ChamadoConsultado(chamado="254177", estado="pendente", commits=[])
    )
    texto = _texto(sem_commits)
    assert "SEM COMMITS" in texto and "PENDENTE" not in texto

    com_commit = renderizar_chamado(
        ChamadoConsultado(
            chamado="256308",
            estado="pendente",
            commits=[CommitRef(hash_origem="c0ffee123456", chamado="256308")],
        )
    )
    assert "PENDENTE" in _texto(com_commit)


def test_renderizar_chamado_mostra_o_descendente_no_topo():
    """O consultar entrega ancestral primeiro; a tela inverte. A data do autor
    contraria o grafo de proposito — e o que o rebase deixa (ch257911).
    """
    chamado = ChamadoConsultado(
        chamado="256308",
        estado="pendente",
        commits=[
            CommitRef(
                hash_origem="antigo",
                msg="Commit antigo",
                commit_date=datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC),
            ),
            CommitRef(
                hash_origem="novo",
                msg="Commit novo",
                commit_date=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            ),
        ],
    )

    texto = _texto(renderizar_chamado(chamado))

    assert texto.index("Commit novo") < texto.index("Commit antigo")


_ARQUIVO_INSCRICOES = "inscricoes.json"
_ABRE_INSCRICOES = "i"
_ADICIONA_INSCRICAO = "a"
_REMOVE_INSCRICAO = "d"
_LISTA_INSCRICOES = "#inscricoes-lista"


def _inscricao(versao: str, repo: str = "alpha") -> Inscricao:
    return Inscricao(
        repo,
        versao,
        parse_intervalo(INTERVALO_PADRAO),
    )


def test_linha_inscricao_mostra_a_mensagem_do_erro():
    from motor.domain.inscricao import Desfecho, UltimaExecucao

    ultima = UltimaExecucao(
        datetime.datetime.now(datetime.UTC),
        Desfecho.ERRO,
        Desfecho.ERRO,
        frozenset(),
        _MENSAGEM_ERRO,
    )
    i = dataclasses.replace(_inscricao(_VERSAO_PREVIA.numero), ultima=ultima)
    assert tui._linha_inscricao(i).endswith(f"{Desfecho.ERRO.value}: {_MENSAGEM_ERRO}")


async def _abrir_inscricoes(app, pilot, selecionar: bool = True) -> None:
    await app.workers.wait_for_complete()
    if selecionar:
        await _selecionar_previa(app, pilot)
    await pilot.press(_ABRE_INSCRICOES)
    await pilot.pause()


def _app_inscricoes(arquivo: Path) -> MotorTUI:
    return MotorTUI(
        Runners(lambda: [_REPO_PREVIA], lambda opcao: [_VERSAO_PREVIA], _nunca_executa),
        inscricoes_em=arquivo,
    )


def test_inscricoes_lista(tmp_path):
    arquivo = tmp_path / _ARQUIVO_INSCRICOES
    inscrever(arquivo, _inscricao("14.0.0"))

    async def executar_fluxo() -> None:
        app = _app_inscricoes(arquivo)
        async with app.run_test(size=(120, 36)) as pilot:
            await _abrir_inscricoes(app, pilot, selecionar=False)
            lista = app.screen.query_one(_LISTA_INSCRICOES, OptionList)
            assert lista.option_count == 1
            texto = _texto(lista.get_option_at_index(0).prompt)
            assert "14.0.0" in texto
            assert "30m" in texto

    asyncio.run(executar_fluxo())


def test_inscricoes_adiciona_selecionada(tmp_path):
    arquivo = tmp_path / _ARQUIVO_INSCRICOES

    async def executar_fluxo() -> None:
        app = _app_inscricoes(arquivo)
        async with app.run_test(size=(120, 36)) as pilot:
            await _abrir_inscricoes(app, pilot)
            await pilot.press(_ADICIONA_INSCRICAO)
            await pilot.pause()

    asyncio.run(executar_fluxo())
    [gravada] = carregar(arquivo)
    assert (gravada.repo, gravada.versao) == (_REPO_PREVIA.nome, _VERSAO_PREVIA.numero)
    assert gravada.intervalo == parse_intervalo(INTERVALO_PADRAO)
    [crua] = json.loads(arquivo.read_text())
    assert "diretorio" not in crua
    assert "ambiente" not in crua


def test_inscricoes_remove(tmp_path):
    arquivo = tmp_path / _ARQUIVO_INSCRICOES
    inscrever(arquivo, _inscricao("14.0.0"))

    async def executar_fluxo() -> None:
        app = _app_inscricoes(arquivo)
        async with app.run_test(size=(120, 36)) as pilot:
            await _abrir_inscricoes(app, pilot, selecionar=False)
            await pilot.press("down", _REMOVE_INSCRICAO)
            await pilot.pause()

    asyncio.run(executar_fluxo())
    assert carregar(arquivo) == []


def test_inscricoes_sem_versao_avisa(tmp_path, monkeypatch):
    arquivo = tmp_path / _ARQUIVO_INSCRICOES

    async def executar_fluxo() -> None:
        app = _app_inscricoes(arquivo)
        avisos = _gravar_avisos(monkeypatch, app)
        async with app.run_test(size=(120, 36)) as pilot:
            await _abrir_inscricoes(app, pilot, selecionar=False)
            await pilot.press(_ADICIONA_INSCRICAO)
            await pilot.pause()
            assert len(avisos) == 1

    asyncio.run(executar_fluxo())
    assert not arquivo.exists()


def _gravar_avisos(monkeypatch, app: MotorTUI) -> list[str]:
    avisos: list[str] = []
    monkeypatch.setattr(app, "notify", lambda mensagem, **_: avisos.append(mensagem))
    return avisos


def test_inscricoes_arquivo_corrompido_avisa_sem_cair(tmp_path, monkeypatch):
    arquivo = tmp_path / _ARQUIVO_INSCRICOES
    arquivo.write_text("{ isto nao e json", encoding="utf-8")

    async def executar_fluxo() -> None:
        app = _app_inscricoes(arquivo)
        avisos = _gravar_avisos(monkeypatch, app)
        async with app.run_test(size=(120, 36)) as pilot:
            await _abrir_inscricoes(app, pilot, selecionar=False)
            assert len(avisos) == 1
            assert str(arquivo) in avisos[0]

    asyncio.run(executar_fluxo())


# -- lock do repo (decisão 032) ---------------------------------------------

_OCUPADO = "ocupado por outra operação"


def _app_com_lock(chamadas: list[str], bloqueia: bool = False) -> MotorTUI:
    """App em que cada runner só registra a chamada.

    Com `bloqueia`, o atualizar devolve BLOCKED: continuar e abortar ficam na mesa.
    """
    commit = CommitRef(hash_origem="deadbeefcafe", chamado="255514", msg="Primeiro")
    status = VersionStatus(verde=False, estado_integro=True, faltantes=[commit])

    def registra(nome, resultado):
        def runner(*args, **kwargs):
            chamadas.append(nome)
            return resultado

        return runner

    atualizado = (
        AtualizarResult(
            status=AtualizarStatus.BLOCKED,
            blocked_commit="deadbeefcafe",
            arquivos_conflito=["motor/tui.py"],
        )
        if bloqueia
        else AtualizarResult(status=AtualizarStatus.DONE)
    )
    return MotorTUI(
        Runners(
            carregar_repos=lambda: [_REPO_PREVIA],
            carregar_versoes=lambda opcao: [_VERSAO_PREVIA],
            executar=registra("executar", status),
            atualizar_repo=registra("atualizar", atualizado),
            previa_atualizacao=registra("previa", status),
            continuar_repo=registra(
                "continuar", AtualizarResult(status=AtualizarStatus.DONE)
            ),
            abortar_repo=registra("abortar", None),
            criar_repo=registra("criar", AtualizarResult(status=AtualizarStatus.DONE)),
            versionamento_repo=lambda repo: ESCALONADO_COMPOSTA(),
        )
    )


def _travar_previa():
    from motor.trava import travar

    assert _REPO_PREVIA.caminho is not None
    return travar(_REPO_PREVIA.nome, _REPO_PREVIA.caminho)


async def _clicar_e_esperar(app, pilot, *seletores: str) -> None:
    for seletor in seletores:
        await pilot.click(seletor)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()


async def _ate_bloquear(app, pilot) -> None:
    await _selecionar_previa(app, pilot)
    await _clicar_e_esperar(app, pilot, "#atualizar", "#confirmar-sim")


@pytest.mark.parametrize(
    "acao", ["verificar", "previa", "continuar", "abortar", "criar"]
)
def test_app_com_repo_ocupado_mostra_a_recusa_sem_chamar_o_runner(acao):
    chamadas: list[str] = []

    async def executar_fluxo() -> None:
        app = _app_com_lock(chamadas, bloqueia=acao in {"continuar", "abortar"})
        async with app.run_test(size=(120, 36)) as pilot:
            if acao in {"continuar", "abortar"}:
                await _ate_bloquear(app, pilot)
            else:
                await _selecionar_previa(app, pilot)
            antes = list(chamadas)
            with _travar_previa():
                if acao == "verificar":
                    await _clicar_e_esperar(app, pilot, "#verificar")
                elif acao in {"previa", "continuar"}:
                    await _clicar_e_esperar(app, pilot, "#atualizar")
                elif acao == "abortar":
                    await _clicar_e_esperar(app, pilot, "#abortar", "#abortar-sim")
                else:
                    await pilot.press("c")
                    await pilot.pause()
                    await pilot.click("#criar-sugestao-1")
                    await pilot.pause()
                    await _clicar_e_esperar(app, pilot, "#criar-ok")
                tela = _texto(app.query_one("#resultado", Static).content)
            assert _OCUPADO in tela
            assert chamadas == antes

    asyncio.run(executar_fluxo())


def test_app_atualizar_confirmado_com_repo_ocupado_e_recusado():
    """Prévia e atualizar são duas operações: o lock é solto entre elas."""
    chamadas: list[str] = []

    async def executar_fluxo() -> None:
        app = _app_com_lock(chamadas)
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot)
            await _clicar_e_esperar(app, pilot, "#atualizar")
            assert chamadas == ["previa"]
            with _travar_previa():
                await _clicar_e_esperar(app, pilot, "#confirmar-sim")
                tela = _texto(app.query_one("#resultado", Static).content)
            assert _OCUPADO in tela
            assert chamadas == ["previa"]

    asyncio.run(executar_fluxo())


def test_app_auditoria_roda_com_repo_ocupado():
    auditorias: list[bool] = []

    def executar(repo, numero, auditar) -> VersionStatus:
        auditorias.append(auditar)
        return VersionStatus(verde=True, estado_integro=True)

    liberada = VersionOption(numero="14.0.0", liberada=True)

    async def executar_fluxo() -> None:
        app = MotorTUI(
            Runners(
                carregar_repos=lambda: [_REPO_PREVIA],
                carregar_versoes=lambda opcao: [liberada],
                executar=executar,
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            with _travar_previa():
                await _selecionar_previa(app, pilot, liberada)
                app.query_one("#auditar", Checkbox).value = True
                await pilot.pause()
                await _clicar_e_esperar(app, pilot, "#verificar")
                tela = _texto(app.query_one("#resultado", Static).content)
            assert auditorias == [True]
            assert _OCUPADO not in tela

    asyncio.run(executar_fluxo())


_Julgada = tuple[RepoOption, str, str, str | None, str]


def _app_orfaos(
    julgamentos: dict[str, JulgamentoOrfao], chamadas: list[_Julgada]
) -> MotorTUI:
    orfaos = ["aaaa1111", "bbbb2222"]

    def listar(repo: RepoOption, versao: str) -> list[OrfaoDaVersao]:
        return [
            OrfaoDaVersao(
                hash_origem=h,
                assunto=f"assunto {h}",
                data=datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC),
                julgamento=julgamentos.get(h),
            )
            for h in orfaos
        ]

    def julgar(
        repo: RepoOption, versao: str, hash_: str, chamado: str | None, motivo: str
    ) -> JulgamentoOrfao:
        chamadas.append((repo, versao, hash_, chamado, motivo))
        j = JulgamentoOrfao(hash_, versao, chamado, motivo)
        julgamentos[hash_] = j
        return j

    return MotorTUI(
        Runners(
            lambda: [_REPO_PREVIA],
            lambda opcao: [_VERSAO_PREVIA],
            _nunca_executa,
            listar_orfaos=listar,
            julgar_orfao=julgar,
        )
    )


def test_orfaos_sem_repo_e_versao_avisa_e_nao_abre(monkeypatch):
    severidades: list[str] = []

    async def executar_fluxo() -> None:
        app = _app_orfaos({}, [])
        monkeypatch.setattr(
            app,
            "notify",
            lambda mensagem, **kw: severidades.append(kw.get("severity")),
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("o")
            await pilot.pause()
            assert not isinstance(app.screen, OrfaosModal)

    asyncio.run(executar_fluxo())
    assert severidades == ["warning"]


def test_orfaos_abre_com_execucao_da_tui_em_andamento():
    """Listar e julgar rodam ao lado de outra operação (decisão 034)."""

    async def executar_fluxo() -> None:
        app = _app_orfaos({}, [])
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot)
            app._ocupado = True
            await pilot.press("o")
            await pilot.pause()
            assert isinstance(app.screen, OrfaosModal)

    asyncio.run(executar_fluxo())


def test_orfaos_lista_e_julga_nos_dois_sentidos():
    julgamentos: dict[str, JulgamentoOrfao] = {}
    chamadas: list[_Julgada] = []
    numero = _VERSAO_PREVIA.numero

    def textos(app) -> list[str]:
        lista = app.screen.query_one("#orfaos-lista", OptionList)
        return [
            _texto(lista.get_option_at_index(i).prompt)
            for i in range(lista.option_count)
        ]

    async def gravar(app, pilot, indice: int, chamado: str | None, motivo: str):
        modal = app.screen
        modal.query_one("#orfaos-lista", OptionList).highlighted = indice
        if chamado is None:
            modal.query_one("#orfao-nenhum", Checkbox).value = True
        else:
            modal.query_one("#orfao-chamado", Input).value = chamado
        modal.query_one("#orfao-motivo", Input).value = motivo
        await pilot.pause()
        modal.query_one("#orfao-gravar", Button).press()
        await pilot.pause()
        await modal.workers.wait_for_complete()
        await pilot.pause()

    async def executar_fluxo() -> None:
        app = _app_orfaos(julgamentos, chamadas)
        async with app.run_test(size=(120, 36)) as pilot:
            await _selecionar_previa(app, pilot)
            await pilot.press("o")
            await pilot.pause()
            assert isinstance(app.screen, OrfaosModal)
            await app.screen.workers.wait_for_complete()
            await pilot.pause()
            assert all("[pendente]" in t for t in textos(app))

            await gravar(app, pilot, 0, "123", "m1")
            primeiro, segundo = textos(app)
            assert "pertence a 123: m1" in primeiro
            assert "[pendente]" in segundo

            await gravar(app, pilot, 1, None, "m2")
            primeiro, segundo = textos(app)
            assert "pertence a 123: m1" in primeiro
            assert "nenhum: m2" in segundo

    asyncio.run(executar_fluxo())
    assert chamadas == [
        (_REPO_PREVIA, numero, "aaaa1111", "123", "m1"),
        (_REPO_PREVIA, numero, "bbbb2222", None, "m2"),
    ]


def test_app_avisa_versao_nova_ao_abrir(monkeypatch):
    novidade = Novidade(
        PACOTE_MOTOR, "0.2.0", "0.3.0", f"{PACOTE_MOTOR} atualizar-motor"
    )
    agora = datetime.datetime.now(datetime.UTC)
    monkeypatch.setattr(modulo_novidades, "ler_registro", object)
    monkeypatch.setattr(modulo_novidades, "checagem_ligada", lambda: True)
    monkeypatch.setattr(
        modulo_novidades, "ler_cache", lambda _: Cache(agora, (novidade,))
    )
    avisos: list[tuple[str, str]] = []

    async def executar_fluxo() -> None:
        app = MotorTUI(Runners(lambda: [], lambda opcao: [], _nunca_executa))
        monkeypatch.setattr(
            app,
            "notify",
            lambda mensagem, severity, **_: avisos.append((mensagem, severity)),
        )
        async with app.run_test(size=(120, 36)):
            await app.workers.wait_for_complete()

    asyncio.run(executar_fluxo())
    assert (
        "Versão 0.3.0 disponível (você tem 0.2.0): monitor-versoes atualizar-motor",
        "warning",
    ) in avisos
