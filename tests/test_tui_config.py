import asyncio
import os
from pathlib import Path

import pytest
from textual.widgets import Input, OptionList, Select, TabbedContent

from motor.config import (
    CHAVE_CAMINHO,
    TABELA_AMBIENTE,
    Chave,
    Tabela,
    VarAmbiente,
    caminho_config_global,
    repos_configurados,
)
from motor.config_edicao import (
    AcaoAlteracao,
    Alteracao,
    Campo,
    ConfigEditavel,
    Escopo,
    TipoCampo,
    ValorLido,
)
from motor.domain.types import VersionStatus
from motor.errors import ErroDeEntrada
from motor.operacoes import RepoOption, Runners
from motor.tui import MotorTUI
from motor.tui_config import (
    ABA_REPOS,
    ChaveForm,
    ConfigModal,
    Escalar,
    alteracoes_do_formulario,
    converter_texto,
)

SEGREDO = "s3nha"
SENHA = VarAmbiente.BITBUCKET_TOKEN
CHAVE_PRINCIPAL = (None, Tabela.BRANCHES, Chave.PRINCIPAL)
CHAVE_SENHA = (None, TABELA_AMBIENTE, SENHA)
CHAVE_LIVRE = (None, Tabela.TAREFAS, "lista")
NOME_REPO = "app"
TEXTO_COMENTARIO = "# meu comentário"
VALOR_NOVO = "develop"
VALOR_TOPO = "main"
WORKTREES = VarAmbiente.WORKTREES_MANTIDAS
PORTA_TEXTO = "5433"
CHAVE_TOKEN = "token"


def _escrever(texto: str) -> None:
    caminho = caminho_config_global()
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w") as f:
        f.write(texto)


def _nunca_executa(repo: RepoOption, versao: str, auditar: bool) -> VersionStatus:
    raise AssertionError("este teste nao deveria executar verificacao")


def _app() -> MotorTUI:
    return MotorTUI(Runners(lambda: [], lambda opcao: [], _nunca_executa))


def _config(
    campos: list[Campo], valores: list[ValorLido], repos: list[str] | None = None
) -> ConfigEditavel:
    return ConfigEditavel(campos, valores, repos or [], "v1")


CAMPO_PRINCIPAL = Campo(
    Escopo.GERAL, Tabela.BRANCHES, Chave.PRINCIPAL, TipoCampo.TEXTO, "Principal"
)
CAMPO_SENHA = Campo(
    Escopo.AMBIENTE, TABELA_AMBIENTE, SENHA, TipoCampo.TEXTO, "Senha", segredo=True
)
CAMPO_CAMINHO = Campo(Escopo.REPO, None, CHAVE_CAMINHO, TipoCampo.TEXTO, "Caminho")


def test_segredo_nao_tocado_nao_gera_alteracao():
    original = _config(
        [CAMPO_SENHA], [ValorLido(None, TABELA_AMBIENTE, SENHA, None, True, True)]
    )
    assert alteracoes_do_formulario(original, {CHAVE_SENHA: ""}, [], []) == []


def test_segredo_apagado_so_gera_remover_se_estava_definido():
    definido = _config(
        [CAMPO_SENHA], [ValorLido(None, TABELA_AMBIENTE, SENHA, None, True, True)]
    )
    remover = Alteracao(AcaoAlteracao.REMOVER, None, TABELA_AMBIENTE, SENHA)
    assert alteracoes_do_formulario(definido, {CHAVE_SENHA: None}, [], []) == [remover]
    assert (
        alteracoes_do_formulario(
            _config([CAMPO_SENHA], []), {CHAVE_SENHA: None}, [], []
        )
        == []
    )


def test_segredo_novo_gera_definir():
    original = _config([CAMPO_SENHA], [])
    assert alteracoes_do_formulario(original, {CHAVE_SENHA: SEGREDO}, [], []) == [
        Alteracao(AcaoAlteracao.DEFINIR, None, TABELA_AMBIENTE, SENHA, SEGREDO)
    ]


def test_chave_nao_editavel_nunca_gera_alteracao():
    original = _config(
        [], [ValorLido(None, Tabela.TAREFAS, "lista", None, True, False)]
    )
    assert alteracoes_do_formulario(original, {CHAVE_LIVRE: ""}, [], []) == []


def test_valor_igual_nao_gera_e_esvaziar_remove():
    lido = ValorLido(None, Tabela.BRANCHES, Chave.PRINCIPAL, "main", True, True)
    original = _config([CAMPO_PRINCIPAL], [lido])
    assert alteracoes_do_formulario(original, {CHAVE_PRINCIPAL: "main"}, [], []) == []
    assert alteracoes_do_formulario(original, {CHAVE_PRINCIPAL: ""}, [], []) == [
        Alteracao(AcaoAlteracao.REMOVER, None, Tabela.BRANCHES, Chave.PRINCIPAL)
    ]


def test_repo_criado_vem_antes_dos_definir_e_removido_manda_so_remover_repo():
    original = _config(
        [CAMPO_CAMINHO],
        [ValorLido("velho", None, CHAVE_CAMINHO, "/x", True, True)],
        ["velho"],
    )
    valores: dict[ChaveForm, Escalar] = {
        ("novo", None, CHAVE_CAMINHO): "/y",
        ("velho", None, CHAVE_CAMINHO): "",
    }
    assert alteracoes_do_formulario(original, valores, ["novo"], ["velho"]) == [
        Alteracao(AcaoAlteracao.CRIAR_REPO, "novo"),
        Alteracao(AcaoAlteracao.DEFINIR, "novo", None, CHAVE_CAMINHO, "/y"),
        Alteracao(AcaoAlteracao.REMOVER_REPO, "velho"),
    ]


