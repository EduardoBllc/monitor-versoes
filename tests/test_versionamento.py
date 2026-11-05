"""Versionamento: esquema, politica, piso e nomes nas camadas config > esquema > padrao."""

import pytest

from motor.atribuicoes import Exata
from motor.config import carregar_config
from motor.errors import ErroDeEntrada
from motor.esquemas.semver import Semver
from motor.montagem import resolver_versionamento
from motor.services.versionamento import Versionamento

_ESQUEMA_DE_TESTE = "tests.test_versionamento:EsquemaDeTeste"


class EsquemaDeTeste(Semver):
    """Declara as duas camadas de branch, para a config ter o que vencer."""

    branch_versao = "rel-{versao}"
    branch_principal = "trunk"


@pytest.fixture
def camadas(tmp_path, monkeypatch):
    """(global, repo): XDG e raiz do repo isolados em tmp_path."""
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    repo = tmp_path / "repo"
    repo.mkdir()
    (xdg / "monitor-versoes").mkdir(parents=True)
    return xdg / "monitor-versoes" / "config.toml", repo / ".monitor-versoes.toml"


def _resolver(repo) -> Versionamento:
    return resolver_versionamento(carregar_config(str(repo.parent)))


def test_sem_config_vale_semver_exata_e_main(camadas):
    _, repo = camadas

    v = _resolver(repo)

    assert isinstance(v.esquema, Semver)
    assert isinstance(v.politica, Exata)
    assert (v.branch_versao, v.principal, v.tag_liberacao, v.piso) == (
        "{versao}",
        "main",
        None,
        None,
    )


@pytest.mark.parametrize(
    ("no_repo", "atributo", "esperado"),
    [
        ("", "principal", "trunk"),
        ('[branches]\nprincipal = "dev"\n', "principal", "dev"),
        ("", "branch_versao", "rel-{versao}"),
        (
            '[branches]\nversao = "release/{versao}"\n',
            "branch_versao",
            "release/{versao}",
        ),
    ],
)
def test_config_vence_o_esquema_nos_nomes_de_branch(
    camadas, no_repo, atributo, esperado
):
    glob, repo = camadas
    glob.write_text(f'[versao]\nesquema = "{_ESQUEMA_DE_TESTE}"\n')
    repo.write_text(no_repo)

    assert getattr(_resolver(repo), atributo) == esperado


def test_piso_que_o_esquema_nao_reconhece_cita_valor_e_arquivo(camadas):
    _, repo = camadas
    repo.write_text('[versao]\npiso = "abc"\n')
    config = carregar_config(str(repo.parent))

    with pytest.raises(ErroDeEntrada) as e:
        resolver_versionamento(config)
    assert "'abc'" in str(e.value)
    assert str(repo) in str(e.value)


@pytest.mark.parametrize(
    ("conteudo", "trecho"),
    [
        ('[versao]\nesquema = "naoexiste"\n', "monitor_versoes.esquemas"),
        ('[versao]\natribuicao = "naoexiste"\n', "monitor_versoes.atribuicoes"),
        (f'[versao]\nesquema = "{_ESQUEMA_DE_TESTE}"\n', "config.toml central"),
    ],
)
def test_plugin_que_nao_carrega_e_erro_de_entrada(camadas, conteudo, trecho):
    _, repo = camadas
    repo.write_text(conteudo)
    config = carregar_config(str(repo.parent))

    with pytest.raises(ErroDeEntrada) as e:
        resolver_versionamento(config)
    # A mensagem do carregador diz o grupo ou por que o import direto foi recusado.
    assert trecho in str(e.value)


@pytest.mark.parametrize(
    ("nome", "versao"),
    [
        ("release/1.2.0", "1.2.0"),
        ("release/x", None),
        ("main", None),
        ("release/", None),
    ],
)
def test_versao_da_branch_inverte_o_template(nome, versao):
    v = Versionamento(
        esquema=Semver(), politica=Exata(), branch_versao="release/{versao}"
    )

    assert v.versao_da_branch(nome) == versao
