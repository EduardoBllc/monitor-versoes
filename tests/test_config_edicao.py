from __future__ import annotations

import hashlib
import os
import stat
import sys
from importlib.metadata import EntryPoint

import pytest
from monitor_versoes_bitbucket import Var as VarBitbucket

from motor import plugins
from motor.adapters.sugestao.anthropic import Var as VarAnthropic
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
    MODO_ARQUIVO_NOVO,
    ORIGEM_MOTOR,
    AcaoAlteracao,
    Alteracao,
    Campo,
    Escopo,
    GrupoPlugin,
    TipoCampo,
    catalogo_campos,
    gravar,
    ler_para_edicao,
    rascunho,
)
from motor.errors import ErroDeEntrada, RecusaDeInvariante
from motor.montagem import GRUPO_PRS, GRUPO_TAREFAS

SEGREDO = "s3nha"
NOME_PLUGIN = "falso"
NOME_QUEBRADO = "quebrado"
NOME_OUTRO = "outro"
CHAVE_PROJETO = "projeto"
CHAVE_TOKEN_FALSO = "FAKE_TOKEN"


class FonteFalsa:
    campos_config = (
        Campo(Escopo.GERAL, Tabela.TAREFAS, CHAVE_PROJETO, TipoCampo.TEXTO, "Projeto"),
        Campo(
            Escopo.AMBIENTE,
            TABELA_AMBIENTE,
            CHAVE_TOKEN_FALSO,
            TipoCampo.TEXTO,
            "Token",
            segredo=True,
        ),
    )


class FonteTokenAberto:
    campos_config = (
        Campo(
            Escopo.AMBIENTE,
            TABELA_AMBIENTE,
            CHAVE_TOKEN_FALSO,
            TipoCampo.TEXTO,
            "Token",
        ),
    )


class FonteProjetoInteiro:
    campos_config = (
        Campo(
            Escopo.GERAL, Tabela.TAREFAS, CHAVE_PROJETO, TipoCampo.INTEIRO, "Projeto"
        ),
    )


CHAVE_TOKEN = "MINHA_FONTE_TOKEN"
CHAVE_PIN = "MINHA_FONTE_PIN"


class FonteComSegredo:
    """Declara o `[ambiente]` com `tabela=None`, como o README já ensinou."""

    campos_config = (
        Campo(
            Escopo.AMBIENTE, None, CHAVE_TOKEN, TipoCampo.TEXTO, "Token", segredo=True
        ),
        Campo(
            Escopo.AMBIENTE,
            TABELA_AMBIENTE,
            CHAVE_PIN,
            TipoCampo.INTEIRO,
            "PIN",
            segredo=True,
        ),
    )


def _escrever(texto: str) -> None:
    caminho = caminho_config_global()
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(texto)


def _instalar(monkeypatch, *pontos: EntryPoint) -> None:
    """Os grupos com algum ponto falso veem só os falsos; os demais, os reais."""
    instalados = plugins.pontos_instalados
    falsos = {p.group for p in pontos}

    def pontos_do_grupo(grupo: str) -> tuple[EntryPoint, ...]:
        if grupo in falsos:
            return tuple(p for p in pontos if p.group == grupo)
        return instalados(grupo)

    monkeypatch.setattr(plugins, "pontos_instalados", pontos_do_grupo)


def _ep(nome: str, valor: str, grupo: str = GRUPO_TAREFAS) -> EntryPoint:
    return EntryPoint(name=nome, value=valor, group=grupo)


def test_segredo_nunca_sai_na_leitura():
    _escrever(f'[ambiente]\n{VarBitbucket.TOKEN} = "{SEGREDO}"\n')
    lido = ler_para_edicao()
    [v] = [v for v in lido.valores if v.chave == VarBitbucket.TOKEN]
    assert v.valor is None and v.definido is True
    assert SEGREDO not in repr(lido)


def test_chave_da_anthropic_e_mascarada():
    _escrever(f'[ambiente]\n{VarAnthropic.CHAVE} = "sk-x"\n')

    assert all(v.valor != "sk-x" for v in ler_para_edicao().valores)


