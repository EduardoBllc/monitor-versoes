"""O que está instalado: plugins (entry points) e o registro do `uv tool`."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from importlib.metadata import Distribution, EntryPoint, entry_points
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from motor.config_edicao import GrupoPlugin

PACOTE_MOTOR = "monitor-versoes"
ARQUIVO_REGISTRO = "uv-receipt.toml"
ARQUIVO_DIRECT_URL = "direct_url.json"
PREFIXO_GIT = "git+"
PARAMETRO_REV = "rev"
PARAMETRO_SUBDIRETORIO = "subdirectory"
# Ref que não muda sozinha: tag de versão ou SHA completo; o resto é branch.
TAG_VERSAO = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
_REF_FIXA = re.compile(f"{TAG_VERSAO.pattern}|[0-9a-f]{{40}}")


class TipoOrigem(StrEnum):
    GIT = "git"
    INDICE = "índice"
    EMBUTIDO = "embutido"
    LOCAL = "local"


class ChaveRegistro(StrEnum):
    TOOL = "tool"
    PYTHON = "python"
    REQUISITOS = "requirements"
    NOME = "name"
    GIT = "git"
    EXTRAS = "extras"
    ESPECIFICADOR = "specifier"


class ChaveDirectUrl(StrEnum):
    URL = "url"
    VCS = "vcs_info"
    DIR = "dir_info"
    REVISAO = "requested_revision"
    COMMIT = "commit_id"


@dataclass(frozen=True)
class Origem:
    tipo: TipoOrigem
    url: str | None = None  # git: sem o "git+"
    ref: str | None = None  # tag ou commit pedido; None = solta (segue a branch)
    commit: str | None = None  # commit instalado (direct_url.json)


@dataclass(frozen=True)
class PluginInstalado:
    grupo: str
    nome: str
    pacote: str
    versao: str
    origem: Origem


@dataclass(frozen=True)
class Requisito:
    nome: str
    git: str | None = None
    ref: str | None = None
    extras: tuple[str, ...] = ()
    especificador: str | None = None
    subdiretorio: str | None = None


@dataclass(frozen=True)
class Registro:
    motor: Requisito
    plugins: tuple[Requisito, ...]
    python: str | None = None


def _pontos_do_grupo(grupo: str) -> Iterable[EntryPoint]:
    return entry_points(group=grupo)


def origem_do_pacote(dist: Distribution) -> Origem:
    bruto = dist.read_text(ARQUIVO_DIRECT_URL)
    if bruto is None:
        return Origem(TipoOrigem.INDICE)
    dados = json.loads(bruto)
    vcs = dados.get(ChaveDirectUrl.VCS)
    if vcs is not None:
        return Origem(
            TipoOrigem.GIT,
            url=dados.get(ChaveDirectUrl.URL),
            ref=vcs.get(ChaveDirectUrl.REVISAO),
            commit=vcs.get(ChaveDirectUrl.COMMIT),
        )
    if ChaveDirectUrl.DIR in dados:
        return Origem(TipoOrigem.LOCAL)
    return Origem(TipoOrigem.INDICE)


def plugins_instalados(
    pontos: Callable[[str], Iterable[EntryPoint]] = _pontos_do_grupo,
) -> list[PluginInstalado]:
    achados = []
    for grupo in GrupoPlugin:
        for ep in pontos(grupo):
            assert ep.dist is not None
            pacote = ep.dist.metadata["Name"]
            origem = (
                Origem(TipoOrigem.EMBUTIDO)
                if pacote == PACOTE_MOTOR
                else origem_do_pacote(ep.dist)
            )
            achados.append(
                PluginInstalado(grupo, ep.name, pacote, ep.dist.version, origem)
            )
    return sorted(achados, key=lambda p: (p.grupo, p.nome))


def _requisito(linha: Mapping[str, object]) -> Requisito:
    bruto = linha.get(ChaveRegistro.GIT)
    git = ref = subdiretorio = None
    if isinstance(bruto, str):
        partes = urlsplit(bruto)
        resto = []
        for chave, valor in parse_qsl(partes.query):
            if chave == PARAMETRO_REV:
                ref = valor
            elif chave == PARAMETRO_SUBDIRETORIO:
                subdiretorio = valor
            else:
                resto.append((chave, valor))
        git = partes._replace(query=urlencode(resto)).geturl()
    espec = linha.get(ChaveRegistro.ESPECIFICADOR)
    extras = linha.get(ChaveRegistro.EXTRAS) or ()
    return Requisito(
        nome=str(linha[ChaveRegistro.NOME]),
        git=git,
        ref=ref,
        extras=tuple(extras),  # type: ignore[arg-type]
        especificador=str(espec) if espec is not None else None,
        subdiretorio=subdiretorio,
    )


def ler_registro(prefixo: Path = Path(sys.prefix)) -> Registro | None:
    arquivo = prefixo / ARQUIVO_REGISTRO
    if not arquivo.is_file():
        return None
    dados = tomllib.loads(arquivo.read_text())
    linhas = dados[ChaveRegistro.TOOL][ChaveRegistro.REQUISITOS]
    todos = [_requisito(linha) for linha in linhas]
    motor = next((r for r in todos if r.nome == PACOTE_MOTOR), None)
    if motor is None:
        return None
    python = dados[ChaveRegistro.TOOL].get(ChaveRegistro.PYTHON)
    return Registro(motor, tuple(r for r in todos if r is not motor), python)


def fixar_soltos(reg: Registro, commits: Mapping[str, str]) -> Registro:
    def fixar(r: Requisito) -> Requisito:
        if r.git is None or r.nome not in commits:
            return r
        if r.ref is not None and _REF_FIXA.fullmatch(r.ref):
            return r
        return replace(r, ref=commits[r.nome])

    return replace(
        reg, motor=fixar(reg.motor), plugins=tuple(fixar(p) for p in reg.plugins)
    )


def _escrever(r: Requisito) -> str:
    extras = f"[{','.join(r.extras)}]" if r.extras else ""
    if r.git is not None:
        ref = f"@{r.ref}" if r.ref else ""
        sub = f"#{PARAMETRO_SUBDIRETORIO}={r.subdiretorio}" if r.subdiretorio else ""
        return f"{r.nome}{extras} @ {PREFIXO_GIT}{r.git}{ref}{sub}"
    return f"{r.nome}{extras}{r.especificador or ''}"


def comando_reinstalar(reg: Registro) -> list[str]:
    comando = ["uv", "tool", "install", "--reinstall"]
    if reg.python:
        comando += ["--python", reg.python]
    comando.append(_escrever(reg.motor))
    for plugin in reg.plugins:
        comando += ["--with", _escrever(plugin)]
    return comando