def test_tui_config_salva_e_preserva_comentario():
    _escrever(f'{TEXTO_COMENTARIO}\n[branches]\nprincipal = "main"\n')

    async def fluxo() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("g")
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, ConfigModal)
            modal.query_one(
                f"#{modal.id_de(CHAVE_PRINCIPAL)}", Input
            ).value = VALOR_NOVO
            await pilot.click("#salvar")
            await pilot.pause()
            assert not isinstance(app.screen, ConfigModal), [
                n.message for n in app._notifications
            ]

    asyncio.run(fluxo())
    texto = Path(caminho_config_global()).read_text()
    assert VALOR_NOVO in texto
    assert TEXTO_COMENTARIO in texto


def test_tui_config_recusa_com_execucao():
    async def fluxo() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            app._ocupado = True
            await pilot.press("g")
            await pilot.pause()
            assert not isinstance(app.screen, ConfigModal)
            assert app._notifications

    asyncio.run(fluxo())


def test_tui_config_segredo_nao_aparece():
    _escrever(f'[ambiente]\nBITBUCKET_TOKEN = "{SEGREDO}"\n')

    async def fluxo() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("g")
            await pilot.pause()
            assert isinstance(app.screen, ConfigModal)
            entradas = list(app.screen.query(Input))
            assert entradas
            assert all(SEGREDO not in e.value for e in entradas)
            assert all(SEGREDO not in (e.placeholder or "") for e in entradas)

    asyncio.run(fluxo())


def test_converter_texto_preserva_tipo_toml():
    lido_bool = ValorLido(None, Tabela.TAREFAS, "b", True, True, True)
    lido_int = ValorLido(None, Tabela.TAREFAS, "n", 3, True, True)
    assert converter_texto("FALSE", lido_bool, False) is False
    assert converter_texto("7", lido_int, False) == 7
    assert converter_texto("", lido_int, False) == ""
    assert converter_texto("None", None, False) == "None"
    with pytest.raises(ErroDeEntrada):
        converter_texto("talvez", lido_bool, False)
    with pytest.raises(ErroDeEntrada):
        converter_texto("x", lido_int, False)


def test_tui_config_cria_repo_e_atualiza_lista(tmp_path):
    _escrever('[branches]\nprincipal = "main"\n')
    novo = tmp_path / "novo"
    novo.mkdir()

    def repos() -> list[RepoOption]:
        return [RepoOption(n, c) for n, c in repos_configurados().items()]

    async def fluxo() -> None:
        app = MotorTUI(Runners(repos, lambda opcao: [], _nunca_executa))
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("g")
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, ConfigModal)
            modal.query_one(TabbedContent).active = ABA_REPOS
            await pilot.pause()
            modal.query_one("#novo-repo", Input).value = NOME_REPO
            await pilot.click("#criar-repo")
            await pilot.pause()
            caminho = (NOME_REPO, None, CHAVE_CAMINHO)
            modal.query_one(f"#{modal.id_de(caminho)}", Input).value = str(novo)
            await pilot.click("#salvar")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert [o.nome for o in repos()] == [NOME_REPO]
            assert (
                app.query_one("#repo", Select).query_one(OptionList).option_count == 2
            )

    asyncio.run(fluxo())


def test_tui_config_repo_mostra_valor_do_topo_como_placeholder():
    _escrever(f'[branches]\nprincipal = "{VALOR_TOPO}"\n[repos.app]\ncaminho = "/x"\n')

    async def fluxo() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("g")
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, ConfigModal)
            principal = modal.query_one(
                f"#{modal.id_de((NOME_REPO, Tabela.BRANCHES, Chave.PRINCIPAL))}", Input
            )
            assert principal.placeholder == VALOR_TOPO
            assert principal.value == ""

    asyncio.run(fluxo())


def test_inteiro_gravado_como_texto_nao_tocado_nao_gera_alteracao():
    campo = Campo(
        Escopo.AMBIENTE, TABELA_AMBIENTE, WORKTREES, TipoCampo.INTEIRO, "Worktrees"
    )
    lido = ValorLido(None, TABELA_AMBIENTE, WORKTREES, PORTA_TEXTO, True, True)
    chave = (None, TABELA_AMBIENTE, WORKTREES)
    novo = converter_texto(PORTA_TEXTO, lido, True)
    assert (
        alteracoes_do_formulario(_config([campo], [lido]), {chave: novo}, [], []) == []
    )


def test_segredo_geral_no_repo_nao_tocado_nao_gera_alteracao():
    campo = Campo(
        Escopo.GERAL,
        Tabela.TAREFAS,
        CHAVE_TOKEN,
        TipoCampo.TEXTO,
        "Token",
        segredo=True,
    )
    lido = ValorLido(NOME_REPO, Tabela.TAREFAS, CHAVE_TOKEN, None, True, True)
    original = _config([campo], [lido], [NOME_REPO])
    chave = (NOME_REPO, Tabela.TAREFAS, CHAVE_TOKEN)
    assert alteracoes_do_formulario(original, {chave: ""}, [], []) == []