def test_segredo_de_plugin_no_ambiente_sai_mascarado(monkeypatch):
    _instalar(monkeypatch, _ep(NOME_PLUGIN, "tests.test_config_edicao:FonteComSegredo"))
    _escrever(f'[ambiente]\n{CHAVE_TOKEN} = "{SEGREDO}"\n')
    lido = ler_para_edicao()
    [v] = [v for v in lido.valores if v.chave == CHAVE_TOKEN]
    assert v.valor is None and v.definido is True
    assert SEGREDO not in repr(lido)


def test_inteiro_secreto_invalido_nao_ecoa_o_valor(monkeypatch):
    _instalar(monkeypatch, _ep(NOME_PLUGIN, "tests.test_config_edicao:FonteComSegredo"))
    with pytest.raises(ErroDeEntrada) as erro:
        gravar(
            [_definir(SEGREDO, CHAVE_PIN, TABELA_AMBIENTE)], ler_para_edicao().versao
        )
    assert SEGREDO not in str(erro.value)


def test_plugin_instalado_declara_campos(monkeypatch):
    _instalar(monkeypatch, _ep(NOME_PLUGIN, "tests.test_config_edicao:FonteFalsa"))
    campos = [c for c in catalogo_campos({}) if c.origem == NOME_PLUGIN]
    assert {c.chave for c in campos} == {CHAVE_PROJETO, CHAVE_TOKEN_FALSO}
    assert all(c.grupo is GrupoPlugin.TAREFAS for c in campos)
    assert all(c.grupo is None for c in catalogo_campos({}) if c.origem == ORIGEM_MOTOR)


def test_plugins_com_a_mesma_chave_mantem_cada_declaracao(monkeypatch):
    fonte = "tests.test_config_edicao:FonteFalsa"
    _instalar(monkeypatch, _ep(NOME_PLUGIN, fonte), _ep(NOME_OUTRO, fonte))
    origens = [c.origem for c in catalogo_campos({}) if c.chave == CHAVE_PROJETO]
    assert sorted(origens) == sorted([NOME_PLUGIN, NOME_OUTRO])


def test_segredo_de_um_plugin_vale_para_a_chave_em_todos(monkeypatch):
    _instalar(
        monkeypatch,
        _ep(NOME_OUTRO, "tests.test_config_edicao:FonteTokenAberto"),
        _ep(NOME_PLUGIN, "tests.test_config_edicao:FonteFalsa"),
    )
    campos = [c for c in catalogo_campos({}) if c.chave == CHAVE_TOKEN_FALSO]
    assert sorted(c.origem for c in campos) == sorted([NOME_PLUGIN, NOME_OUTRO])
    assert all(c.segredo for c in campos)


def test_mesmo_plugin_em_dois_grupos_mantem_a_declaracao_de_cada_grupo(monkeypatch):
    fonte = "tests.test_config_edicao:FonteFalsa"
    _instalar(
        monkeypatch,
        _ep(NOME_PLUGIN, fonte),
        _ep(NOME_PLUGIN, fonte, GRUPO_PRS),
    )
    grupos = [
        c.grupo
        for c in catalogo_campos({})
        if c.chave == CHAVE_TOKEN_FALSO and c.origem == NOME_PLUGIN
    ]
    assert len(grupos) == 2
    assert set(grupos) == {GrupoPlugin.TAREFAS, GrupoPlugin.PRS}


def test_mesmo_plugin_no_mesmo_grupo_nao_repete(monkeypatch):
    fonte = "tests.test_config_edicao:FonteFalsa"
    _instalar(monkeypatch, _ep(NOME_PLUGIN, fonte), _ep(NOME_PLUGIN, fonte))
    campos = [c for c in catalogo_campos({}) if c.chave == CHAVE_TOKEN_FALSO]
    assert [c.origem for c in campos] == [NOME_PLUGIN]


def test_host_de_pr_do_pacote_declara_campos_do_grupo_prs():
    campos = [c for c in catalogo_campos({}) if c.origem == "bitbucket"]
    assert campos
    assert all(c.grupo is GrupoPlugin.PRS for c in campos)


class EntryPointQuebrado(EntryPoint):
    def load(self):
        raise RuntimeError("quebrou")


@pytest.mark.parametrize(
    "ponto",
    [
        _ep(NOME_QUEBRADO, "modulo_que_nao_existe:X"),
        EntryPointQuebrado(NOME_QUEBRADO, "x:Y", GRUPO_TAREFAS),
    ],
)
def test_plugin_quebrado_fica_fora_do_catalogo(monkeypatch, ponto):
    _instalar(monkeypatch, ponto)
    lido = ler_para_edicao()
    assert all(c.origem != NOME_QUEBRADO for c in lido.campos)


