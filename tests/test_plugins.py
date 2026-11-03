from __future__ import annotations

from importlib.metadata import EntryPoint

import pytest

from motor import plugins
from motor.errors import ErroDeEntrada

GRUPO = "monitor_versoes.teste"


class PluginDeTeste:
    pass


NAO_E_CLASSE = 42


def _instalar(monkeypatch, *pontos: EntryPoint):
    def falso(group):
        assert group == GRUPO
        return [p for p in pontos]

    monkeypatch.setattr(plugins, "entry_points", falso)


def _ep(nome: str, valor: str) -> EntryPoint:
    return EntryPoint(name=nome, value=valor, group=GRUPO)


def test_entry_point_carrega_por_nome(monkeypatch):
    _instalar(monkeypatch, _ep("teste", "tests.test_plugins:PluginDeTeste"))
    assert plugins.carregar_plugin(GRUPO, "teste", "repo") is PluginDeTeste


def test_nome_inexistente_lista_os_instalados(monkeypatch):
    _instalar(
        monkeypatch,
        _ep("b", "tests.test_plugins:PluginDeTeste"),
        _ep("a", "tests.test_plugins:PluginDeTeste"),
    )
    with pytest.raises(ErroDeEntrada, match=r"'x'.*instalados: a, b"):
        plugins.carregar_plugin(GRUPO, "x", "central")


def test_sem_instalados_diz_nenhum(monkeypatch):
    _instalar(monkeypatch)
    with pytest.raises(ErroDeEntrada, match="instalados: nenhum"):
        plugins.carregar_plugin(GRUPO, "x", "central")


def test_entry_point_que_nao_e_classe_e_erro(monkeypatch):
    _instalar(monkeypatch, _ep("n", "tests.test_plugins:NAO_E_CLASSE"))
    with pytest.raises(ErroDeEntrada, match=r"'n'.*nao e uma classe"):
        plugins.carregar_plugin(GRUPO, "n", "central")


def test_import_direto_funciona_no_central():
    alvo = plugins.carregar_plugin(GRUPO, "tests.test_plugins:PluginDeTeste", "central")
    assert alvo is PluginDeTeste


def test_import_direto_no_repo_e_recusado():
    with pytest.raises(ErroDeEntrada, match="repo nao escolhe codigo"):
        plugins.carregar_plugin(GRUPO, "tests.test_plugins:PluginDeTeste", "repo")


def test_modulo_inexistente_cita_o_nome_pedido():
    with pytest.raises(ErroDeEntrada, match=r"nao_existe_xyz:Foo"):
        plugins.carregar_plugin(GRUPO, "nao_existe_xyz:Foo", "central")


def test_classe_ausente_cita_o_nome_pedido():
    with pytest.raises(ErroDeEntrada, match=r"tests\.test_plugins:Ausente"):
        plugins.carregar_plugin(GRUPO, "tests.test_plugins:Ausente", "central")


def test_import_direto_que_nao_e_classe_e_erro():
    with pytest.raises(ErroDeEntrada, match="nao e uma classe"):
        plugins.carregar_plugin(GRUPO, "tests.test_plugins:NAO_E_CLASSE", "central")
