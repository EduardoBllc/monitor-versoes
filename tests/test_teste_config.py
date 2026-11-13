"""Testar uma peça sobre o rascunho, num subprocesso real e sem rede."""

from __future__ import annotations

import os
import re
import stat
import sys
import tempfile

import pytest

from motor import teste_config
from motor.adapters.commitsource.bitbucket import Var as VarBitbucket
from motor.config import (
    AMBIENTE_PADRAO,
    CHAVE_CAMINHO,
    TABELA_AMBIENTE,
    Chave,
    Tabela,
    caminho_config_global,
    carregar_config_global,
)
from motor.config_edicao import AcaoAlteracao, Alteracao, gravar, ler_para_edicao
from motor.diagnostico import (
    Estado,
    Peca,
    PecaTestavel,
    diagnosticar_peca,
    onde_das_credenciais,
)
from motor.errors import ErroDeEntrada

SEGREDO = "s3nha-nao-salva"
REPO = "novo"
HOST_FALSO = "tests.fontes_falsas:HostFalso"
HOST_SAIDA_BINARIA = "tests.fontes_falsas:HostSaidaBinaria"
HOST_BITBUCKET = "bitbucket"
VAR_HOST_FALSO = "HOST_FALSO_TOKEN"
MODO_DIRETORIO_PRIVADO = 0o700
MODULO_HOMONIMO = "json.py"
VAR_PYTHONPATH = "PYTHONPATH"


def _definir(valor, chave, tabela=None, repo=None) -> Alteracao:
    return Alteracao(AcaoAlteracao.DEFINIR, repo, tabela, chave, valor)


def _repo_novo(caminho) -> list[Alteracao]:
    return [
        Alteracao(AcaoAlteracao.CRIAR_REPO, REPO),
        _definir(str(caminho), CHAVE_CAMINHO, repo=REPO),
    ]