def test_campos_config_malformado_fica_fora(monkeypatch):
    class Torto:
        campos_config = ("nao e Campo",)

    monkeypatch.setattr(plugins, "carregar_plugin", lambda g, n: Torto)
    _instalar(monkeypatch, _ep(NOME_QUEBRADO, "x:Y"))
    assert all(c.origem != NOME_QUEBRADO for c in catalogo_campos({}))


def test_chave_sem_declaracao_vira_livre():
    _escrever('[tarefas]\noutra = "x"\n')
    lido = ler_para_edicao()
    [v] = [v for v in lido.valores if v.chave == "outra"]
    assert v.editavel is True and v.valor == "x"
    assert all(c.chave != "outra" for c in lido.campos)


def test_subtabela_e_so_leitura_e_secao_de_repo_lista_caminho():
    _escrever(
        '[tarefas.algo]\nx = 1\n[repos.app]\ncaminho = "/a"\n[repos.app.versao]\npiso = "1.0"\n'
    )
    lido = ler_para_edicao()
    sub = next(v for v in lido.valores if v.chave == "algo")
    assert sub.editavel is False and sub.valor is None
    caminho = next(v for v in lido.valores if v.chave == CHAVE_CAMINHO)
    assert (caminho.repo, caminho.tabela, caminho.valor) == ("app", None, "/a")
    assert lido.repos == ["app"]


def test_modulo_classe_em_uso_vira_opcao_do_campo():
    _escrever('[tarefas]\nfonte = "tests.test_config_edicao:FonteFalsa"\n')
    campo = next(c for c in ler_para_edicao().campos if c.chave == Chave.FONTE)
    assert "tests.test_config_edicao:FonteFalsa" in campo.opcoes
    daquele = [
        c
        for c in ler_para_edicao().campos
        if c.origem == "tests.test_config_edicao:FonteFalsa"
    ]
    assert daquele
    assert all(c.grupo is GrupoPlugin.TAREFAS for c in daquele)


def test_versao_e_hash_do_arquivo():
    assert ler_para_edicao().versao == hashlib.sha256(b"").hexdigest()
    _escrever('[tarefas]\na = "1"\n')
    antes = ler_para_edicao().versao
    _escrever('[tarefas]\na = "2"\n')
    assert ler_para_edicao().versao != antes


@pytest.mark.parametrize("chave", [Chave.ESQUEMA, Chave.ATRIBUICAO])
def test_opcoes_incluem_os_instalados(chave):
    campo = next(c for c in ler_para_edicao().campos if c.chave == chave)
    assert campo.opcoes


MODO_GRUPO = 0o640
EMAIL_BASE = "base@exemplo.com"
EMAIL_CENTRAL = "central@exemplo.com"
CHAVE_LISTA = "filtros"


@pytest.fixture(autouse=True)
def _ambiente_base(monkeypatch):
    """Gravar reaplica o `[ambiente]` no processo; o monkeypatch o desfaz no fim."""
    monkeypatch.setenv(VarBitbucket.EMAIL, EMAIL_BASE)


def _bytes() -> bytes:
    with open(caminho_config_global(), "rb") as f:
        return f.read()


def _definir(valor, chave, tabela=None, repo=None) -> Alteracao:
    return Alteracao(AcaoAlteracao.DEFINIR, repo, tabela, chave, valor)


def test_gravar_preserva_comentarios_e_ordem(tmp_path):
    _escrever(
        "# topo\n"
        '[branches]\nversao = "v/{versao}"\n'
        f"[repos.a]\n# do repo\ncaminho = '{tmp_path}'\n"
    )
    gravar(
        [_definir("1.2.0", Chave.PISO, Tabela.VERSAO, "a")], ler_para_edicao().versao
    )
    texto = _bytes().decode()
    assert "# topo" in texto and "# do repo" in texto
    assert texto.index("[branches]") < texto.index("[repos.a]")
    assert 'piso = "1.2.0"' in texto


