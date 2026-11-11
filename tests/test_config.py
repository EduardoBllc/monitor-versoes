from __future__ import annotations

import os

import pytest

from motor import config
from motor.config import (
    CHAVE_CAMINHO,
    SECAO_REPOS,
    VAR_XDG_CONFIG_HOME,
    VarAmbiente,
    database_url,
    worktrees_mantidas,
)
from motor.errors import ErroDeEntrada
from tests.config_repos import rotulo_secao, secao_repo

NOME = "x"

COMPLETO = {
    "DATABASE_HOST": "localhost",
    "DATABASE_PORT": "5433",
    "DATABASE_NAME": "monitor_versoes",
    "DATABASE_USER": "motor",
    "DATABASE_PASSWORD": "motor",
}


POSTGRES = {"DATABASE_BACKEND": "postgres"}


@pytest.fixture(autouse=True)
def _aviso_reiniciavel():
    config._avisos_emitidos.clear()


def _ambiente(monkeypatch, valores):
    for chave in (*COMPLETO, "DATABASE_BACKEND", "DATABASE_SQLITE_PATH"):
        monkeypatch.delenv(chave, raising=False)
    for chave, valor in valores.items():
        monkeypatch.setenv(chave, valor)


def test_database_url_monta_a_partir_das_partes(monkeypatch):
    _ambiente(monkeypatch, {**POSTGRES, **COMPLETO})
    assert database_url() == (
        "postgresql+psycopg://motor:motor@localhost:5433/monitor_versoes"
    )


def test_database_url_escapa_caractere_que_quebraria_a_url(monkeypatch):
    # Sem quote, "s@nha" faria a URL apontar para o host "nha" e o erro
    # observado seria "conexao recusada", nao "senha invalida".
    _ambiente(monkeypatch, {**POSTGRES, **COMPLETO, "DATABASE_PASSWORD": "s@nha//#"})
    assert "@localhost:5433/" in database_url()
    assert "s%40nha%2F%2F%23" in database_url()


def test_database_url_lista_todas_as_variaveis_faltando(monkeypatch):
    _ambiente(monkeypatch, {**POSTGRES, "DATABASE_HOST": "localhost"})
    with pytest.raises(ErroDeEntrada) as erro:
        database_url()
    assert "DATABASE_PORT" in str(erro.value)
    assert "DATABASE_PASSWORD" in str(erro.value)


def test_database_url_recusa_porta_nao_numerica(monkeypatch):
    # create_engine converte a porta na hora e levanta ValueError, que cairia no
    # ramo de bug do CLI (traceback) em vez de virar mensagem para o operador.
    _ambiente(monkeypatch, {**POSTGRES, **COMPLETO, "DATABASE_PORT": "5433a"})
    with pytest.raises(ErroDeEntrada) as erro:
        database_url()
    assert "DATABASE_PORT" in str(erro.value)


def test_sem_configuracao_usa_sqlite_no_caminho_padrao(monkeypatch, tmp_path, capsys):
    _ambiente(monkeypatch, {})
    monkeypatch.setenv("HOME", str(tmp_path))
    esperado = tmp_path / ".local" / "share" / "monitor-versoes" / "estado.db"
    assert database_url() == f"sqlite:///{esperado}"
    assert esperado.parent.is_dir()
    assert capsys.readouterr().err == ""


def test_sqlite_path_sobrescreve_o_padrao(monkeypatch, tmp_path):
    destino = tmp_path / "sub" / "x.db"
    _ambiente(monkeypatch, {"DATABASE_SQLITE_PATH": str(destino)})
    assert database_url() == f"sqlite:///{destino}"
    assert destino.parent.is_dir()


def test_backend_desconhecido_lista_os_aceitos(monkeypatch):
    _ambiente(monkeypatch, {"DATABASE_BACKEND": "mysql"})
    with pytest.raises(ErroDeEntrada) as erro:
        database_url()
    assert "sqlite, postgres" in str(erro.value)


def test_sem_backend_e_com_partes_completas_usa_sqlite_e_avisa(
    monkeypatch, tmp_path, capsys
):
    _ambiente(monkeypatch, {**COMPLETO, "DATABASE_SQLITE_PATH": str(tmp_path / "e.db")})
    assert database_url().startswith("sqlite:///")
    assert database_url().startswith("sqlite:///")
    err = capsys.readouterr().err
    assert "DATABASE_BACKEND=postgres" in err
    assert err.count("\n") == 1  # uma vez por execucao


