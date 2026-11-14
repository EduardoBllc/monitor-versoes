from __future__ import annotations

import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from motor import novidades
from motor.instalacao import (
    PACOTE_MOTOR,
    Origem,
    Registro,
    Requisito,
    TipoOrigem,
)
from motor.novidades import (
    Cache,
    Novidade,
    checar,
    gravar_cache,
    ler_cache,
    maior_tag,
    rodar_git,
    vencido,
)

URL_MOTOR = "https://github.com/EduardoBllc/monitor-versoes"
PLUGIN = "monitor-versoes-extra"
URL_PLUGIN = "https://github.com/EduardoBllc/monitor-versoes-extra"
COMMIT_ANTIGO = "a" * 40
COMMIT_NOVO = "b" * 40
AGORA = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _remoto(*, tags: tuple[str, ...] = (), head: str | None = None) -> str:
    linhas = [f"{head}\tHEAD"] if head else []
    linhas += [f"{COMMIT_ANTIGO}\trefs/tags/{t}" for t in tags]
    return "\n".join(linhas)


def _rodar_fixo(saida: str | None) -> Any:
    def rodar(args: list[str], env: Mapping[str, str]) -> str | None:
        return saida

    return rodar


def _registro(motor_ref: str | None, *, plugin: bool = False) -> Registro:
    motor = Requisito(PACOTE_MOTOR, git=URL_MOTOR, ref=motor_ref)
    plugins = (Requisito(PLUGIN, git=URL_PLUGIN),) if plugin else ()
    return Registro(motor, plugins)


def test_maior_tag_ordena_numericamente_e_ignora_lixo() -> None:
    saida = _remoto(tags=("v0.9.0", "v0.10.0", "v1.0.0-rc1", "latest"))
    assert maior_tag(saida) == "v0.10.0"
    assert maior_tag("") is None


@pytest.mark.parametrize(
    ("registro", "instalados", "saida", "esperado"),
    [
        (
            _registro("v0.2.0"),
            {},
            _remoto(tags=("v0.2.0", "v0.3.0")),
            (
                Novidade(
                    PACOTE_MOTOR,
                    "0.2.0",
                    "0.3.0",
                    f"{PACOTE_MOTOR} atualizar-motor",
                ),
            ),
        ),
        (
            _registro(None, plugin=True),
            {
                PACOTE_MOTOR: Origem(TipoOrigem.GIT, commit=COMMIT_ANTIGO),
                PLUGIN: Origem(TipoOrigem.GIT, commit=COMMIT_ANTIGO),
            },
            _remoto(head=COMMIT_NOVO),
            (
                Novidade(
                    PACOTE_MOTOR,
                    COMMIT_ANTIGO[:7],
                    COMMIT_NOVO[:7],
                    f"{PACOTE_MOTOR} atualizar-motor",
                ),
                Novidade(
                    PLUGIN,
                    COMMIT_ANTIGO[:7],
                    COMMIT_NOVO[:7],
                    f"{PACOTE_MOTOR} plugin atualizar {PLUGIN}",
                ),
            ),
        ),
        (_registro("v0.3.0"), {}, _remoto(tags=("v0.3.0",)), ()),
        (
            _registro(None),
            {PACOTE_MOTOR: Origem(TipoOrigem.GIT, commit=COMMIT_NOVO)},
            _remoto(head=COMMIT_NOVO),
            (),
        ),
        (_registro("v0.2.0"), {}, None, ()),
    ],
)
def test_checar(
    registro: Registro,
    instalados: Mapping[str, Origem],
    saida: str | None,
    esperado: tuple[Novidade, ...],
) -> None:
    assert checar(registro, instalados, _rodar_fixo(saida)) == esperado


def test_git_roda_sem_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas: list[dict[str, Any]] = []

    def falso(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        chamadas.append(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", falso)
    assert rodar_git(["git", "ls-remote", URL_MOTOR], {}) == "ok"
    env = chamadas[0]["env"]
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
    assert chamadas[0]["timeout"] == novidades.TIMEOUT_GIT_S == 10


@pytest.mark.parametrize(
    "erro", [subprocess.TimeoutExpired("git", 10), FileNotFoundError()]
)
def test_git_com_falha_nao_levanta(
    monkeypatch: pytest.MonkeyPatch, erro: Exception
) -> None:
    def falso(*args: Any, **kwargs: Any) -> None:
        raise erro

    monkeypatch.setattr(subprocess, "run", falso)
    assert rodar_git(["git"], {}) is None


def test_cache_ida_e_volta_e_validade(tmp_path: Path) -> None:
    arquivo = tmp_path / "novidades.json"
    cache = Cache(AGORA, (Novidade("pacote", "1", "2", "comando"),))
    gravar_cache(arquivo, cache)
    assert ler_cache(arquivo) == cache

    assert vencido(None, AGORA)
    assert vencido(cache, AGORA + timedelta(hours=24, seconds=1))
    assert not vencido(cache, AGORA + timedelta(hours=23))

    arquivo.write_text("{corrompido")
    assert ler_cache(arquivo) is None


def test_gravacao_atomica(tmp_path: Path) -> None:
    arquivo = tmp_path / "novidades.json"
    arquivo.write_text("antigo")
    gravar_cache(arquivo, Cache(AGORA, ()))
    assert ler_cache(arquivo) == Cache(AGORA, ())
    assert list(tmp_path.iterdir()) == [arquivo]


def test_disparar_renovacao_ignora_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    def falso(*args: Any, **kwargs: Any) -> None:
        raise OSError

    monkeypatch.setattr(subprocess, "Popen", falso)
    novidades.disparar_renovacao()
