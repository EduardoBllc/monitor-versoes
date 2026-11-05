from __future__ import annotations

import pytest

from motor import config
from motor.config import database_url, worktrees_mantidas
from motor.errors import ErroDeEntrada

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


# --- config em camadas ---


@pytest.fixture
def camadas(tmp_path, monkeypatch):
    """(global, repo): XDG e raiz do repo isolados em tmp_path."""
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    repo = tmp_path / "repo"
    repo.mkdir()
    (xdg / "monitor-versoes").mkdir(parents=True)
    return xdg / "monitor-versoes" / "config.toml", repo / ".monitor-versoes.toml"


def test_piso_so_no_global(camadas):
    glob, repo = camadas
    glob.write_text('[versao]\npiso = "1.0.0"\n')
    assert config.carregar_config(str(repo.parent)).piso == "1.0.0"


def test_piso_so_no_repo(camadas):
    _, repo = camadas
    repo.write_text('[versao]\npiso = "2.0.0"\n')
    assert config.carregar_config(str(repo.parent)).piso == "2.0.0"


def test_piso_nos_dois_vence_o_repo(camadas):
    glob, repo = camadas
    glob.write_text('[versao]\npiso = "1.0.0"\n')
    repo.write_text('[versao]\npiso = "2.0.0"\n')
    assert config.carregar_config(str(repo.parent)).piso == "2.0.0"


def test_sem_piso_nas_duas_camadas_e_none(camadas):
    _, repo = camadas
    assert config.carregar_config(str(repo.parent)).piso is None


def test_tarefas_parcial_no_repo_sobrescreve_so_a_chave_declarada(camadas):
    glob, repo = camadas
    glob.write_text("[tarefas]\nsistema = 1\noutra = 'x'\n")
    repo.write_text("[tarefas]\nsistema = 2\n")
    assert dict(config.carregar_config(str(repo.parent)).tarefas) == {
        "sistema": 2,
        "outra": "x",
    }


def test_toml_invalido_cita_o_arquivo(camadas):
    _, repo = camadas
    repo.write_text("isto = = nao\n")
    with pytest.raises(ErroDeEntrada, match=r"\.monitor-versoes\.toml"):
        config.carregar_config(str(repo.parent))


@pytest.mark.parametrize("piso", ["1.2", "12", '""'])
def test_piso_invalido_e_erro_de_entrada(camadas, piso):
    _, repo = camadas
    repo.write_text(f"[versao]\npiso = {piso}\n")
    with pytest.raises(ErroDeEntrada):
        config.carregar_config(str(repo.parent))


def test_piso_fora_do_formato_e_lido_cru(camadas):
    # Quem valida o numero e o esquema em uso, quando e resolvido: ler o piso
    # nao pode derrubar `atualizar --abort`.
    _, repo = camadas
    repo.write_text('[versao]\npiso = "abc"\n')
    config_lida = config.carregar_config(str(repo.parent))
    assert (config_lida.piso, config_lida.arquivo_piso) == ("abc", str(repo))


@pytest.mark.parametrize(
    "tabela", ["versao", "tarefas", "referencia", "liberacao", "branches"]
)
def test_tabela_que_nao_e_tabela_e_erro(camadas, tabela):
    _, repo = camadas
    repo.write_text(f'{tabela} = "x"\n')
    with pytest.raises(ErroDeEntrada):
        config.carregar_config(str(repo.parent))


def test_padrao_de_referencia_do_repo_vence_o_global(camadas):
    glob, repo = camadas
    glob.write_text('[referencia]\npadrao = "a{id}"\n')
    repo.write_text('[referencia]\npadrao = "b{id}"\n')
    assert config.carregar_config(str(repo.parent)).padrao_referencia == "b{id}"


def test_padrao_de_referencia_so_no_global(camadas):
    glob, repo = camadas
    glob.write_text('[referencia]\npadrao = "a{id}"\n')
    assert config.carregar_config(str(repo.parent)).padrao_referencia == "a{id}"


