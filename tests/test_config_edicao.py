from __future__ import annotations

import hashlib
import os
import stat
from importlib.metadata import EntryPoint

import pytest

from motor import plugins
from motor.config import (
    BACKENDS,
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
    Escopo,
    TipoCampo,
    catalogo_campos,
    gravar,
    ler_para_edicao,
)
from motor.errors import ErroDeEntrada, RecusaDeInvariante
from motor.montagem import GRUPO_TAREFAS

SEGREDO = "s3nha"
NOME_PLUGIN = "falso"
NOME_QUEBRADO = "quebrado"


class FonteFalsa:
    campos_config = (
        Campo(Escopo.GERAL, "tarefas", "projeto", TipoCampo.TEXTO, "Projeto"),
        Campo(
            Escopo.AMBIENTE,
            "ambiente",
            "FAKE_TOKEN",
            TipoCampo.TEXTO,
            "Token",
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
        lambda group: list(pontos) if group == GRUPO_TAREFAS else [],
    )


def _ep(nome: str, valor: str) -> EntryPoint:
    return EntryPoint(name=nome, value=valor, group=GRUPO_TAREFAS)


def test_segredo_nunca_sai_na_leitura():
    _escrever(f'[ambiente]\nDATABASE_PASSWORD = "{SEGREDO}"\n')
    lido = ler_para_edicao()
    [v] = [v for v in lido.valores if v.chave == "DATABASE_PASSWORD"]
    assert v.valor is None and v.definido is True
    assert SEGREDO not in repr(lido)


def test_plugin_instalado_declara_campos(monkeypatch):
    _instalar(monkeypatch, _ep(NOME_PLUGIN, "tests.test_config_edicao:FonteFalsa"))
    campos = [c for c in catalogo_campos({}) if c.origem == NOME_PLUGIN]
    assert {c.chave for c in campos} == {"projeto", "FAKE_TOKEN"}


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
    caminho = next(v for v in lido.valores if v.chave == "caminho")
    assert (caminho.repo, caminho.tabela, caminho.valor) == ("app", None, "/a")
    assert lido.repos == ["app"]


def test_modulo_classe_em_uso_vira_opcao_do_campo():
    _escrever('[tarefas]\nfonte = "tests.test_config_edicao:FonteFalsa"\n')
    campo = next(c for c in ler_para_edicao().campos if c.chave == "fonte")
    assert "tests.test_config_edicao:FonteFalsa" in campo.opcoes


def test_versao_e_hash_do_arquivo():
    assert ler_para_edicao().versao == hashlib.sha256(b"").hexdigest()
    _escrever('[tarefas]\na = "1"\n')
    antes = ler_para_edicao().versao
    _escrever('[tarefas]\na = "2"\n')
    assert ler_para_edicao().versao != antes


@pytest.mark.parametrize("chave", ["esquema", "atribuicao"])
def test_opcoes_incluem_os_instalados(chave):
    campo = next(c for c in ler_para_edicao().campos if c.chave == chave)
    assert campo.opcoes


SQLITE, POSTGRES = BACKENDS
MODO_NOVO = 0o600
MODO_GRUPO = 0o640
CHAVE_LISTA = "filtros"


@pytest.fixture(autouse=True)
def _backend_base(monkeypatch):
    """Gravar reaplica o `[ambiente]` no processo; o monkeypatch o desfaz no fim."""
    monkeypatch.setenv(VarAmbiente.DATABASE_BACKEND, SQLITE)


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
        _definir("cinco", VarAmbiente.DATABASE_PORT, TABELA_AMBIENTE),
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
        [_definir(SQLITE, VarAmbiente.DATABASE_BACKEND, TABELA_AMBIENTE)],
        hashlib.sha256(b"").hexdigest(),
    )
    assert stat.S_IMODE(os.stat(caminho_config_global()).st_mode) == MODO_NOVO


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
        [_definir(POSTGRES, VarAmbiente.DATABASE_BACKEND, TABELA_AMBIENTE)],
        ler_para_edicao().versao,
    )
    assert os.environ[VarAmbiente.DATABASE_BACKEND] == POSTGRES
    gravar(
        [
            Alteracao(
                AcaoAlteracao.REMOVER,
                tabela=TABELA_AMBIENTE,
                chave=VarAmbiente.DATABASE_BACKEND,
            )
        ],
        definida.versao,
    )
    assert os.environ[VarAmbiente.DATABASE_BACKEND] == SQLITE
