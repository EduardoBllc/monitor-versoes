from __future__ import annotations

import argparse
import shlex
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from motor import agendador, ajudante, cli_instalacao, instalacao, novidades, servico
from motor.__main__ import main
from motor.agendador import SYSTEMCTL, Acao, Sistema
from motor.cli_instalacao import (
    COMANDO_ATUALIZAR_MOTOR,
    COMANDO_PLUGIN,
    COMANDO_POS_REINSTALAR,
    AcaoPlugin,
)
from motor.config import Chave, Tabela, caminho_config_global, diretorio_cache
from motor.config_edicao import GrupoPlugin
from motor.errors import CodigoSaida, ErroDeEntrada
from motor.instalacao import (
    ARQUIVO_REGISTRO,
    PACOTE_MOTOR,
    PREFIXO_GIT,
    UV,
    ArgUv,
    Origem,
    PluginInstalado,
    Registro,
    Requisito,
    TipoOrigem,
    registro_para_json,
)
from motor.novidades import (
    ARQUIVO_CACHE,
    PREFIXO_TAG,
    REF_HEAD,
    TAMANHO_COMMIT_CURTO,
    Cache,
    Novidade,
    gravar_cache,
    linha_aviso,
)
from tests.test_agendador import MOTIVO_FALHA
from tests.test_agendador import Registro as RegistroDeComandos

URL_MOTOR = "https://github.com/EduardoBllc/monitor-versoes"
PLUGIN_A = "monitor-versoes-extra"
PLUGIN_A_METADADO = "Monitor_Versoes.Extra"  # mesmo pacote, grafia do METADATA
URL_A = "https://github.com/EduardoBllc/monitor-versoes-extra"
PLUGIN_B = "monitor-versoes-outro"
URL_B = "git@github.com:EduardoBllc/monitor-versoes-outro.git"
URL_B_UV = "ssh://git@github.com/EduardoBllc/monitor-versoes-outro.git"
URL_B_HTTPS = "https://github.com/EduardoBllc/monitor-versoes-outro"
PUBLICADO = "meu-plugin"
PLUGIN_L = "monitor-versoes-local"
SUBDIR = "subdirectory=pkg/x"
COMMIT_A = "a" * 40
COMMIT_NOVO = "b" * 40
A_CURTO = COMMIT_A[:TAMANHO_COMMIT_CURTO]
NOVO_CURTO = COMMIT_NOVO[:TAMANHO_COMMIT_CURTO]
VERSAO_MOTOR = "0.2.0"
TAG_MOTOR = f"v{VERSAO_MOTOR}"
TAG_MOTOR_NOVA = "v0.3.0"
VERSAO_A = "1.0.0"
VERSAO_A_NOVA = "1.2.0"
VERSAO_PUBLICADO = "0.1.0"
TAG_B_VELHA = "v1.0.0"
TAG_B = "v1.2.0"
EXTRA = "anthropic"
CAMINHO_UV = "/usr/bin/uv"
PLUGIN_JIRA = "monitor-versoes-jira"
SUBDIR_JIRA = "plugins/jira"
VERSAO_JIRA = "0.1.0"
URL_JIRA = f"{URL_MOTOR}#subdirectory={SUBDIR_JIRA}"
LINHA_JIRA = f"{PLUGIN_JIRA} @ git+{URL_MOTOR}@{{ref}}#subdirectory={SUBDIR_JIRA}"

MOTOR = Requisito(PACOTE_MOTOR, git=URL_MOTOR, ref=TAG_MOTOR, extras=(EXTRA,))
LINHA_MOTOR = f"{PACOTE_MOTOR}[{EXTRA}] @ git+{URL_MOTOR}@{TAG_MOTOR}"
INICIO = [UV, ArgUv.TOOL, ArgUv.INSTALL, ArgUv.REINSTALL, ArgUv.NO_SOURCES]


def _remoto(*, tags: tuple[str, ...] = (), head: str = COMMIT_NOVO) -> str:
    linhas = [f"{head}\t{REF_HEAD}"]
    linhas += [f"{COMMIT_NOVO}\t{PREFIXO_TAG}{t}" for t in tags]
    return "\n".join(linhas)


