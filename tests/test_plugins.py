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
    def falso(grupo):
        assert grupo == GRUPO
        return pontos

    monkeypatch.setattr(plugins, "pontos_instalados", falso)


def _ep(nome: str, valor: str) -> EntryPoint:
    return EntryPoint(name=nome, value=valor, group=GRUPO)


def test_entry_point_carrega_por_nome(monkeypatch):
    _instalar(monkeypatch, _ep("teste", "tests.test_plugins:PluginDeTeste"))
    assert plugins.carregar_plugin(GRUPO, "teste") is PluginDeTeste


def test_nome_inexistente_lista_os_instalados(monkeypatch):
    _instalar(
        monkeypatch,
        _ep("b", "tests.test_plugins:PluginDeTeste"),
        _ep("a", "tests.test_plugins:PluginDeTeste"),
    )
    with pytest.raises(ErroDeEntrada, match=r"'x'.*instalados: a, b"):
        plugins.carregar_plugin(GRUPO, "x")


def test_sem_instalados_diz_nenhum(monkeypatch):
    _instalar(monkeypatch)
    with pytest.raises(ErroDeEntrada, match="instalados: nenhum"):
        plugins.carregar_plugin(GRUPO, "x")


def test_entry_point_que_nao_e_classe_e_erro(monkeypatch):
    _instalar(monkeypatch, _ep("n", "tests.test_plugins:NAO_E_CLASSE"))
    with pytest.raises(ErroDeEntrada):
        plugins.carregar_plugin(GRUPO, "n")


def test_import_direto_aceito_sem_origem():
    alvo = plugins.carregar_plugin(GRUPO, "tests.test_plugins:PluginDeTeste")
    assert alvo is PluginDeTeste


@pytest.mark.parametrize(
    "pedido",
    [
        "nao_existe_xyz:Foo",
        "tests.test_plugins:Ausente",
        "tests.test_plugins:NAO_E_CLASSE",
    ],
)
def test_import_direto_invalido_e_erro(pedido):
    with pytest.raises(ErroDeEntrada):
        plugins.carregar_plugin(GRUPO, pedido)


def _pacote_instalado(pasta, nome: str) -> None:
    info = pasta / f"{nome}-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {nome}\nVersion: 1.0\n"
    )
    (info / "entry_points.txt").write_text(
        f"[{GRUPO}]\n{nome} = tests.test_plugins:PluginDeTeste\n"
    )


def test_plugin_instalado_depois_da_consulta_aparece_sem_reiniciar(
    tmp_path, monkeypatch
):
    monkeypatch.syspath_prepend(str(tmp_path))
    _pacote_instalado(tmp_path, "primeiro")
    assert plugins.nomes_instalados(GRUPO) == ["primeiro"]

    _pacote_instalado(tmp_path, "segundo")

    assert plugins.nomes_instalados(GRUPO) == ["primeiro", "segundo"]
    assert plugins.carregar_plugin(GRUPO, "segundo") is PluginDeTeste
