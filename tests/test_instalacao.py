from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from motor.config_edicao import GrupoPlugin
from motor.instalacao import (
    PACOTE_MOTOR,
    Origem,
    Requisito,
    TipoOrigem,
    comando_reinstalar,
    fixar_soltos,
    ler_registro,
    origem_do_pacote,
    plugins_instalados,
)

URL_MOTOR = "https://github.com/EduardoBllc/monitor-versoes"
PLUGIN = "monitor-versoes-extra"
URL_PLUGIN = "https://github.com/EduardoBllc/monitor-versoes-extra"
TAG = "v0.2.0"

# Formato real do `uv tool install`: a revisão vai na própria URL, em `?rev=`.
RECIBO = f"""\
[tool]
requirements = [
    {{ name = "{PACOTE_MOTOR}", extras = ["anthropic"], git = "{URL_MOTOR}?rev={TAG}" }},
    {{ name = "{PLUGIN}", git = "{URL_PLUGIN}" }},
    {{ name = "six", specifier = ">=1.10" }},
]
"""


def test_registro_ida_e_volta_preserva_extra_e_plugins(tmp_path: Path) -> None:
    (tmp_path / "uv-receipt.toml").write_text(RECIBO)
    reg = ler_registro(tmp_path)
    assert reg is not None
    assert comando_reinstalar(reg) == [
        "uv",
        "tool",
        "install",
        "--reinstall",
        f"{PACOTE_MOTOR}[anthropic] @ git+{URL_MOTOR}@{TAG}",
        "--with",
        f"{PLUGIN} @ git+{URL_PLUGIN}",
        "--with",
        "six>=1.10",
    ]


def test_ler_registro_fora_de_uv_tool(tmp_path: Path) -> None:
    assert ler_registro(tmp_path) is None


def test_fixar_soltos_usa_o_commit_instalado(tmp_path: Path) -> None:
    (tmp_path / "uv-receipt.toml").write_text(RECIBO)
    reg = ler_registro(tmp_path)
    assert reg is not None
    fixado = fixar_soltos(reg, {PLUGIN: "abc123", PACOTE_MOTOR: "zzz"})
    assert fixado.plugins[0] == Requisito(PLUGIN, git=URL_PLUGIN, ref="abc123")
    assert fixado.motor.ref == TAG


class DistFalsa:
    def __init__(self, direct_url: dict[str, Any] | None) -> None:
        self._texto = None if direct_url is None else json.dumps(direct_url)

    def read_text(self, nome: str) -> str | None:
        return self._texto


@pytest.mark.parametrize(
    ("direct_url", "esperado"),
    [
        (
            {
                "url": URL_PLUGIN,
                "vcs_info": {
                    "vcs": "git",
                    "requested_revision": TAG,
                    "commit_id": "abc123",
                },
            },
            Origem(TipoOrigem.GIT, url=URL_PLUGIN, ref=TAG, commit="abc123"),
        ),
        (
            {"url": URL_PLUGIN, "vcs_info": {"vcs": "git", "commit_id": "abc123"}},
            Origem(TipoOrigem.GIT, url=URL_PLUGIN, commit="abc123"),
        ),
        (None, Origem(TipoOrigem.INDICE)),
        ({"url": "file:///x", "dir_info": {}}, Origem(TipoOrigem.LOCAL)),
    ],
)
def test_origem_do_pacote(direct_url: dict[str, Any] | None, esperado: Origem) -> None:
    assert origem_do_pacote(DistFalsa(direct_url)) == esperado  # type: ignore[arg-type]


def _ponto(grupo: str, nome: str, pacote: str, versao: str) -> SimpleNamespace:
    dist = DistFalsa(None)
    dist.metadata = {"Name": pacote}  # type: ignore[attr-defined]
    dist.version = versao  # type: ignore[attr-defined]
    return SimpleNamespace(group=grupo, name=nome, dist=dist)


def test_plugins_instalados_marca_embutidos() -> None:
    todos = [
        _ponto(GrupoPlugin.PRS, "gh", "outro-pacote", "2.0"),
        _ponto(GrupoPlugin.PRS, "bb", PACOTE_MOTOR, "0.2.0"),
        _ponto(GrupoPlugin.ESQUEMAS, "x", PACOTE_MOTOR, "0.2.0"),
    ]
    achados = plugins_instalados(lambda g: [p for p in todos if p.group == g])  # type: ignore[misc]
    assert [(p.grupo, p.nome, p.origem.tipo) for p in achados] == [
        (GrupoPlugin.ESQUEMAS, "x", TipoOrigem.EMBUTIDO),
        (GrupoPlugin.PRS, "bb", TipoOrigem.EMBUTIDO),
        (GrupoPlugin.PRS, "gh", TipoOrigem.INDICE),
    ]
    assert achados[2].pacote == "outro-pacote"
    assert achados[2].versao == "2.0"