def test_aviso_nao_sai_com_avisar_falso_nem_com_partes_incompletas(
    monkeypatch, tmp_path, capsys
):
    base = {"DATABASE_SQLITE_PATH": str(tmp_path / "e.db")}
    _ambiente(monkeypatch, {**COMPLETO, **base})
    database_url(avisar=False)
    _ambiente(monkeypatch, {"DATABASE_HOST": "h", **base})
    database_url()
    assert capsys.readouterr().err == ""


@pytest.mark.integracao
def test_sessao_postgres_ignora_o_ambiente(monkeypatch, request):
    """A fixture trunca sete tabelas — a URL dela nao pode sair do ambiente.

    Enquanto saia, um `.env` apontado para producao truncava producao, e o que
    segurava isso era a guarda `_exigir_banco_development`. Hoje a URL vem do
    container efemero; este teste falha se alguem reintroduzir o
    `create_engine(database_url())`.
    """
    # O container primeiro: ele povoa DATABASE_* no ambiente ao subir, entao
    # apontar para producao antes disso so seria sobrescrito e o teste passaria
    # sem testar nada.
    container = request.getfixturevalue("_postgres_efemero")
    _ambiente(monkeypatch, {**POSTGRES, **COMPLETO})
    sessao = request.getfixturevalue("sessao_postgres")
    url = sessao.get_bind().url.render_as_string(hide_password=False)
    assert url == container.get_connection_url()


# -- worktrees mantidas -------------------------------------------------------
#
# setenv("") em vez de delenv: e o que um `.env` com a linha vazia produz, e a
# disciplina do conftest para variavel "ausente" (ver docs/padroes/testes.md).


def test_worktrees_mantidas_default_quando_ausente(monkeypatch):
    monkeypatch.setenv("WORKTREES_MANTIDAS", "")
    assert worktrees_mantidas() == 3


def test_worktrees_mantidas_le_do_ambiente(monkeypatch):
    monkeypatch.setenv("WORKTREES_MANTIDAS", "7")
    assert worktrees_mantidas() == 7


def test_worktrees_mantidas_aceita_zero(monkeypatch):
    # 0 e o comportamento historico (worktree descartada a cada run), nao
    # "nao configurado" — por isso o default nao pode vir de `or`.
    monkeypatch.setenv("WORKTREES_MANTIDAS", "0")
    assert worktrees_mantidas() == 0


@pytest.mark.parametrize("valor", ["abc", "-1", "1.5", "3 worktrees"])
def test_worktrees_mantidas_recusa_valor_invalido(monkeypatch, valor):
    # Cair no default calado faria o operador achar que configurou.
    monkeypatch.setenv("WORKTREES_MANTIDAS", valor)
    with pytest.raises(ErroDeEntrada) as erro:
        worktrees_mantidas()
    assert "WORKTREES_MANTIDAS" in str(erro.value)


# --- caminho e leitura da config central ---