def test_sem_referencia_o_padrao_e_none(camadas):
    _, repo = camadas
    assert config.carregar_config(str(repo.parent)).padrao_referencia is None


@pytest.mark.parametrize(
    ("conteudo", "valor"),
    [
        ('referencia = "x"\n', "'x'"),
        ("[referencia]\npadrao = 1\n", "1"),
        ('[referencia]\npadrao = "sem"\n', "'sem'"),
    ],
)
def test_referencia_invalida_cita_arquivo_e_valor(camadas, conteudo, valor):
    _, repo = camadas
    repo.write_text(conteudo)
    with pytest.raises(ErroDeEntrada) as e:
        config.carregar_config(str(repo.parent))
    # O texto é requisito: diz qual arquivo e qual valor corrigir.
    assert str(repo) in str(e.value)
    assert valor in str(e.value)


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


def test_arquivos_traz_global_primeiro(camadas):
    glob, repo = camadas
    assert config.carregar_config(str(repo.parent)).arquivos == (str(glob), str(repo))


def test_sem_raiz_ignora_a_camada_do_repo(camadas):
    glob, _ = camadas
    assert config.carregar_config(None).arquivos == (str(glob),)


def test_chave_esquema_e_ignorada(camadas):
    glob, _ = camadas
    glob.write_text('esquema = "vendabem"\n')
    assert config.carregar_config(None) == config.ConfigProjeto(arquivos=(str(glob),))


# --- esquema, atribuicao, liberacao e branches ---

_CHAVES_NOVAS = [
    # (atributo, tabela, chave, valor do global, valor do repo)
    ("esquema", "versao", "esquema", "semver", "vendabem"),
    ("atribuicao", "versao", "atribuicao", "exata", "composta"),
    ("tag_liberacao", "liberacao", "tag", "{versao}", "v{versao}"),
    ("branch_versao", "branches", "versao", "{versao}", "release/{versao}"),
    ("branch_principal", "branches", "principal", "master", "main"),
]


@pytest.mark.parametrize(
    ("atributo", "tabela", "chave", "glob_v", "repo_v"), _CHAVES_NOVAS
)
def test_chave_nova_do_repo_vence_o_global(
    camadas, atributo, tabela, chave, glob_v, repo_v
):
    glob, repo = camadas
    glob.write_text(f'[{tabela}]\n{chave} = "{glob_v}"\n')
    repo.write_text(f'[{tabela}]\n{chave} = "{repo_v}"\n')

    escolhido = getattr(config.carregar_config(str(repo.parent)), atributo)

    assert escolhido == config.Escolhido(repo_v, str(repo), "repo")


@pytest.mark.parametrize(
    ("atributo", "tabela", "chave", "glob_v", "repo_v"), _CHAVES_NOVAS
)
def test_chave_nova_so_no_global_vem_do_central(
    camadas, atributo, tabela, chave, glob_v, repo_v
):
    glob, repo = camadas
    glob.write_text(f'[{tabela}]\n{chave} = "{glob_v}"\n')

    escolhido = getattr(config.carregar_config(str(repo.parent)), atributo)

    assert escolhido == config.Escolhido(glob_v, str(glob), "central")


@pytest.mark.parametrize(
    ("conteudo", "valor"),
    [
        ('[liberacao]\ntag = "v"\n', "'v'"),
        ('[liberacao]\ntag = "{versao}-{versao}"\n', "'{versao}-{versao}'"),
        ('[branches]\nversao = "release"\n', "'release'"),
        ("[branches]\nprincipal = 1\n", "1"),
        ('[branches]\nprincipal = ""\n', "''"),
        ("[versao]\nesquema = true\n", "True"),
        ("[versao]\natribuicao = []\n", "[]"),
    ],
)
def test_valor_invalido_cita_arquivo_e_valor(camadas, conteudo, valor):
    _, repo = camadas
    repo.write_text(conteudo)
    with pytest.raises(ErroDeEntrada) as e:
        config.carregar_config(str(repo.parent))
    # O texto é requisito: diz qual arquivo e qual valor corrigir.
    assert str(repo) in str(e.value)
    assert valor in str(e.value)
