from __future__ import annotations

import hashlib
import os
import stat
from importlib.metadata import EntryPoint, entry_points

import pytest

from motor import plugins
from motor.adapters.commitsource.bitbucket import Var as VarBitbucket
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
from motor.montagem import GRUPO_TAREFAS

SEGREDO = "s3nha"
NOME_PLUGIN = "falso"
NOME_QUEBRADO = "quebrado"


class FonteFalsa:
    campos_config = (
        Campo(Escopo.GERAL, Tabela.TAREFAS, "projeto", TipoCampo.TEXTO, "Projeto"),
        Campo(
            Escopo.AMBIENTE,
            TABELA_AMBIENTE,
            "FAKE_TOKEN",
            TipoCampo.TEXTO,
            "Token",
            segredo=True,
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
    with open(caminho, "w") as f:
        f.write(texto)


def _instalar(monkeypatch, *pontos: EntryPoint) -> None:
    monkeypatch.setattr(
        plugins,
        "entry_points",
        lambda group: (
            list(pontos) if group == GRUPO_TAREFAS else entry_points(group=group)
        ),
    )


def _ep(nome: str, valor: str) -> EntryPoint:
    return EntryPoint(name=nome, value=valor, group=GRUPO_TAREFAS)


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
    assert {c.chave for c in campos} == {"projeto", "FAKE_TOKEN"}
    assert all(c.grupo is GrupoPlugin.TAREFAS for c in campos)
    assert all(c.grupo is None for c in catalogo_campos({}) if c.origem == ORIGEM_MOTOR)


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
        f'[repos.a]\n# do repo\ncaminho = "{tmp_path}"\n'
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
    _escrever(f'[repos.a]\ncaminho = "{tmp_path}"\n')
    antes = _bytes()
    with pytest.raises(ErroDeEntrada):
        gravar([alteracao], ler_para_edicao().versao)
    assert _bytes() == antes


def test_versao_velha_recusada():
    _escrever('[tarefas]\na = "1"\n')
    versao = ler_para_edicao().versao
    _escrever('[tarefas]\na = "2"\n')
    with pytest.raises(RecusaDeInvariante, match="recarregue"):
        gravar([_definir("3", "a", Tabela.TAREFAS)], versao)


def test_gravar_cria_arquivo_e_diretorio():
    gravar(
        [_definir(EMAIL_CENTRAL, VarBitbucket.EMAIL, TABELA_AMBIENTE)],
        hashlib.sha256(b"").hexdigest(),
    )
    assert stat.S_IMODE(os.stat(caminho_config_global()).st_mode) == MODO_ARQUIVO_NOVO


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
    _escrever(f'[repos.a]\ncaminho = "{tmp_path}"\n[repos.a.versao]\npiso = "1.0.0"\n')
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
    _escrever(f'[repos.a]\ncaminho = "{tmp_path}"\n')
    with pytest.raises(ErroDeEntrada):
        gravar([alteracao], ler_para_edicao().versao)


def test_rascunho_nao_grava():
    _escrever('[tarefas]\na = "1"\n')
    antes = _bytes()
    texto = rascunho([_definir("2", "a", Tabela.TAREFAS)], ler_para_edicao().versao)
    assert 'a = "2"' in texto
    assert _bytes() == antes


def test_rascunho_invalido_e_versao_velha(tmp_path):
    _escrever(f'[repos.a]\ncaminho = "{tmp_path}"\n')
    versao = ler_para_edicao().versao
    with pytest.raises(ErroDeEntrada):
        rascunho([_definir("abc", Chave.PISO, Tabela.VERSAO, "a")], versao)
    _escrever('[tarefas]\na = "2"\n')
    with pytest.raises(RecusaDeInvariante, match="recarregue"):
        rascunho([_definir("3", "a", Tabela.TAREFAS)], versao)
