"""Descobre versão nova por `git ls-remote`, guarda o resultado num cache de 24 h."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from importlib.metadata import distribution
from pathlib import Path

from motor.config import checagem_ligada, diretorio_cache
from motor.errors import MotorError
from motor.instalacao import (
    PACOTE_MOTOR,
    SHA_COMPLETO,
    TAG_VERSAO,
    Origem,
    Registro,
    Requisito,
    ler_registro,
    normalizar,
    origem_do_pacote,
    plugins_instalados,
)

ARQUIVO_CACHE = "novidades.json"
VALIDADE = timedelta(hours=24)
TIMEOUT_GIT_S = 10
TAMANHO_COMMIT_CURTO = 7
PREFIXO_TAG = "refs/tags/"
REF_HEAD = "HEAD"
ENV_GIT = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_SSH_COMMAND": "ssh -o BatchMode=yes",
}
# Windows: constantes só existem lá.
_FLAGS_DESTACADO = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
    subprocess, "CREATE_NO_WINDOW", 0
)


class ChaveCache(StrEnum):
    CHECADO_EM = "checado_em"
    NOVIDADES = "novidades"
    PACOTE = "pacote"
    ATUAL = "atual"
    NOVA = "nova"
    COMANDO = "comando"


@dataclass(frozen=True)
class Novidade:
    pacote: str
    atual: str
    nova: str
    comando: str  # o que o usuário roda


@dataclass(frozen=True)
class Cache:
    checado_em: datetime
    novidades: tuple[Novidade, ...]


Rodar = Callable[[list[str], Mapping[str, str]], str | None]  # stdout; None em falha


def rodar_git(args: list[str], env: Mapping[str, str]) -> str | None:
    try:
        feito = subprocess.run(
            args,
            check=False,
            env={**os.environ, **ENV_GIT, **env},
            capture_output=True,
            text=True,
            timeout=TIMEOUT_GIT_S,
            stdin=subprocess.DEVNULL,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    return feito.stdout if feito.returncode == 0 else None


def _versao(tag: str) -> tuple[int, ...] | None:
    achada = TAG_VERSAO.fullmatch(tag)
    return tuple(int(n) for n in achada.groups()) if achada else None


def _tags(saida: str) -> list[str]:
    nomes = (
        linha.partition("\t")[2].removeprefix(PREFIXO_TAG)
        for linha in saida.splitlines()
        if linha.partition("\t")[2].startswith(PREFIXO_TAG)
    )
    return [n for n in nomes if _versao(n) is not None]


def maior_tag(saida_ls_remote: str) -> str | None:
    return max(_tags(saida_ls_remote), key=lambda t: _versao(t) or (), default=None)


def _commits_da_tag(saida: str, tag: str) -> set[str]:
    # Tag anotada aparece também como `tag^{}`, com o commit de fato.
    nomes = {f"{PREFIXO_TAG}{tag}", f"{PREFIXO_TAG}{tag}^{{}}"}
    return {
        c
        for c, _, ref in (ln.partition("\t") for ln in saida.splitlines())
        if ref in nomes
    }


def _head(saida: str) -> str | None:
    for linha in saida.splitlines():
        commit, _, ref = linha.partition("\t")
        if ref == REF_HEAD:
            return commit
    return None


def _de_tag_fixa(r: Requisito, ref: str, saida: str, comando: str) -> Novidade | None:
    nova = maior_tag(saida)
    if nova is None or (_versao(nova) or ()) <= (_versao(ref) or ()):
        return None
    return Novidade(r.nome, ref[1:], nova[1:], comando)


def _de_commit(
    r: Requisito, instalado: str, saida: str, comando: str
) -> Novidade | None:
    curto = TAMANHO_COMMIT_CURTO
    nova = maior_tag(saida)
    if nova is not None:
        if instalado in _commits_da_tag(saida, nova):
            return None
        return Novidade(r.nome, instalado[:curto], nova[1:], comando)
    remoto = _head(saida)
    if remoto is None or remoto == instalado:
        return None
    return Novidade(r.nome, instalado[:curto], remoto[:curto], comando)


def ref_mais_nova(saida: str) -> str | None:
    """Tag `v*` mais nova; sem tags, o commit do `HEAD` remoto."""
    return maior_tag(saida) or _head(saida)


def novidade(
    r: Requisito, instalados: Mapping[str, Origem], saida: str
) -> Novidade | None:
    comando = (
        f"{PACOTE_MOTOR} atualizar-motor"
        if r.nome == PACOTE_MOTOR
        else f"{PACOTE_MOTOR} plugin atualizar {r.nome}"
    )
    if r.ref is not None and _versao(r.ref) is not None:
        return _de_tag_fixa(r, r.ref, saida, comando)
    if r.ref is not None and not SHA_COMPLETO.fullmatch(r.ref):
        return None  # branch: não há o que comparar
    origem = next(
        (o for nome, o in instalados.items() if normalizar(nome) == normalizar(r.nome)),
        None,
    )
    instalado = (origem.commit if origem else None) or r.ref
    return _de_commit(r, instalado, saida, comando) if instalado else None


def ls_remote(url: str, rodar: Rodar = rodar_git) -> str | None:
    return rodar(["git", "ls-remote", url, REF_HEAD, f"{PREFIXO_TAG}*"], {})


def checar(
    reg: Registro, instalados: Mapping[str, Origem], rodar: Rodar = rodar_git
) -> tuple[Novidade, ...]:
    achadas = []
    for r in (reg.motor, *reg.plugins):
        if r.git is None:
            continue
        saida = ls_remote(r.git, rodar)
        if saida is None:
            continue
        if (achada := novidade(r, instalados, saida)) is not None:
            achadas.append(achada)
    return tuple(achadas)


def ler_cache(arquivo: Path) -> Cache | None:
    try:
        dados = json.loads(arquivo.read_text())
        return Cache(
            datetime.fromisoformat(dados[ChaveCache.CHECADO_EM]),
            tuple(
                Novidade(
                    n[ChaveCache.PACOTE],
                    n[ChaveCache.ATUAL],
                    n[ChaveCache.NOVA],
                    n[ChaveCache.COMANDO],
                )
                for n in dados[ChaveCache.NOVIDADES]
            ),
        )
    except OSError, ValueError, KeyError, TypeError:
        return None


def gravar_cache(arquivo: Path, cache: Cache) -> None:
    dados = {
        ChaveCache.CHECADO_EM: cache.checado_em.isoformat(),
        ChaveCache.NOVIDADES: [
            {
                ChaveCache.PACOTE: n.pacote,
                ChaveCache.ATUAL: n.atual,
                ChaveCache.NOVA: n.nova,
                ChaveCache.COMANDO: n.comando,
            }
            for n in cache.novidades
        ],
    }
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    # Temporário no mesmo diretório: `os.replace` só é atômico dentro do volume.
    fd, temporario = tempfile.mkstemp(dir=arquivo.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(dados, f)
        os.replace(temporario, arquivo)
    except BaseException:
        Path(temporario).unlink(missing_ok=True)
        raise


def vencido(cache: Cache | None, agora: datetime) -> bool:
    return cache is None or agora - cache.checado_em > VALIDADE


def disparar_renovacao() -> None:
    comando = [sys.executable, "-P", "-m", "motor.novidades"]
    nada = subprocess.DEVNULL
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                comando,
                stdin=nada,
                stdout=nada,
                stderr=nada,
                creationflags=_FLAGS_DESTACADO,
            )
        else:
            subprocess.Popen(
                comando, stdin=nada, stdout=nada, stderr=nada, start_new_session=True
            )
    except OSError:
        pass


def novidades_do_cache() -> Cache | None:
    """O cache de versões; `None` com a checagem desligada ou fora de um `uv tool`.
    Cache vencido dispara a renovação em segundo plano, sem esperar."""
    if ler_registro() is None or not checagem_ligada():
        return None
    cache = ler_cache(Path(diretorio_cache()) / ARQUIVO_CACHE)
    if vencido(cache, datetime.now(UTC)):
        disparar_renovacao()
    return cache


def novidades_para_exibir() -> tuple[Novidade, ...]:
    """Para TUI e web: config inválida vale "nada novo" (o diagnóstico a aponta)."""
    try:
        cache = novidades_do_cache()
    except MotorError:
        return ()
    return cache.novidades if cache else ()


def linha_aviso(n: Novidade) -> str:
    prefixo = "" if n.pacote == PACOTE_MOTOR else f"{n.pacote}: "
    return f"{prefixo}Versão {n.nova} disponível (você tem {n.atual}): {n.comando}"


def _checar_instalado() -> tuple[Novidade, ...]:
    reg = ler_registro()
    if reg is None:
        return ()
    instalados = {p.pacote: p.origem for p in plugins_instalados()}
    instalados[PACOTE_MOTOR] = origem_do_pacote(distribution(PACOTE_MOTOR))
    return checar(reg, instalados)


def _renovar() -> None:
    try:
        achadas = _checar_instalado()
    except Exception:
        # Sem cache novo, todo comando dispararia outra renovação.
        achadas = ()
    gravar_cache(
        Path(diretorio_cache()) / ARQUIVO_CACHE,
        Cache(datetime.now().astimezone(), achadas),
    )


if __name__ == "__main__":
    _renovar()
