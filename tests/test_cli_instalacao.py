from __future__ import annotations

import argparse
import shlex
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from motor import cli_instalacao
from motor.__main__ import main
from motor.cli_instalacao import COMANDO_ATUALIZAR_MOTOR, COMANDO_PLUGIN, AcaoPlugin
from motor.config import diretorio_cache
from motor.config_edicao import GrupoPlugin
from motor.errors import ErroDeEntrada
from motor.instalacao import (
    PACOTE_MOTOR,
    UV,
    Origem,
    PluginInstalado,
    Registro,
    Requisito,
    TipoOrigem,
)
from motor.novidades import (
    ARQUIVO_CACHE,
    TAMANHO_COMMIT_CURTO,
    Cache,
    Novidade,
    gravar_cache,
)

URL_MOTOR = "https://github.com/EduardoBllc/monitor-versoes"
PLUGIN_A = "monitor-versoes-extra"
PLUGIN_A_METADADO = "Monitor_Versoes.Extra"  # mesmo pacote, grafia do METADATA
URL_A = "https://github.com/EduardoBllc/monitor-versoes-extra"
PLUGIN_B = "monitor-versoes-outro"
URL_B = "git@github.com:EduardoBllc/monitor-versoes-outro.git"
URL_B_UV = "ssh://git@github.com/EduardoBllc/monitor-versoes-outro.git"
PUBLICADO = "meu-plugin"
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

MOTOR = Requisito(PACOTE_MOTOR, git=URL_MOTOR, ref=TAG_MOTOR, extras=(EXTRA,))
LINHA_MOTOR = f"{PACOTE_MOTOR}[{EXTRA}] @ git+{URL_MOTOR}@{TAG_MOTOR}"
INICIO = [UV, "tool", "install", "--reinstall"]


def _remoto(*, tags: tuple[str, ...] = (), head: str = COMMIT_NOVO) -> str:
    linhas = [f"{head}\tHEAD"]
    linhas += [f"{COMMIT_NOVO}\trefs/tags/{t}" for t in tags]
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


@pytest.fixture
def inst(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Instalacao:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(shutil, "which", lambda _nome: CAMINHO_UV)
    falsa = Instalacao([Registro(MOTOR, (Requisito(PLUGIN_A, git=URL_A),))])
    monkeypatch.setattr(cli_instalacao, "ler_registro", falsa.ler_registro)
    monkeypatch.setattr(cli_instalacao, "rodar_git", falsa.rodar_git)
    monkeypatch.setattr(cli_instalacao, "executar_uv", falsa.executar_uv)
    monkeypatch.setattr(cli_instalacao, "plugins_instalados", lambda: PLUGINS)
    return falsa


def _cache() -> Path:
    return Path(diretorio_cache()) / ARQUIVO_CACHE


def test_plugin_listar_por_grupo(inst: Instalacao, capsys) -> None:
    comando = f"{PACOTE_MOTOR} plugin atualizar {PLUGIN_A}"
    novidade = Novidade(PLUGIN_A, A_CURTO, VERSAO_A_NOVA, comando)
    gravar_cache(_cache(), Cache(datetime.now(UTC), (novidade,)))

    main([COMANDO_PLUGIN, AcaoPlugin.LISTAR])

    assert capsys.readouterr().out == (
        "esquemas\n"
        f"  padrao: {PACOTE_MOTOR} {VERSAO_MOTOR}, embutido\n"
        "tarefas\n"
        f"  extra: {PLUGIN_A} {VERSAO_A}, git {URL_A}@{A_CURTO} → {VERSAO_A_NOVA}\n"
        f"  publicado: {PUBLICADO} {VERSAO_PUBLICADO}, índice\n"
    )


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
            "--with",
            f"{PLUGIN_A} @ git+{URL_A}@{COMMIT_A}",
            "--with",
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


def test_plugin_instalar_repo_sem_tags_fixa_head(inst: Instalacao) -> None:
    inst.remotos[URL_B_UV] = _remoto()

    main([COMANDO_PLUGIN, AcaoPlugin.INSTALAR, URL_B])

    assert inst.comandos[0][-2:] == ["--with", f"git+{URL_B_UV}@{COMMIT_NOVO}"]


def test_plugin_por_nome_publicado(inst: Instalacao) -> None:
    main([COMANDO_PLUGIN, AcaoPlugin.INSTALAR, PUBLICADO])
    assert inst.comandos[-1][-2:] == ["--with", PUBLICADO]

    inst.registros = [
        Registro(MOTOR, (Requisito(PLUGIN_A, git=URL_A), Requisito(PUBLICADO)))
    ]
    main([COMANDO_PLUGIN, AcaoPlugin.ATUALIZAR, PUBLICADO])
    assert inst.comandos[-1][-4:] == [
        "--with",
        PUBLICADO,
        "--upgrade-package",
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
        [*INICIO, LINHA_MOTOR, "--with", f"{PLUGIN_A} @ git+{URL_A}@{COMMIT_NOVO}"]
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
            "--with",
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
