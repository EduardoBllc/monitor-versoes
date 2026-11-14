from __future__ import annotations

import httpx
import pytest
from monitor_versoes_jira import FonteJira
from monitor_versoes_jira.fonte import ChaveTarefas, VarJira

from motor.config_edicao import catalogo_campos
from motor.domain.commits import extrair_chamado
from motor.domain.referencia import Referencia
from motor.errors import ErroDeEntrada
from motor.montagem import GRUPO_TAREFAS
from motor.plugins import carregar_plugin
from motor.ports import TaskSource

_: type[TaskSource] = FonteJira


def test_entry_point_jira_carrega_a_fonte() -> None:
    assert carregar_plugin(GRUPO_TAREFAS, "jira") is FonteJira


def test_construir_sem_config_nao_faz_io() -> None:
    def falha(request: httpx.Request) -> httpx.Response:
        pytest.fail("construir não pode fazer I/O")

    client = httpx.Client(transport=httpx.MockTransport(falha))
    FonteJira(tarefas={}, arquivos=(), env={}, client=client)


def test_referencia_usa_o_projeto() -> None:
    fonte = FonteJira(tarefas={ChaveTarefas.PROJETO: "ABC"}, arquivos=())
    ref = fonte.referencia
    assert ref == Referencia("ABC-{id}", "0-9")
    assert extrair_chamado("ABC-123 corrige x", ref) == "123"
    assert extrair_chamado("ABC-12 corrige x", ref) == "12"


def test_referencia_sem_projeto_pede_a_chave() -> None:
    with pytest.raises(ErroDeEntrada):
        _ = FonteJira(tarefas={}, arquivos=("a.toml",)).referencia


def test_campos_aparecem_no_catalogo() -> None:
    campos = {
        c.chave: c
        for c in catalogo_campos({"tarefas": {"fonte": "jira"}})
        if c.origem == "jira"
    }
    assert set(campos) == {*ChaveTarefas, *VarJira}
    assert campos[VarJira.TOKEN].segredo