def test_criar_e_remover_repo(tmp_path):
    criado = gravar(
        [
            Alteracao(AcaoAlteracao.CRIAR_REPO, "b"),
            _definir(str(tmp_path), CHAVE_CAMINHO, repo="b"),
        ],
        ler_para_edicao().versao,
    )
    assert "b" in repos_configurados()
    gravar([Alteracao(AcaoAlteracao.REMOVER_REPO, "b")], criado.versao)
    assert "b" not in repos_configurados()


def test_repo_com_ponto_no_nome(tmp_path):
    nome = "app.web"
    gravar(
        [
            Alteracao(AcaoAlteracao.CRIAR_REPO, nome),
            _definir(str(tmp_path), CHAVE_CAMINHO, repo=nome),
        ],
        ler_para_edicao().versao,
    )
    assert '[repos."app.web"]' in _bytes().decode()
    assert nome in repos_configurados()


@pytest.mark.parametrize(
    "alteracao",
    [
        _definir("abc", Chave.PISO, Tabela.VERSAO, "a"),
        _definir("cinco", VarAmbiente.WORKTREES_MANTIDAS, TABELA_AMBIENTE),
        _definir("²", VarAmbiente.WORKTREES_MANTIDAS, TABELA_AMBIENTE),
        _definir("release", Chave.VERSAO, Tabela.BRANCHES),
    ],
)
def test_valor_invalido_nao_muda_o_arquivo(tmp_path, alteracao):
    _escrever(f"[repos.a]\ncaminho = '{tmp_path}'\n")
    antes = _bytes()
    with pytest.raises(ErroDeEntrada):
        gravar([alteracao], ler_para_edicao().versao)
    assert _bytes() == antes


PROJETO_TEXTO = "grupo/projeto"
NOME_REPO = "a"


def _projeto_texto_e_inteiro(monkeypatch) -> None:
    _instalar(
        monkeypatch,
        _ep(NOME_OUTRO, "tests.test_config_edicao:FonteProjetoInteiro"),
        _ep(NOME_PLUGIN, "tests.test_config_edicao:FonteFalsa"),
    )


@pytest.mark.parametrize(
    ("fonte_topo", "fonte_repo"), [(NOME_PLUGIN, None), (NOME_OUTRO, NOME_PLUGIN)]
)
def test_campo_de_plugin_valida_pela_declaracao_do_escolhido(
    monkeypatch, tmp_path, fonte_topo, fonte_repo
):
    _projeto_texto_e_inteiro(monkeypatch)
    texto = f'[tarefas]\n{Chave.FONTE} = "{fonte_topo}"\n'
    repo = None if fonte_repo is None else NOME_REPO
    if repo is not None:
        texto += (
            f"[repos.{repo}]\n{CHAVE_CAMINHO} = '{tmp_path}'\n"
            f'[repos.{repo}.tarefas]\n{Chave.FONTE} = "{fonte_repo}"\n'
        )
    _escrever(texto)
    gravar(
        [_definir(PROJETO_TEXTO, CHAVE_PROJETO, Tabela.TAREFAS, repo)],
        ler_para_edicao().versao,
    )
    assert PROJETO_TEXTO in _bytes().decode()


def test_campo_de_plugin_recusa_valor_invalido_para_o_escolhido(monkeypatch):
    _projeto_texto_e_inteiro(monkeypatch)
    _escrever(f'[tarefas]\n{Chave.FONTE} = "{NOME_OUTRO}"\n')
    with pytest.raises(ErroDeEntrada):
        gravar(
            [_definir(PROJETO_TEXTO, CHAVE_PROJETO, Tabela.TAREFAS)],
            ler_para_edicao().versao,
        )


def test_versao_velha_recusada():
    _escrever('[tarefas]\na = "1"\n')
    versao = ler_para_edicao().versao
    _escrever('[tarefas]\na = "2"\n')
    with pytest.raises(RecusaDeInvariante, match="recarregue"):
        gravar([_definir("3", "a", Tabela.TAREFAS)], versao)


@pytest.mark.skipif(sys.platform == "win32", reason="o Windows não tem modo POSIX")
def test_gravar_cria_arquivo_e_diretorio():
    gravar(
        [_definir(EMAIL_CENTRAL, VarBitbucket.EMAIL, TABELA_AMBIENTE)],
        hashlib.sha256(b"").hexdigest(),
    )
    assert stat.S_IMODE(os.stat(caminho_config_global()).st_mode) == MODO_ARQUIVO_NOVO