@dataclass
class Instalacao:
    registros: list[Registro | None]  # em sequência; o último se repete
    remotos: dict[str, str] = field(default_factory=dict)
    retorno_uv: int = 0
    comandos: list[list[str]] = field(default_factory=list)
    consultados: list[str] = field(default_factory=list)

    def ler_registro(self) -> Registro | None:
        return self.registros.pop(0) if len(self.registros) > 1 else self.registros[0]

    def rodar_git(self, args: list[str], env: Mapping[str, str]) -> str | None:
        self.consultados.append(args[2])
        return self.remotos.get(args[2])

    def executar_uv(self, cmd: list[str]) -> int:
        self.comandos.append(cmd)
        return self.retorno_uv


PLUGINS = [
    PluginInstalado(
        GrupoPlugin.ESQUEMAS,
        "padrao",
        PACOTE_MOTOR,
        VERSAO_MOTOR,
        Origem(TipoOrigem.EMBUTIDO),
    ),
    PluginInstalado(
        GrupoPlugin.TAREFAS,
        "extra",
        PLUGIN_A,
        VERSAO_A,
        Origem(TipoOrigem.GIT, URL_A, None, COMMIT_A),
    ),
    PluginInstalado(
        GrupoPlugin.TAREFAS,
        "publicado",
        PUBLICADO,
        VERSAO_PUBLICADO,
        Origem(TipoOrigem.INDICE),
    ),
]


