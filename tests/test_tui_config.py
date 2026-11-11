import asyncio
import os
from pathlib import Path

from textual.widgets import Input

from motor.config import (
    CHAVE_CAMINHO,
    TABELA_AMBIENTE,
    Chave,
    Tabela,
    VarAmbiente,
    caminho_config_global,
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
from motor.operacoes import RepoOption, Runners
from motor.tui import MotorTUI
from motor.tui_config import (
    ChaveForm,
    ConfigModal,
    Escalar,
    alteracoes_do_formulario,
)

SEGREDO = "s3nha"
SENHA = VarAmbiente.DATABASE_PASSWORD
CHAVE_PRINCIPAL = (None, Tabela.BRANCHES, Chave.PRINCIPAL)
CHAVE_SENHA = (None, TABELA_AMBIENTE, SENHA)
CHAVE_LIVRE = (None, Tabela.TAREFAS, "lista")
NOME_REPO = "app"
TEXTO_COMENTARIO = "# meu comentário"
VALOR_NOVO = "develop"


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
    _escrever(f'[ambiente]\nDATABASE_PASSWORD = "{SEGREDO}"\n')

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
