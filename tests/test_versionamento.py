"""Versionamento: esquema, politica, piso e nomes nas camadas config > esquema > padrao."""

import re

import pytest

from motor.atribuicoes import Exata
from motor.config import CHAVE_CAMINHO, SECAO_REPOS, carregar_config_repo
from motor.errors import ErroDeEntrada
from motor.esquemas.semver import Semver
from motor.montagem import resolver_versionamento
from motor.services.versionamento import Versionamento

_ESQUEMA_DE_TESTE = "tests.test_versionamento:EsquemaDeTeste"


class EsquemaDeTeste(Semver):
    """Declara as duas camadas de branch, para a config ter o que vencer."""

    branch_versao = "rel-{versao}"
    branch_principal = "trunk"


NOME_REPO = "repo"


@pytest.fixture
def escrever(tmp_path, monkeypatch):
    """Escreve o `config.toml` central: topo + `[repos.repo]`. `do_repo` usa
    cabeçalhos relativos à seção (`[branches]` vira `[repos.repo.branches]`)."""
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    raiz = tmp_path / NOME_REPO
    raiz.mkdir()
    (xdg / "monitor-versoes").mkdir(parents=True)
    central = xdg / "monitor-versoes" / "config.toml"

    def _escrever(topo: str = "", do_repo: str = "") -> str:
        do_repo = re.sub(r"^\[", f"[{SECAO_REPOS}.{NOME_REPO}.", do_repo, flags=re.M)
        central.write_text(
            f'{topo}[{SECAO_REPOS}.{NOME_REPO}]\n{CHAVE_CAMINHO} = "{raiz}"\n{do_repo}'
        )
        return str(central)

    _escrever()
    return _escrever


def _resolver() -> Versionamento:
    return resolver_versionamento(carregar_config_repo(NOME_REPO))


def test_sem_config_vale_semver_exata_e_main(escrever):
    v = _resolver()

    assert isinstance(v.esquema, Semver)
    assert isinstance(v.politica, Exata)
    assert (v.branch_versao, v.principal, v.tag_liberacao, v.piso) == (
        "{versao}",
        "main",
        None,
        None,
    )


@pytest.mark.parametrize(
    ("na_secao", "atributo", "esperado"),
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
    escrever, na_secao, atributo, esperado
):
    escrever(topo=f'[versao]\nesquema = "{_ESQUEMA_DE_TESTE}"\n', do_repo=na_secao)

    assert getattr(_resolver(), atributo) == esperado


def test_piso_que_o_esquema_nao_reconhece_cita_valor_e_arquivo(escrever):
    arquivo = escrever(do_repo='[versao]\npiso = "abc"\n')
    config = carregar_config_repo(NOME_REPO)

    with pytest.raises(ErroDeEntrada) as e:
        resolver_versionamento(config)
    assert "'abc'" in str(e.value)
    assert arquivo in str(e.value)


@pytest.mark.parametrize(
    ("conteudo", "trecho"),
    [
        ('[versao]\nesquema = "naoexiste"\n', "monitor_versoes.esquemas"),
        ('[versao]\natribuicao = "naoexiste"\n', "monitor_versoes.atribuicoes"),
    ],
)
def test_plugin_que_nao_carrega_e_erro_de_entrada(escrever, conteudo, trecho):
    escrever(do_repo=conteudo)
    config = carregar_config_repo(NOME_REPO)

    with pytest.raises(ErroDeEntrada) as e:
        resolver_versionamento(config)
    # A mensagem do carregador diz o grupo.
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