@pytest.fixture(autouse=True)
def _reinstala_direto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Em todo sistema, o caminho que chama o `uv` daqui; o do ajudante tem teste próprio."""
    monkeypatch.setattr(cli_instalacao, "_reinstala_pelo_ajudante", lambda: False)


@pytest.fixture
def inst(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Instalacao:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(shutil, "which", lambda _nome: CAMINHO_UV)
    falsa = Instalacao([Registro(MOTOR, (Requisito(PLUGIN_A, git=URL_A),))])
    monkeypatch.setattr(cli_instalacao, "ler_registro", falsa.ler_registro)
    monkeypatch.setattr(cli_instalacao, "rodar_git", falsa.rodar_git)
    monkeypatch.setattr(cli_instalacao, "executar_uv", falsa.executar_uv)
    monkeypatch.setattr(novidades, "ler_registro", falsa.ler_registro)
    monkeypatch.setattr(novidades, "disparar_renovacao", lambda _: None)
    monkeypatch.setattr(cli_instalacao, "plugins_instalados", lambda: PLUGINS)
    monkeypatch.setattr(instalacao, "plugins_instalados", lambda: PLUGINS)
    monkeypatch.setattr(cli_instalacao, "url_do_motor", lambda: URL_MOTOR)
    return falsa


def _cache() -> Path:
    return Path(diretorio_cache()) / ARQUIVO_CACHE


def test_plugin_listar_por_grupo(inst: Instalacao, capsys) -> None:
    comando = f"{PACOTE_MOTOR} plugin atualizar {PLUGIN_A}"
    novidade = Novidade(PLUGIN_A, A_CURTO, VERSAO_A_NOVA, comando)
    motor = Novidade(
        PACOTE_MOTOR, VERSAO_MOTOR, TAG_MOTOR_NOVA[1:], COMANDO_ATUALIZAR_MOTOR
    )
    gravar_cache(_cache(), Cache(datetime.now(UTC), (motor, novidade)))

    main([COMANDO_PLUGIN, AcaoPlugin.LISTAR])

    assert capsys.readouterr().out == (
        f"{linha_aviso(motor)}\n"
        "esquemas\n"
        f"  padrao: {PACOTE_MOTOR} {VERSAO_MOTOR}, embutido\n"
        "tarefas\n"
        f"  extra: {PLUGIN_A} {VERSAO_A}, git {URL_A}@{A_CURTO} → {VERSAO_A_NOVA}\n"
        f"  publicado: {PUBLICADO} {VERSAO_PUBLICADO}, índice\n"
    )


def test_plugin_listar_com_config_invalida_lista_sem_novidades(
    inst: Instalacao, capsys
) -> None:
    config = Path(caminho_config_global())
    config.parent.mkdir(parents=True)
    config.write_text(f'[{Tabela.ATUALIZACOES}]\n{Chave.CHECAR} = "talvez"\n')

    main([COMANDO_PLUGIN, AcaoPlugin.LISTAR])

    saida = capsys.readouterr().out
    assert f"  extra: {PLUGIN_A} {VERSAO_A}, git {URL_A}@{A_CURTO}\n" in saida


def test_plugin_instalar_url_git_preserva_resto(inst: Instalacao, capsys) -> None:
    inst.remotos[URL_B_UV] = _remoto(tags=(TAG_B_VELHA, TAG_B))
    _cache().parent.mkdir(parents=True)
    _cache().write_text("{}")
    a_fixado = Requisito(PLUGIN_A, git=URL_A, ref=COMMIT_A)
    b = Requisito(PLUGIN_B, git=URL_B_UV, ref=TAG_B)
    inst.registros.append(Registro(MOTOR, (a_fixado, b)))

    main([COMANDO_PLUGIN, AcaoPlugin.INSTALAR, URL_B])

    assert inst.comandos == [
        [
            *INICIO,
            LINHA_MOTOR,
            ArgUv.WITH,
            f"{PLUGIN_A} @ git+{URL_A}@{COMMIT_A}",
            ArgUv.WITH,
            f"git+{URL_B_UV}@{TAG_B}",
        ]
    ]
    assert not _cache().exists()
    saida = capsys.readouterr().out
    assert f"{PLUGIN_B}: instalado ({TAG_B})" in saida
    assert PLUGIN_A not in saida


def test_instalar_fixa_plugin_com_nome_grafado_diferente_no_metadado(
    inst: Instalacao, monkeypatch: pytest.MonkeyPatch
) -> None:
    git_a = Origem(TipoOrigem.GIT, URL_A, None, COMMIT_A)
    a = PluginInstalado(
        GrupoPlugin.TAREFAS, "extra", PLUGIN_A_METADADO, VERSAO_A, git_a
    )
    monkeypatch.setattr(cli_instalacao, "plugins_instalados", lambda: [a])
    inst.remotos[URL_B_UV] = _remoto(tags=(TAG_B,))

    main([COMANDO_PLUGIN, AcaoPlugin.INSTALAR, URL_B])

    assert f"{PLUGIN_A} @ git+{URL_A}@{COMMIT_A}" in inst.comandos[0]


@pytest.mark.parametrize(
    ("origem", "url", "ref"),
    [
        (URL_B_HTTPS, URL_B_HTTPS, None),
        (f"{URL_B_HTTPS}@{TAG_B_VELHA}", URL_B_HTTPS, TAG_B_VELHA),
        (URL_B, URL_B_UV, None),
        (f"{URL_B}@{TAG_B_VELHA}", URL_B_UV, TAG_B_VELHA),
        (f"{URL_B_UV}@{COMMIT_A}", URL_B_UV, COMMIT_A),
    ],
)
def test_plugin_instalar_url_com_ou_sem_ref(
    inst: Instalacao, origem: str, url: str, ref: str | None
) -> None:
    inst.remotos[url] = _remoto(tags=(TAG_B_VELHA, TAG_B))

    main([COMANDO_PLUGIN, AcaoPlugin.INSTALAR, origem])

    assert inst.comandos[0][-2:] == [ArgUv.WITH, f"{PREFIXO_GIT}{url}@{ref or TAG_B}"]
    assert inst.consultados == ([] if ref else [url])


def test_plugin_instalar_repo_sem_tags_fixa_head(inst: Instalacao) -> None:
    inst.remotos[URL_B_UV] = _remoto()

    main([COMANDO_PLUGIN, AcaoPlugin.INSTALAR, URL_B])

    assert inst.comandos[0][-2:] == [ArgUv.WITH, f"git+{URL_B_UV}@{COMMIT_NOVO}"]


def test_plugin_por_nome_publicado(inst: Instalacao) -> None:
    main([COMANDO_PLUGIN, AcaoPlugin.INSTALAR, PUBLICADO])
    assert inst.comandos[-1][-2:] == [ArgUv.WITH, PUBLICADO]

    inst.registros = [
        Registro(MOTOR, (Requisito(PLUGIN_A, git=URL_A), Requisito(PUBLICADO)))
    ]
    main([COMANDO_PLUGIN, AcaoPlugin.ATUALIZAR, PUBLICADO])
    assert inst.comandos[-1][-4:] == [
        ArgUv.WITH,
        PUBLICADO,
        ArgUv.UPGRADE_PACKAGE,
        PUBLICADO,
    ]
    assert inst.consultados == []


@pytest.mark.parametrize(
    ("pacote", "erro"),
    [(PLUGIN_A, None), (PACOTE_MOTOR, "embutido"), (PLUGIN_B, "não instalado")],
)
def test_plugin_remover(
    inst: Instalacao, monkeypatch: pytest.MonkeyPatch, pacote: str, erro: str | None
) -> None:
    if erro is None:
        main([COMANDO_PLUGIN, AcaoPlugin.REMOVER, pacote])
        assert inst.comandos == [[*INICIO, LINHA_MOTOR]]
        return
    # Chamado direto: o `main()` engole a exceção no `sys.exit(1)`.
    with pytest.raises(ErroDeEntrada, match=erro):
        cli_instalacao.plugin(_args(acao_plugin=AcaoPlugin.REMOVER, pacote=pacote))
    assert inst.comandos == []


def _args(**campos: object) -> argparse.Namespace:
    return argparse.Namespace(**campos)


def test_plugin_atualizar_leva_a_versao_nova_e_mantem_o_resto(
    inst: Instalacao, capsys
) -> None:
    inst.remotos[URL_A] = _remoto(head=COMMIT_NOVO)
    inst.remotos[URL_MOTOR] = _remoto(tags=(TAG_MOTOR, TAG_MOTOR_NOVA))
    a_novo = Requisito(PLUGIN_A, git=URL_A, ref=COMMIT_NOVO)
    inst.registros.append(Registro(MOTOR, (a_novo,)))

    main([COMANDO_PLUGIN, AcaoPlugin.ATUALIZAR])

    assert inst.comandos == [
        [*INICIO, LINHA_MOTOR, ArgUv.WITH, f"{PLUGIN_A} @ git+{URL_A}@{COMMIT_NOVO}"]
    ]
    saida = capsys.readouterr().out
    assert f"{PLUGIN_A}: {A_CURTO} → {NOVO_CURTO}" in saida
    assert f"{PACOTE_MOTOR} serve" in saida


@pytest.mark.parametrize(
    "argv",
    [[COMANDO_PLUGIN, AcaoPlugin.ATUALIZAR], [COMANDO_ATUALIZAR_MOTOR]],
)
def test_atualizar_sem_versao_nova_nao_reinstala(
    inst: Instalacao, capsys, argv: list[str]
) -> None:
    # Pacote do índice não tem checagem: só o pedido explícito o atualiza.
    publicado = Requisito(PUBLICADO)
    inst.registros = [Registro(MOTOR, (Requisito(PLUGIN_A, git=URL_A), publicado))]
    inst.remotos[URL_A] = _remoto(head=COMMIT_A)
    inst.remotos[URL_MOTOR] = _remoto(tags=(TAG_MOTOR,))

    main(argv)

    assert inst.comandos == []
    assert "tudo em dia" in capsys.readouterr().out


def test_atualizar_com_origem_sem_resposta_nao_diz_tudo_em_dia(
    inst: Instalacao, capsys
) -> None:
    inst.remotos[URL_MOTOR] = _remoto(tags=(TAG_MOTOR,))

    main([COMANDO_ATUALIZAR_MOTOR])

    assert inst.comandos == []
    saida = capsys.readouterr()
    assert f"Sem resposta de {URL_A}" in saida.err
    assert "tudo em dia" not in saida.out
    assert "nada a reinstalar" in saida.out.lower()


def test_atualizar_motor_leva_motor_e_plugins(inst: Instalacao, capsys) -> None:
    inst.remotos[URL_A] = _remoto(head=COMMIT_NOVO)
    inst.remotos[URL_MOTOR] = _remoto(tags=(TAG_MOTOR, TAG_MOTOR_NOVA))
    motor_novo = replace(MOTOR, ref=TAG_MOTOR_NOVA)
    a_novo = Requisito(PLUGIN_A, git=URL_A, ref=COMMIT_NOVO)
    inst.registros.append(Registro(motor_novo, (a_novo,)))

    main([COMANDO_ATUALIZAR_MOTOR])

    assert inst.comandos == [
        [
            *INICIO,
            f"{PACOTE_MOTOR}[{EXTRA}] @ git+{URL_MOTOR}@{TAG_MOTOR_NOVA}",
            ArgUv.WITH,
            f"{PLUGIN_A} @ git+{URL_A}@{COMMIT_NOVO}",
        ]
    ]
    saida = capsys.readouterr().out
    assert f"{PACOTE_MOTOR}: {TAG_MOTOR} → {TAG_MOTOR_NOVA}" in saida
    assert f"{PLUGIN_A}: {A_CURTO} → {NOVO_CURTO}" in saida


@pytest.mark.parametrize(
    ("registro", "uv", "texto"),
    [
        (None, CAMINHO_UV, "checkout de desenvolvimento"),
        (Registro(MOTOR, ()), None, "https://docs.astral.sh/uv/"),
    ],
)
def test_acoes_recusam_fora_de_uv_tool_ou_sem_uv(
    inst: Instalacao,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    registro: Registro | None,
    uv: str | None,
    texto: str,
) -> None:
    inst.registros = [registro]
    monkeypatch.setattr(shutil, "which", lambda _nome: uv)

    with pytest.raises(ErroDeEntrada, match=texto):
        cli_instalacao.atualizar_motor(_args())
    assert inst.comandos == []

    main([COMANDO_PLUGIN, AcaoPlugin.LISTAR])
    assert PLUGIN_A in capsys.readouterr().out


def test_falha_do_uv_imprime_comando_manual(inst: Instalacao, capsys) -> None:
    inst.retorno_uv = 1

    with pytest.raises(SystemExit) as saiu:
        main([COMANDO_PLUGIN, AcaoPlugin.REMOVER, PLUGIN_A])

    assert saiu.value.code == 1
    assert shlex.join([*INICIO, LINHA_MOTOR]) in capsys.readouterr().err


@pytest.mark.parametrize(
    "caminho", ["./meu-plugin", "../meu-plugin", "/home/x/meu-plugin", r"C:\x\plugin"]
)
def test_plugin_instalar_caminho_que_nao_e_pasta_recusa(
    inst: Instalacao, caminho: str
) -> None:
    with pytest.raises(ErroDeEntrada):
        cli_instalacao.plugin(_args(acao_plugin=AcaoPlugin.INSTALAR, origem=caminho))
    assert inst.comandos == []


@pytest.mark.parametrize("relativo", [False, True])
def test_plugin_instalar_pasta_local(
    inst: Instalacao, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relativo: bool
) -> None:
    pasta = tmp_path / "meu-plugin"
    pasta.mkdir()
    monkeypatch.chdir(tmp_path)

    main(
        [
            COMANDO_PLUGIN,
            AcaoPlugin.INSTALAR,
            "./meu-plugin" if relativo else str(pasta),
        ]
    )

    assert inst.comandos[0][-2:] == [ArgUv.WITH, str(pasta.resolve())]
    assert inst.consultados == []


@pytest.mark.parametrize(
    ("origem", "ref", "consulta"),
    [
        (f"{URL_B}#{SUBDIR}", TAG_B, True),
        (f"{URL_B}@{TAG_B_VELHA}#{SUBDIR}", TAG_B_VELHA, False),
    ],
)
def test_plugin_instalar_url_com_subdiretorio(
    inst: Instalacao, origem: str, ref: str, consulta: bool
) -> None:
    inst.remotos[URL_B_UV] = _remoto(tags=(TAG_B_VELHA, TAG_B))

    main([COMANDO_PLUGIN, AcaoPlugin.INSTALAR, origem])

    assert inst.comandos[0][-2:] == [
        ArgUv.WITH,
        f"{PREFIXO_GIT}{URL_B_UV}@{ref}#{SUBDIR}",
    ]
    assert inst.consultados == ([URL_B_UV] if consulta else [])


def _registro_com_local(pasta: Path) -> Registro:
    local = Requisito(PLUGIN_L, diretorio=str(pasta))
    return Registro(MOTOR, (Requisito(PLUGIN_A, git=URL_A, ref=COMMIT_A), local))


def test_plugin_atualizar_pacote_local_reinstala_da_pasta(
    inst: Instalacao, tmp_path: Path
) -> None:
    inst.registros = [_registro_com_local(tmp_path)]
    inst.remotos[URL_A] = _remoto(head=COMMIT_A)
    inst.remotos[URL_MOTOR] = _remoto(tags=(TAG_MOTOR,))

    main([COMANDO_PLUGIN, AcaoPlugin.ATUALIZAR])
    assert inst.comandos == []

    main([COMANDO_PLUGIN, AcaoPlugin.ATUALIZAR, PLUGIN_L])
    assert inst.comandos[0][-4:] == [
        ArgUv.WITH,
        f"{PLUGIN_L} @ {tmp_path.as_uri()}",
        ArgUv.UPGRADE_PACKAGE,
        PLUGIN_L,
    ]


def test_pasta_local_sumida_bloqueia_reinstalacao(
    inst: Instalacao, tmp_path: Path, capsys, caplog
) -> None:
    sumida = tmp_path / "sumiu"
    inst.registros = [_registro_com_local(sumida)]
    inst.remotos[URL_B_UV] = _remoto(tags=(TAG_B,))

    with pytest.raises(SystemExit) as saiu:
        main([COMANDO_PLUGIN, AcaoPlugin.INSTALAR, URL_B])

    assert saiu.value.code == CodigoSaida.ERRO
    mensagem = capsys.readouterr().err + caplog.text
    assert PLUGIN_L in mensagem
    assert str(sumida) in mensagem
    assert inst.comandos == []


def test_plugin_listar_mostra_origem_local(
    inst: Instalacao, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    local = PluginInstalado(
        GrupoPlugin.TAREFAS,
        "local",
        PLUGIN_L,
        VERSAO_A,
        Origem(TipoOrigem.LOCAL, url="/x/p"),
    )
    monkeypatch.setattr(cli_instalacao, "plugins_instalados", lambda: [local])

    main([COMANDO_PLUGIN, AcaoPlugin.LISTAR])

    assert f"  local: {PLUGIN_L} {VERSAO_A}, local /x/p\n" in capsys.readouterr().out


@pytest.mark.parametrize(
    "fonte",
    [
        f'{{ name = "{PLUGIN_L}", editable = "/x/p" }}',
        f'{{ name = "{PACOTE_MOTOR}", directory = "/x/motor" }}',
    ],
)
def test_atualizar_motor_com_origem_recusada_sai_com_codigo_proprio(
    inst: Instalacao, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fonte: str
) -> None:
    motor = f'{{ name = "{PACOTE_MOTOR}", git = "{URL_MOTOR}?rev={TAG_MOTOR}" }}'
    motor_e_fonte = [fonte] if PACOTE_MOTOR in fonte else [motor, fonte]
    (tmp_path / ARQUIVO_REGISTRO).write_text(
        f"[tool]\nrequirements = [{', '.join(motor_e_fonte)}]\n"
    )
    monkeypatch.setattr(
        cli_instalacao, "ler_registro", lambda: instalacao.ler_registro(tmp_path)
    )

    with pytest.raises(SystemExit) as saiu:
        main([COMANDO_ATUALIZAR_MOTOR])

    assert saiu.value.code == CodigoSaida.ORIGEM_RECUSADA
    assert inst.comandos == []


RAMO = "main"


@pytest.mark.parametrize("ref", [RAMO, A_CURTO, ""])
def test_plugin_instalar_recusa_ref_que_nao_fixa(inst: Instalacao, ref: str) -> None:
    with pytest.raises(ErroDeEntrada, match="commit completo"):
        cli_instalacao.plugin(
            _args(acao_plugin=AcaoPlugin.INSTALAR, origem=f"{URL_B_HTTPS}@{ref}")
        )
    assert inst.comandos == []


def _jira(ref: str) -> Requisito:
    return Requisito(PLUGIN_JIRA, git=URL_MOTOR, ref=ref, subdiretorio=SUBDIR_JIRA)


def test_plugin_listar_mostra_repo_do_motor(
    inst: Instalacao, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    jira = PluginInstalado(
        GrupoPlugin.TAREFAS,
        "jira",
        PLUGIN_JIRA,
        VERSAO_JIRA,
        Origem(TipoOrigem.GIT, URL_MOTOR, TAG_MOTOR, COMMIT_A, SUBDIR_JIRA),
    )
    monkeypatch.setattr(cli_instalacao, "plugins_instalados", lambda: [jira])

    main([COMANDO_PLUGIN, AcaoPlugin.LISTAR])

    assert (
        f"  jira: {PLUGIN_JIRA} {VERSAO_JIRA}, repo do motor ({SUBDIR_JIRA}) "
        f"{TAG_MOTOR}\n"
    ) in capsys.readouterr().out


def test_plugin_do_repo_do_motor_instala_na_tag_do_motor(inst: Instalacao) -> None:
    main([COMANDO_PLUGIN, AcaoPlugin.INSTALAR, f"{PREFIXO_GIT}{URL_JIRA}"])

    assert inst.comandos == [
        [
            *INICIO,
            LINHA_MOTOR,
            ArgUv.WITH,
            f"{PLUGIN_A} @ git+{URL_A}@{COMMIT_A}",
            ArgUv.WITH,
            f"{PREFIXO_GIT}{URL_MOTOR}@{TAG_MOTOR}#subdirectory={SUBDIR_JIRA}",
        ]
    ]
    assert inst.consultados == []


def test_plugin_do_repo_do_motor_recusa_ref_diferente_da_tag_do_motor(
    inst: Instalacao,
) -> None:
    origem = f"{PREFIXO_GIT}{URL_MOTOR}@v9.9.9#subdirectory={SUBDIR_JIRA}"

    with pytest.raises(ErroDeEntrada):
        cli_instalacao.plugin(_args(acao_plugin=AcaoPlugin.INSTALAR, origem=origem))

    assert inst.comandos == []


@pytest.mark.parametrize("pacote", [PLUGIN_JIRA, None])
def test_plugin_atualizar_nao_move_plugin_do_repo_do_motor(
    inst: Instalacao, capsys, pacote: str | None
) -> None:
    inst.registros = [Registro(MOTOR, (_jira(TAG_MOTOR),))]

    main([COMANDO_PLUGIN, AcaoPlugin.ATUALIZAR, *([pacote] if pacote else [])])

    assert inst.comandos == []
    assert inst.consultados == []
    saida = capsys.readouterr().out
    assert "acompanha o motor" in saida
    assert f"{PACOTE_MOTOR} {COMANDO_ATUALIZAR_MOTOR}" in saida


def test_atualizar_motor_leva_plugins_do_repo_a_mesma_tag(inst: Instalacao) -> None:
    inst.remotos[URL_MOTOR] = _remoto(tags=(TAG_MOTOR, TAG_MOTOR_NOVA))
    inst.registros = [Registro(MOTOR, (_jira(TAG_MOTOR),))]

    main([COMANDO_ATUALIZAR_MOTOR])

    assert inst.comandos == [
        [
            *INICIO,
            f"{PACOTE_MOTOR}[{EXTRA}] @ git+{URL_MOTOR}@{TAG_MOTOR_NOVA}",
            ArgUv.WITH,
            LINHA_JIRA.format(ref=TAG_MOTOR_NOVA),
        ]
    ]
    assert inst.consultados == [URL_MOTOR]


def test_atualizar_motor_em_dia_alinha_plugin_do_repo_a_tag_do_motor(
    inst: Instalacao,
) -> None:
    inst.remotos[URL_MOTOR] = _remoto(tags=(TAG_MOTOR,))
    inst.registros = [Registro(MOTOR, (_jira(TAG_B_VELHA),))]

    main([COMANDO_ATUALIZAR_MOTOR])

    assert inst.comandos == [
        [*INICIO, LINHA_MOTOR, ArgUv.WITH, LINHA_JIRA.format(ref=TAG_MOTOR)]
    ]


def test_atualizar_motor_sem_ref_nao_apaga_a_tag_do_plugin_do_repo(
    inst: Instalacao,
) -> None:
    inst.remotos[URL_MOTOR] = _remoto(tags=(TAG_MOTOR,))
    sem_ref = replace(MOTOR, ref=None)
    inst.registros = [Registro(sem_ref, (_jira(TAG_MOTOR),))]

    main([COMANDO_ATUALIZAR_MOTOR])

    assert inst.comandos == []


@pytest.mark.parametrize("ligado", [True, False])
@pytest.mark.parametrize(
    "argv",
    [[COMANDO_PLUGIN, AcaoPlugin.INSTALAR, URL_B], [COMANDO_ATUALIZAR_MOTOR]],
)
def test_reinstalar_reinicia_o_servico_ligado(
    inst: Instalacao,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    argv: list[str],
    ligado: bool,
) -> None:
    inst.remotos[URL_A] = _remoto(head=COMMIT_NOVO)
    inst.remotos[URL_B_UV] = _remoto(tags=(TAG_B,))
    inst.remotos[URL_MOTOR] = _remoto(tags=(TAG_MOTOR, TAG_MOTOR_NOVA))
    if ligado:
        arquivo = servico.caminho(Sistema.LINUX, Path.home())
        arquivo.parent.mkdir(parents=True)
        arquivo.write_text("")
    monkeypatch.setattr(servico, "sistema_atual", lambda: Sistema.LINUX)
    chamados: list[list[str]] = []
    monkeypatch.setattr(agendador, "rodar_comando_do_sistema", chamados.append)

    main(argv)

    saida = capsys.readouterr().out
    if ligado:
        assert chamados == [[*SYSTEMCTL, Acao.RESTART, servico.ARQUIVO_SERVICE]]
        assert "reinicie-o" not in saida
    else:
        assert chamados == []
        assert f"Se o `{PACOTE_MOTOR} serve` estiver rodando, reinicie-o." in saida


def test_reinstalar_com_o_reinicio_falhando_avisa_e_mantem_o_sucesso(
    inst: Instalacao, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inst.remotos[URL_B_UV] = _remoto(tags=(TAG_B,))
    arquivo = servico.caminho(Sistema.LINUX, Path.home())
    arquivo.parent.mkdir(parents=True)
    arquivo.write_text("")
    monkeypatch.setattr(servico, "sistema_atual", lambda: Sistema.LINUX)
    monkeypatch.setattr(
        agendador,
        "rodar_comando_do_sistema",
        RegistroDeComandos(falhar_em=Acao.RESTART),
    )

    main([COMANDO_PLUGIN, AcaoPlugin.INSTALAR, URL_B])

    saida = capsys.readouterr().out
    assert f"Se o `{PACOTE_MOTOR} serve` estiver rodando, reinicie-o." in saida
    assert MOTIVO_FALHA in saida


def test_reinstalar_no_windows_entrega_ao_ajudante(
    inst: Instalacao, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_instalacao, "_reinstala_pelo_ajudante", lambda: True)
    entregues: list[tuple[Registro, list[str]]] = []
    monkeypatch.setattr(
        ajudante, "entregar", lambda antes, cmd: entregues.append((antes, cmd))
    )
    antes = Registro(MOTOR, ())
    cmd = [*INICIO, LINHA_MOTOR]

    cli_instalacao._reinstalar(antes, cmd)

    assert entregues == [(antes, cmd)]
    assert inst.comandos == []


def test_pos_reinstalar_imprime_mudancas_e_apaga_o_cache(
    inst: Instalacao, capsys
) -> None:
    antes = Registro(MOTOR, (_jira(TAG_MOTOR),))
    inst.registros = [Registro(MOTOR, (_jira(TAG_MOTOR_NOVA),))]
    pasta = ajudante.pasta_reinstalacao()
    pasta.mkdir(parents=True)
    (pasta / ajudante.ARQUIVO_ANTES).write_text(registro_para_json(antes))
    _cache().parent.mkdir(parents=True)
    _cache().write_text("{}")

    main([COMANDO_POS_REINSTALAR])

    assert (
        capsys.readouterr().out == f"  {PLUGIN_JIRA}: {TAG_MOTOR} → {TAG_MOTOR_NOVA}\n"
    )
    assert not _cache().exists()
