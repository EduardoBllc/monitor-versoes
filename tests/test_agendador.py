from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from motor.agendador import (
    ARGUMENTOS_RODAR,
    ARQUIVO_PLIST,
    ARQUIVO_SERVICE,
    ARQUIVO_TIMER,
    CHAVE_ARGUMENTOS,
    CHAVE_INTERVALO,
    CHAVE_ROTULO,
    INTERVALO_LAUNCHD_S,
    ROTULO_LAUNCHD,
    Sistema,
    agendar,
    arquivos,
    desagendar,
    executavel_motor,
    instalado,
    rodar_comando_do_sistema,
    sistema_atual,
)
from motor.errors import BackendIndisponivel, ErroDeEntrada

EXE = "/opt/bin/motor"


class Registro:
    def __init__(self, falhar_em: str | None = None) -> None:
        self.comandos: list[list[str]] = []
        self.falhar_em = falhar_em

    def __call__(self, cmd: list[str]) -> None:
        self.comandos.append(cmd)
        if self.falhar_em and self.falhar_em in cmd:
            raise BackendIndisponivel("falhou")


def test_arquivos_linux_e_macos(tmp_path: Path) -> None:
    linux = arquivos(Sistema.LINUX, EXE, tmp_path)
    por_nome = {p.name: t for p, t in linux.items()}
    assert set(por_nome) == {ARQUIVO_SERVICE, ARQUIVO_TIMER}
    assert f"ExecStart={EXE} {' '.join(ARGUMENTOS_RODAR)}" in por_nome[ARQUIVO_SERVICE]
    assert "OnCalendar=minutely" in por_nome[ARQUIVO_TIMER]
    mac = arquivos(Sistema.MACOS, EXE, tmp_path)
    [(caminho, texto)] = mac.items()
    assert caminho.name == ARQUIVO_PLIST
    dados = plistlib.loads(texto.encode())
    assert dados[CHAVE_ROTULO] == ROTULO_LAUNCHD
    assert dados[CHAVE_ARGUMENTOS] == [EXE, *ARGUMENTOS_RODAR]
    assert dados[CHAVE_INTERVALO] == INTERVALO_LAUNCHD_S


def test_agendar_escreve_e_ativa(tmp_path: Path) -> None:
    r = Registro()
    agendar(Sistema.LINUX, tmp_path, EXE, r)
    assert instalado(Sistema.LINUX, tmp_path)
    assert [c[2] for c in r.comandos] == ["daemon-reload", "enable"]
    assert r.comandos[1][-1] == ARQUIVO_TIMER
    m = Registro(falhar_em="unload")
    agendar(Sistema.MACOS, tmp_path, EXE, m)
    assert m.comandos[0][1] == "unload"
    assert m.comandos[1][1] == "load"
    assert instalado(Sistema.MACOS, tmp_path)


def test_agendar_de_novo_reescreve(tmp_path: Path) -> None:
    agendar(Sistema.LINUX, tmp_path, EXE, Registro())
    agendar(Sistema.LINUX, tmp_path, "/outro/motor", Registro())
    [servico] = list(tmp_path.rglob(ARQUIVO_SERVICE))
    assert "/outro/motor" in servico.read_text()


@pytest.mark.parametrize("sistema", list(Sistema))
def test_desagendar_remove(tmp_path: Path, sistema: Sistema) -> None:
    agendar(sistema, tmp_path, EXE, Registro())
    r = Registro()
    desagendar(sistema, tmp_path, r)
    assert not instalado(sistema, tmp_path)
    assert r.comandos


@pytest.mark.parametrize(
    ("sistema", "palavra"),
    [(Sistema.LINUX, "disable"), (Sistema.MACOS, "unload")],
)
def test_desagendar_remove_mesmo_se_desativar_falha(
    tmp_path: Path, sistema: Sistema, palavra: str
) -> None:
    agendar(sistema, tmp_path, EXE, Registro())
    desagendar(sistema, tmp_path, Registro(falhar_em=palavra))
    assert not instalado(sistema, tmp_path)


def test_sistema_nao_suportado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(ErroDeEntrada):
        sistema_atual()


def test_motor_fora_do_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    with pytest.raises(ErroDeEntrada):
        executavel_motor()


def test_rodar_comando_traduz_erros(monkeypatch: pytest.MonkeyPatch) -> None:
    def levanta(exc: Exception) -> Callable[..., None]:
        def f(*_a: object, **_k: object) -> None:
            raise exc

        return f

    for exc in (OSError("x"), subprocess.CalledProcessError(1, "x")):
        monkeypatch.setattr(subprocess, "run", levanta(exc))
        with pytest.raises(BackendIndisponivel):
            rodar_comando_do_sistema(["x"])
