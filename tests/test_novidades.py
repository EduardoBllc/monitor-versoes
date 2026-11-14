from __future__ import annotations

import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from motor import novidades
from motor.instalacao import (
    GIT,
    PACOTE_MOTOR,
    ArgGit,
    Origem,
    Registro,
    Requisito,
    TipoOrigem,
)
from motor.novidades import (
    ARQUIVO_CACHE,
    PREFIXO_TAG,
    REF_HEAD,
    SEM_PROMPT_GIT,
    SEM_PROMPT_SSH,
    SSH_PADRAO,
    TAMANHO_COMMIT_CURTO,
    TIMEOUT_GIT_S,
    VALIDADE,
    Cache,
    Novidade,
    VarGit,
    checar,
    env_git,
    gravar_cache,
    ler_cache,
    maior_tag,
    rodar_git,
    vencido,
)

URL_MOTOR = "https://github.com/EduardoBllc/monitor-versoes"
PLUGIN = "monitor-versoes-extra"
PLUGIN_METADADO = "Monitor_Versoes.Extra"  # mesmo pacote, grafia do METADATA
URL_PLUGIN = "https://github.com/EduardoBllc/monitor-versoes-extra"
COMMIT_ANTIGO = "a" * 40
COMMIT_NOVO = "b" * 40
COMANDO_MOTOR = f"{PACOTE_MOTOR} atualizar-motor"
AGORA = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _remoto(*, tags: tuple[str, ...] = (), head: str | None = None) -> str:
    linhas = [f"{head}\t{REF_HEAD}"] if head else []
    linhas += [f"{COMMIT_ANTIGO}\t{PREFIXO_TAG}{t}" for t in tags]
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
                    COMMIT_ANTIGO[:TAMANHO_COMMIT_CURTO],
                    COMMIT_NOVO[:TAMANHO_COMMIT_CURTO],
                    f"{PACOTE_MOTOR} atualizar-motor",
                ),
                Novidade(
                    PLUGIN,
                    COMMIT_ANTIGO[:TAMANHO_COMMIT_CURTO],
                    COMMIT_NOVO[:TAMANHO_COMMIT_CURTO],
                    f"{PACOTE_MOTOR} plugin atualizar {PLUGIN}",
                ),
            ),
        ),
        (
            _registro(None, plugin=True),
            {
                PACOTE_MOTOR: Origem(TipoOrigem.GIT, commit=COMMIT_NOVO),
                PLUGIN_METADADO: Origem(TipoOrigem.GIT, commit=COMMIT_ANTIGO),
            },
            _remoto(head=COMMIT_NOVO),
            (
                Novidade(
                    PLUGIN,
                    COMMIT_ANTIGO[:TAMANHO_COMMIT_CURTO],
                    COMMIT_NOVO[:TAMANHO_COMMIT_CURTO],
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
        (
            _registro(COMMIT_ANTIGO),
            {PACOTE_MOTOR: Origem(TipoOrigem.GIT, ref=COMMIT_ANTIGO)},
            _remoto(head=COMMIT_NOVO),
            (
                Novidade(
                    PACOTE_MOTOR,
                    COMMIT_ANTIGO[:TAMANHO_COMMIT_CURTO],
                    COMMIT_NOVO[:TAMANHO_COMMIT_CURTO],
                    f"{PACOTE_MOTOR} atualizar-motor",
                ),
            ),
        ),
        (
            _registro(COMMIT_NOVO),
            {PACOTE_MOTOR: Origem(TipoOrigem.GIT, ref=COMMIT_NOVO)},
            _remoto(head=COMMIT_NOVO),
            (),
        ),
        (
            _registro("main"),
            {},
            _remoto(head=COMMIT_NOVO, tags=("v0.2.0",)),
            (),
        ),
    ],
)
def test_checar(
    registro: Registro,
    instalados: Mapping[str, Origem],
    saida: str | None,
    esperado: tuple[Novidade, ...],
) -> None:
    assert checar(registro, instalados, _rodar_fixo(saida)) == esperado


@pytest.mark.parametrize(
    ("versao", "esperado"),
    [
        ("0.2.0", ()),
        ("0.1.0", (Novidade(PACOTE_MOTOR, "0.1.0", "0.2.0", COMANDO_MOTOR),)),
    ],
)
def test_checar_commit_fixado_com_tags_compara_versao(
    versao: str, esperado: tuple[Novidade, ...]
) -> None:
    instalados = {PACOTE_MOTOR: Origem(TipoOrigem.GIT, commit=COMMIT_NOVO)}
    saida = _remoto(head=COMMIT_NOVO, tags=("v0.2.0",))
    achadas = checar(
        _registro(COMMIT_NOVO), instalados, _rodar_fixo(saida), lambda _: versao
    )
    assert achadas == esperado


def test_git_roda_sem_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas: list[dict[str, Any]] = []

    def falso(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        chamadas.append(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", falso)
    monkeypatch.setattr(novidades, "_ssh_da_config", lambda: None)
    monkeypatch.delenv(VarGit.SSH_COMMAND, raising=False)
    assert rodar_git([GIT, ArgGit.LS_REMOTE, URL_MOTOR], {}) == "ok"
    env = chamadas[0]["env"]
    assert {k: env[k] for k in VarGit} == env_git({}, lambda: None)
    assert chamadas[0]["timeout"] == TIMEOUT_GIT_S


SSH_DO_AMBIENTE = "ssh -i ~/.ssh/chave"
SSH_DA_CONFIG = "C:/Windows/System32/OpenSSH/ssh.exe"


@pytest.mark.parametrize(
    ("ambiente", "config", "ssh"),
    [
        ({VarGit.SSH_COMMAND: SSH_DO_AMBIENTE}, SSH_DA_CONFIG, SSH_DO_AMBIENTE),
        ({}, SSH_DA_CONFIG, SSH_DA_CONFIG),
        ({}, None, SSH_PADRAO),
    ],
)
def test_git_usa_o_ssh_do_usuario_sem_prompt(
    ambiente: dict[str, str], config: str | None, ssh: str
) -> None:
    env = env_git(ambiente, lambda: config)
    assert env[VarGit.SSH_COMMAND] == f"{ssh} {SEM_PROMPT_SSH}"
    assert env[VarGit.TERMINAL_PROMPT] == SEM_PROMPT_GIT


@pytest.mark.parametrize(
    "erro", [subprocess.TimeoutExpired("git", TIMEOUT_GIT_S), FileNotFoundError()]
)
def test_git_com_falha_nao_levanta(
    monkeypatch: pytest.MonkeyPatch, erro: Exception
) -> None:
    def falso(*args: Any, **kwargs: Any) -> None:
        raise erro

    monkeypatch.setattr(subprocess, "run", falso)
    assert rodar_git([GIT], {}) is None


def test_cache_ida_e_volta_e_validade(tmp_path: Path) -> None:
    arquivo = tmp_path / "novidades.json"
    cache = Cache(AGORA, (Novidade("pacote", "1", "2", "comando"),))
    gravar_cache(arquivo, cache)
    assert ler_cache(arquivo) == cache

    assert vencido(None, AGORA)
    assert vencido(cache, AGORA + VALIDADE + timedelta(seconds=1))
    assert not vencido(cache, AGORA + VALIDADE - timedelta(hours=1))

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
    novidades.disparar_renovacao.cache_clear()
    novidades.disparar_renovacao(None)


def test_renovacao_que_falha_ainda_grava_cache_novo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def falha() -> None:
        raise OSError

    monkeypatch.setattr(novidades, "diretorio_cache", lambda: str(tmp_path))
    monkeypatch.setattr(novidades, "_checar_instalado", falha)
    novidades._renovar()
    cache = ler_cache(tmp_path / ARQUIVO_CACHE)
    assert cache is not None
    assert cache.novidades == ()
    assert not vencido(cache, datetime.now().astimezone())


def test_cache_vencido_dispara_uma_renovacao_por_vencimento(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filhos: list[list[str]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **_: filhos.append(cmd))
    novidades.disparar_renovacao.cache_clear()
    monkeypatch.setattr(novidades, "ler_registro", lambda: _registro(None))
    monkeypatch.setattr(novidades, "checagem_ligada", lambda: True)
    monkeypatch.setattr(novidades, "diretorio_cache", lambda: str(tmp_path))
    arquivo = tmp_path / ARQUIVO_CACHE
    gravar_cache(arquivo, Cache(AGORA - VALIDADE * 2, ()))

    # O diagnóstico lê o mesmo cache vencido duas vezes.
    novidades.novidades_do_cache()
    novidades.novidades_do_cache()
    assert len(filhos) == 1

    # O filho regravou o cache, que venceu de novo: o mesmo processo renova outra vez.
    gravar_cache(arquivo, Cache(AGORA - VALIDADE * 3, ()))
    novidades.novidades_do_cache()
    assert len(filhos) == 2