def test_xdg_config_home_e_respeitado(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.caminho_config_global() == str(
        tmp_path / "monitor-versoes" / "config.toml"
    )


@pytest.mark.parametrize("xdg", [None, ""])
def test_sem_xdg_cai_em_config_do_home(tmp_path, monkeypatch, xdg):
    if xdg is None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config.caminho_config_global() == str(
        tmp_path / ".config" / "monitor-versoes" / "config.toml"
    )


def _escrever(central, tmp_path, do_repo: str = "", topo: str = "") -> None:
    central.write_text(topo + secao_repo(NOME, _clone(tmp_path, NOME), do_repo))


def test_toml_invalido_cita_o_arquivo(central):
    central.write_text("isto = = nao\n")
    with pytest.raises(ErroDeEntrada, match=r"config\.toml"):
        config.carregar_config_global()


@pytest.mark.parametrize("piso", ["1.2", "12", '""'])
def test_piso_invalido_e_erro_de_entrada(central, tmp_path, piso):
    _escrever(central, tmp_path, f"[versao]\npiso = {piso}\n")
    with pytest.raises(ErroDeEntrada):
        config.carregar_config_repo(NOME)


def test_piso_fora_do_formato_e_lido_cru(central, tmp_path):
    # Quem valida o numero e o esquema em uso, quando e resolvido: ler o piso
    # nao pode derrubar `atualizar --abort`.
    _escrever(central, tmp_path, '[versao]\npiso = "abc"\n')
    lida = config.carregar_config_repo(NOME)
    assert (lida.piso, lida.arquivo_piso) == ("abc", rotulo_secao(central, NOME))


@pytest.mark.parametrize(
    "tabela", ["versao", "tarefas", "referencia", "liberacao", "branches"]
)
def test_tabela_que_nao_e_tabela_e_erro(central, tabela):
    central.write_text(f'{tabela} = "x"\n')
    with pytest.raises(ErroDeEntrada):
        config.carregar_config_global()


def test_sem_referencia_o_padrao_e_none(central):
    assert config.carregar_config_global().padrao_referencia is None


def test_arquivos_do_repo_traz_o_topo_e_a_secao(central, tmp_path):
    _escrever(central, tmp_path)
    assert config.carregar_config_repo(NOME).arquivos == (
        str(central),
        rotulo_secao(central, NOME),
    )


def test_config_global_ignora_as_secoes_de_repo(central, tmp_path):
    _escrever(central, tmp_path, "[tarefas]\nsistema = 7\n")
    assert config.carregar_config_global() == config.ConfigProjeto(
        arquivos=(str(central),)
    )


def test_chave_esquema_solta_e_ignorada(central):
    central.write_text('esquema = "escalonado"\n')
    assert config.carregar_config_global() == config.ConfigProjeto(
        arquivos=(str(central),)
    )


def test_fonte_de_tarefas_continua_em_tarefas(central, tmp_path):
    _escrever(
        central,
        tmp_path,
        "[tarefas]\nsistema = 7\n",
        topo='[tarefas]\nfonte = "rastreador"\n',
    )

    lido = config.carregar_config_repo(NOME)

    # o plugin recebe a tabela inteira, `fonte` inclusa.
    assert lido.tarefas == {"fonte": "rastreador", "sistema": 7}


# --- esquema, atribuicao, liberacao e branches ---

_CHAVES_NOVAS = [
    # (atributo, tabela, chave, valor do topo, valor da seção)
    ("esquema", "versao", "esquema", "semver", "escalonado"),
    ("atribuicao", "versao", "atribuicao", "exata", "composta"),
    ("tag_liberacao", "liberacao", "tag", "{versao}", "v{versao}"),
    ("branch_versao", "branches", "versao", "{versao}", "release/{versao}"),
    ("branch_principal", "branches", "principal", "master", "main"),
    ("fonte_tarefas", "tarefas", "fonte", "rastreador", "outro"),
]


@pytest.mark.parametrize(
    ("atributo", "tabela", "chave", "topo_v", "secao_v"), _CHAVES_NOVAS
)
def test_chave_nova_da_secao_vence_o_topo(
    central, tmp_path, atributo, tabela, chave, topo_v, secao_v
):
    _escrever(
        central,
        tmp_path,
        f'[{tabela}]\n{chave} = "{secao_v}"\n',
        topo=f'[{tabela}]\n{chave} = "{topo_v}"\n',
    )

    escolhido = getattr(config.carregar_config_repo(NOME), atributo)

    assert escolhido == config.Escolhido(secao_v, rotulo_secao(central, NOME))


@pytest.mark.parametrize(
    ("atributo", "tabela", "chave", "topo_v", "secao_v"), _CHAVES_NOVAS
)
def test_chave_nova_so_no_topo_vem_do_topo(
    central, tmp_path, atributo, tabela, chave, topo_v, secao_v
):
    _escrever(central, tmp_path, topo=f'[{tabela}]\n{chave} = "{topo_v}"\n')

    escolhido = getattr(config.carregar_config_repo(NOME), atributo)

    assert escolhido == config.Escolhido(topo_v, str(central))


@pytest.mark.parametrize(
    ("conteudo", "valor"),
    [
        ("[referencia]\npadrao = 1\n", "1"),
        ('[referencia]\npadrao = "sem"\n', "'sem'"),
        ('[liberacao]\ntag = "v"\n', "'v'"),
        ('[liberacao]\ntag = "{versao}-{versao}"\n', "'{versao}-{versao}'"),
        ('[branches]\nversao = "release"\n', "'release'"),
        ("[branches]\nprincipal = 1\n", "1"),
        ('[branches]\nprincipal = ""\n', "''"),
        ("[versao]\nesquema = true\n", "True"),
        ("[versao]\natribuicao = []\n", "[]"),
    ],
)
def test_valor_invalido_cita_arquivo_e_valor(central, tmp_path, conteudo, valor):
    _escrever(central, tmp_path, conteudo)
    with pytest.raises(ErroDeEntrada) as e:
        config.carregar_config_repo(NOME)
    # O texto é requisito: diz qual arquivo e qual valor corrigir.
    assert str(central) in str(e.value)
    assert valor in str(e.value)


# --- seções [repos.<nome>] da config central ---


@pytest.fixture
def central(tmp_path, monkeypatch):
    """Caminho do config.toml central, com XDG_CONFIG_HOME e HOME isolados."""
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("HOME", str(tmp_path))
    (xdg / "monitor-versoes").mkdir(parents=True)
    return xdg / "monitor-versoes" / "config.toml"


def _clone(tmp_path, nome="clone"):
    pasta = tmp_path / nome
    pasta.mkdir(exist_ok=True)
    return pasta


def _com_caminho(tmp_path, nome=NOME, relativo=""):
    return secao_repo(nome, _clone(tmp_path, nome), relativo)


def test_secao_vence_o_topo_chave_a_chave(central, tmp_path):
    central.write_text(
        '[versao]\nesquema = "a"\n[branches]\nprincipal = "main"\n'
        + _com_caminho(tmp_path, relativo='[versao]\nesquema = "b"\n')
    )
    cfg = config.carregar_config_repo(NOME)
    assert cfg.esquema is not None
    assert cfg.branch_principal is not None
    assert cfg.esquema.valor == "b"
    assert cfg.esquema.arquivo == rotulo_secao(central, NOME)
    assert cfg.branch_principal.valor == "main"
    assert cfg.branch_principal.arquivo == str(central)


def test_piso_na_secao_vale_so_para_o_repo(central, tmp_path):
    central.write_text(
        _com_caminho(tmp_path, NOME, '[versao]\npiso = "14.0.0"\n')
        + _com_caminho(tmp_path, "y")
    )
    assert config.carregar_config_repo(NOME).piso == "14.0.0"
    assert config.carregar_config_repo("y").piso is None


def test_piso_no_topo_e_erro(central, tmp_path):
    central.write_text('[versao]\npiso = "1.0.0"\n' + _com_caminho(tmp_path))
    padrao = rf"piso só vale em \[{SECAO_REPOS}\.<nome>\.versao\]"
    with pytest.raises(ErroDeEntrada, match=padrao):
        config.carregar_config_global()
    with pytest.raises(ErroDeEntrada, match=padrao):
        config.carregar_config_repo(NOME)


def test_tarefas_da_secao_sobrescreve_so_a_chave_declarada(central, tmp_path):
    central.write_text(
        '[tarefas]\nfonte = "t"\n'
        + _com_caminho(tmp_path, relativo="[tarefas]\nsistema = 7\n")
    )
    assert config.carregar_config_repo(NOME).tarefas == {"fonte": "t", "sistema": 7}


def test_padrao_de_referencia_da_secao_vence_o_topo(central, tmp_path):
    central.write_text(
        '[referencia]\npadrao = "a{id}"\n'
        + _com_caminho(tmp_path, relativo='[referencia]\npadrao = "b{id}"\n')
    )
    assert config.carregar_config_repo(NOME).padrao_referencia == "b{id}"
    assert config.carregar_config_global().padrao_referencia == "a{id}"


def test_caminho_expandido(central, tmp_path):
    _clone(tmp_path)
    central.write_text(secao_repo(NOME, "~/clone/"))
    assert config.carregar_config_repo(NOME).caminho == str(tmp_path / "clone")
    assert config.repos_configurados() == {NOME: str(tmp_path / "clone")}


def test_repo_sem_secao_lista_as_existentes(central, tmp_path):
    with pytest.raises(ErroDeEntrada, match=r"\(nenhuma\)"):
        config.carregar_config_repo("c")
    central.write_text(_com_caminho(tmp_path, "a") + _com_caminho(tmp_path, "b"))
    with pytest.raises(ErroDeEntrada, match="a, b"):
        config.carregar_config_repo("c")


def test_secao_sem_caminho_e_erro(central):
    central.write_text(secao_repo(NOME, None, "[versao]\n"))
    with pytest.raises(
        ErroDeEntrada, match=rf"\[{SECAO_REPOS}\.{NOME}\] {CHAVE_CAMINHO}"
    ):
        config.carregar_config_repo(NOME)


def test_caminho_que_nao_e_diretorio_e_erro(central, tmp_path):
    ausente = tmp_path / "ausente"
    central.write_text(secao_repo(NOME, ausente))
    with pytest.raises(ErroDeEntrada) as e:
        config.carregar_config_repo(NOME)
    assert f"[{SECAO_REPOS}.{NOME}]" in str(e.value)
    assert str(ausente) in str(e.value)


def test_nome_de_secao_invalido_e_erro(central):
    central.write_text(secao_repo('"a/b"', "/tmp"))
    with pytest.raises(ErroDeEntrada, match="nome simples"):
        config.repos_configurados()


@pytest.mark.parametrize(
    "conteudo", [f"{SECAO_REPOS} = 1\n", f"[{SECAO_REPOS}]\n{NOME} = 1\n"]
)
def test_repos_ou_secao_que_nao_e_tabela_e_erro(central, conteudo):
    central.write_text(conteudo)
    with pytest.raises(ErroDeEntrada, match=r"config\.toml"):
        config.repos_configurados()


def test_monitor_versoes_toml_no_clone_e_ignorado(central, tmp_path):
    central.write_text(_com_caminho(tmp_path))
    (tmp_path / NOME / ".monitor-versoes.toml").write_text('[versao]\npiso = "9.0.0"\n')
    assert config.carregar_config_repo(NOME).piso is None


def test_repos_configurados_ordena_e_tolera_sem_caminho(central):
    central.write_text(secao_repo("b", None, "[versao]\n") + secao_repo("a", "/abs"))
    assert list(config.repos_configurados().items()) == [("a", "/abs"), ("b", None)]


# --- [ambiente] ---


@pytest.mark.parametrize("conteudo", [None, '[versao]\nesquema = "a"\n'])
def test_ambiente_ausente_e_vazio(central, conteudo):
    if conteudo is not None:
        central.write_text(conteudo)
    assert config.ambiente_central() == {}


def test_ambiente_exporta_texto_e_inteiro_como_texto(central):
    central.write_text('[ambiente]\nA = "x"\nB = 5\n')
    assert config.ambiente_central() == {"A": "x", "B": "5"}


@pytest.mark.parametrize("valor", ["true", "2026-11-10", "[1, 2]", "{ x = 1 }"])
def test_ambiente_recusa_tipo_sem_forma_textual(central, valor):
    central.write_text(f"[ambiente]\nCHAVE_X = {valor}\n")
    with pytest.raises(ErroDeEntrada) as e:
        config.ambiente_central()
    assert str(central) in str(e.value)
    assert "CHAVE_X" in str(e.value)


def test_ambiente_que_nao_e_tabela_e_erro(central):
    central.write_text('ambiente = "x"\n')
    with pytest.raises(ErroDeEntrada, match=r"\[ambiente\] deve ser uma tabela"):
        config.ambiente_central()


@pytest.mark.parametrize(
    "ler", [config.ambiente_central, lambda: config.carregar_config_repo(NOME)]
)
def test_ambiente_por_repo_e_erro(central, tmp_path, ler):
    _escrever(central, tmp_path, '[ambiente]\nA = "x"\n')
    with pytest.raises(ErroDeEntrada) as e:
        ler()
    assert str(central) in str(e.value)
    assert f"[{SECAO_REPOS}.{NOME}.ambiente]" in str(e.value)


def test_postgres_incompleto_aponta_o_ambiente_central(central, monkeypatch):
    _ambiente(monkeypatch, POSTGRES)
    with pytest.raises(ErroDeEntrada) as e:
        database_url()
    assert "[ambiente]" in str(e.value)
    assert str(central) in str(e.value)
    assert ".env" in str(e.value)


def test_reaplicar_ambiente_restaura_chave_removida(monkeypatch):
    host, nome = VarAmbiente.DATABASE_HOST, VarAmbiente.DATABASE_NAME
    monkeypatch.setenv(host, "shell")
    monkeypatch.delenv(nome, raising=False)
    config.aplicar_ambiente_central({host: "central", nome: "x"})
    assert os.environ[host] == "central"
    config.aplicar_ambiente_central({})
    assert os.environ[host] == "shell"
    assert nome not in os.environ


def test_aplicar_ambiente_ignora_xdg():
    antes = os.environ.get(VAR_XDG_CONFIG_HOME)
    config.aplicar_ambiente_central({VAR_XDG_CONFIG_HOME: "/outro"})
    assert os.environ.get(VAR_XDG_CONFIG_HOME) == antes