@pytest.mark.skipif(sys.platform == "win32", reason="o Windows não tem modo POSIX")
def test_gravar_mantem_permissao():
    _escrever('[tarefas]\na = "1"\n')
    os.chmod(caminho_config_global(), MODO_GRUPO)
    gravar([_definir("2", "a", Tabela.TAREFAS)], ler_para_edicao().versao)
    assert stat.S_IMODE(os.stat(caminho_config_global()).st_mode) == MODO_GRUPO


def test_chave_nao_editavel_sobrevive():
    lista = f'{CHAVE_LISTA} = ["a", "b"]'
    _escrever(f'[tarefas]\n{lista}\na = "1"\n')
    versao = gravar([_definir("2", "a", Tabela.TAREFAS)], ler_para_edicao().versao)
    assert lista in _bytes().decode()
    with pytest.raises(ErroDeEntrada):
        gravar([_definir("x", CHAVE_LISTA, Tabela.TAREFAS)], versao.versao)


def test_gravar_reaplica_ambiente():
    definida = gravar(
        [_definir(EMAIL_CENTRAL, VarBitbucket.EMAIL, TABELA_AMBIENTE)],
        ler_para_edicao().versao,
    )
    assert os.environ[VarBitbucket.EMAIL] == EMAIL_CENTRAL
    gravar(
        [
            Alteracao(
                AcaoAlteracao.REMOVER,
                tabela=TABELA_AMBIENTE,
                chave=VarBitbucket.EMAIL,
            )
        ],
        definida.versao,
    )
    assert os.environ[VarBitbucket.EMAIL] == EMAIL_BASE


def test_gravar_segue_symlink(tmp_path):
    alvo = tmp_path / "dotfiles" / "config.toml"
    alvo.parent.mkdir()
    alvo.write_text('[tarefas]\na = "1"\n')
    link = caminho_config_global()
    os.makedirs(os.path.dirname(link), exist_ok=True)
    os.symlink(alvo, link)
    gravar([_definir("2", "a", Tabela.TAREFAS)], ler_para_edicao().versao)
    assert os.path.islink(link)
    assert 'a = "2"' in alvo.read_text()


def test_remover_ausente_e_noop_e_tabela_vazia_some(tmp_path):
    _escrever(
        f"[repos.a]\ncaminho = '{tmp_path}'\n[repos.a.versao]\npiso = \"1.0.0\"\n"
    )
    antes = _bytes()
    remover_ausente = Alteracao(AcaoAlteracao.REMOVER, "a", Tabela.TAREFAS, "x")
    gravar([remover_ausente], ler_para_edicao().versao)
    assert _bytes() == antes
    gravar(
        [Alteracao(AcaoAlteracao.REMOVER, "a", Tabela.VERSAO, Chave.PISO)],
        ler_para_edicao().versao,
    )
    texto = _bytes().decode()
    assert "[repos.a.versao]" not in texto and "[repos.a]" in texto


@pytest.mark.parametrize(
    "alteracao",
    [
        Alteracao(AcaoAlteracao.CRIAR_REPO, "a"),
        Alteracao(AcaoAlteracao.CRIAR_REPO, "pasta/b"),
        Alteracao(AcaoAlteracao.REMOVER_REPO, "ausente"),
    ],
)
def test_operacao_de_repo_invalida(tmp_path, alteracao):
    _escrever(f"[repos.a]\ncaminho = '{tmp_path}'\n")
    with pytest.raises(ErroDeEntrada):
        gravar([alteracao], ler_para_edicao().versao)


def test_rascunho_nao_grava():
    _escrever('[tarefas]\na = "1"\n')
    antes = _bytes()
    texto = rascunho([_definir("2", "a", Tabela.TAREFAS)], ler_para_edicao().versao)
    assert 'a = "2"' in texto
    assert _bytes() == antes


def test_rascunho_invalido_e_versao_velha(tmp_path):
    _escrever(f"[repos.a]\ncaminho = '{tmp_path}'\n")
    versao = ler_para_edicao().versao
    with pytest.raises(ErroDeEntrada):
        rascunho([_definir("abc", Chave.PISO, Tabela.VERSAO, "a")], versao)
    _escrever('[tarefas]\na = "2"\n')
    with pytest.raises(RecusaDeInvariante, match="recarregue"):
        rascunho([_definir("3", "a", Tabela.TAREFAS)], versao)