@pytest.fixture(autouse=True)
def _fontes_falsas_importaveis(monkeypatch) -> None:
    """O subprocesso roda com `-P`: `tests.fontes_falsas` só entra pelo PYTHONPATH."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monkeypatch.setenv(VAR_PYTHONPATH, raiz)


@pytest.fixture
def temporarios(monkeypatch) -> dict[str, int]:
    """Diretório temporário criado pelo teste -> modo dele na criação."""
    criados: dict[str, int] = {}

    class Registrado(tempfile.TemporaryDirectory[str]):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            criados[self.name] = stat.S_IMODE(os.stat(self.name).st_mode)

    monkeypatch.setattr(tempfile, "TemporaryDirectory", Registrado)
    return criados


def test_repo_criado_no_rascunho_e_testado(tmp_path):
    versao = ler_para_edicao().versao

    resultado = teste_config.testar(
        _repo_novo(tmp_path), versao, PecaTestavel.REPO, REPO
    )

    assert resultado.peca is Peca.REPOS
    assert resultado.estado is Estado.OK
    # O salvar recusa caminho inexistente; o teste recusa igual (422 na rota).
    inexistente = str(tmp_path / "nao-existe")
    with pytest.raises(ErroDeEntrada, match=re.escape(inexistente)):
        teste_config.testar(_repo_novo(inexistente), versao, PecaTestavel.REPO, REPO)


@pytest.mark.parametrize("repo", [None, "ausente"])
def test_repo_fora_do_rascunho_e_erro_de_entrada(tmp_path, repo, temporarios):
    with pytest.raises(ErroDeEntrada):
        teste_config.testar(
            _repo_novo(tmp_path), ler_para_edicao().versao, PecaTestavel.REPO, repo
        )
    assert not temporarios


def test_correcao_cita_o_config_real(monkeypatch, temporarios):
    monkeypatch.delenv(VAR_HOST_FALSO, raising=False)

    resultado = teste_config.testar(
        [_definir(HOST_FALSO, Chave.FONTE, Tabela.PRS)],
        ler_para_edicao().versao,
        PecaTestavel.PRS,
        None,
    )

    assert resultado.estado is Estado.FALHA
    assert caminho_config_global() in resultado.correcao
    # A mesma linha que o diagnóstico dá com a config salva.
    gravar([_definir(HOST_FALSO, Chave.FONTE, Tabela.PRS)], ler_para_edicao().versao)
    assert resultado == diagnosticar_peca(
        PecaTestavel.PRS,
        config_central=carregar_config_global,
        repos=dict,
        onde=onde_das_credenciais(caminho_config_global(), AMBIENTE_PADRAO),
    )
    (temporario,) = temporarios
    assert temporario not in resultado.correcao


def test_detalhe_cita_o_config_real(temporarios):
    resultado = teste_config.testar(
        [_definir(HOST_BITBUCKET, Chave.FONTE, Tabela.PRS)],
        ler_para_edicao().versao,
        PecaTestavel.PRS,
        None,
    )

    assert resultado.estado is Estado.FALHA
    assert caminho_config_global() in resultado.detalhe
    (temporario,) = temporarios
    assert temporario not in str(resultado)


def test_saida_que_nao_e_utf8_vira_resultado():
    resultado = teste_config.testar(
        [_definir(HOST_SAIDA_BINARIA, Chave.FONTE, Tabela.PRS)],
        ler_para_edicao().versao,
        PecaTestavel.PRS,
        None,
    )

    assert resultado.peca is Peca.PRS
    assert resultado.estado is Estado.FALHA


def test_segredo_do_rascunho_nao_vaza(tmp_path, temporarios):
    alteracoes = [
        *_repo_novo(tmp_path),
        _definir(SEGREDO, VarBitbucket.TOKEN, TABELA_AMBIENTE),
    ]

    resultado = teste_config.testar(
        alteracoes, ler_para_edicao().versao, PecaTestavel.REPO, REPO
    )

    assert resultado.estado is Estado.OK
    assert SEGREDO not in str(resultado)
    # O Windows não tem modo POSIX; lá o temporário já é do usuário.
    if sys.platform != "win32":
        assert list(temporarios.values()) == [MODO_DIRETORIO_PRIVADO]
    assert not any(os.path.exists(t) for t in temporarios)


def test_modulo_homonimo_no_cwd_nao_e_importado(tmp_path, monkeypatch):
    plantado = tmp_path / "plantado"
    plantado.mkdir()
    marca = tmp_path / "importado"
    (plantado / MODULO_HOMONIMO).write_text(f"open({str(marca)!r}, 'w')\n")
    monkeypatch.chdir(plantado)

    resultado = teste_config.testar(
        _repo_novo(tmp_path), ler_para_edicao().versao, PecaTestavel.REPO, REPO
    )

    assert resultado.estado is Estado.OK
    assert not marca.exists()


def test_timeout_vira_falha(tmp_path, monkeypatch, temporarios):
    monkeypatch.setattr(teste_config, "TIMEOUT_TESTE", 0.001)

    resultado = teste_config.testar(
        _repo_novo(tmp_path), ler_para_edicao().versao, PecaTestavel.REPO, REPO
    )

    assert resultado.peca is Peca.REPOS
    assert resultado.estado is Estado.FALHA
    assert teste_config.TEMPO_ESGOTADO in resultado.detalhe
    assert not any(os.path.exists(t) for t in temporarios)


def test_env_do_daemon_nao_muda(monkeypatch):
    """O `[ambiente]` do rascunho vale no subprocesso e não no processo que testa."""
    monkeypatch.delenv(VAR_HOST_FALSO, raising=False)
    antes = dict(os.environ)

    resultado = teste_config.testar(
        [
            _definir(HOST_FALSO, Chave.FONTE, Tabela.PRS),
            _definir("certo", VAR_HOST_FALSO, TABELA_AMBIENTE),
            _definir(SEGREDO, VarBitbucket.TOKEN, TABELA_AMBIENTE),
        ],
        ler_para_edicao().versao,
        PecaTestavel.PRS,
        None,
    )

    assert resultado.estado is Estado.OK
    assert dict(os.environ) == antes
