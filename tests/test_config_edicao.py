from __future__ import annotations

import hashlib
import os
from importlib.metadata import EntryPoint

import pytest

from motor import plugins
from motor.config import caminho_config_global
from motor.config_edicao import (
    Campo,
    Escopo,
    TipoCampo,
    catalogo_campos,
    ler_para_edicao,
)
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
