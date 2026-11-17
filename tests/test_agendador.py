from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from motor.agendador import (
    NOME_TAREFA_INSCRICOES,
    SCHTASKS,
    Acao,
    AcaoSchtasks,
    Sistema,
    caminhos,
    instalado,
    remover_agendador_antigo,
    rodar_comando_do_sistema,
    sistema_atual,
)
from motor.errors import BackendIndisponivel, ErroDeEntrada

SO_SEM_AGENDADOR = "sunos5"


MOTIVO_FALHA = "falhou"


class Registro:
    def __init__(self, falhar_em: str | None = None) -> None:
        self.comandos: list[list[str]] = []
        self.falhar_em = falhar_em

    def __call__(self, cmd: list[str]) -> None:
        self.comandos.append(cmd)
        if self.falhar_em and self.falhar_em in cmd:
            raise BackendIndisponivel(MOTIVO_FALHA)


def _instalar(sistema: Sistema, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", sistema.value)
    for caminho in caminhos(sistema, home):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.touch()


@pytest.mark.parametrize("sistema", [Sistema.LINUX, Sistema.MACOS])
def test_remover_agendador_antigo_instalado_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sistema: Sistema
) -> None:
    _instalar(sistema, tmp_path, monkeypatch)
    assert remover_agendador_antigo(tmp_path, Registro())
    assert not instalado(sistema, tmp_path)


@pytest.mark.parametrize(
    ("sistema", "acao"),
    [
        (Sistema.LINUX, Acao.DISABLE),
        (Sistema.LINUX, Acao.DAEMON_RELOAD),
        (Sistema.MACOS, Acao.UNLOAD),
    ],
)
def test_remover_agendador_antigo_remove_mesmo_se_o_sistema_falha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sistema: Sistema, acao: Acao
) -> None:
    _instalar(sistema, tmp_path, monkeypatch)
    assert remover_agendador_antigo(tmp_path, Registro(falhar_em=acao))
    assert not any(c.exists() for c in caminhos(sistema, tmp_path))


def test_remover_agendador_antigo_ausente_nao_chama_nada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", Sistema.LINUX.value)
    registro = Registro()
    assert not remover_agendador_antigo(tmp_path, registro)
    assert not registro.comandos


def test_remover_agendador_antigo_em_so_sem_agendador(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", SO_SEM_AGENDADOR)
    assert not remover_agendador_antigo(tmp_path, Registro())


def test_sistema_nao_suportado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", SO_SEM_AGENDADOR)
    with pytest.raises(ErroDeEntrada):
        sistema_atual()


@pytest.mark.parametrize("exc", [OSError("x"), subprocess.CalledProcessError(1, "x")])
def test_rodar_comando_traduz_erros(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    def levanta(*_a: object, **_k: object) -> None:
        raise exc

    monkeypatch.setattr(subprocess, "run", levanta)
    with pytest.raises(BackendIndisponivel):
        rodar_comando_do_sistema(["x"])


def test_remover_agendador_antigo_windows_apaga_a_tarefa_manual(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "platform", Sistema.WINDOWS.value)
    registro = Registro()
    assert remover_agendador_antigo(tmp_path, registro)
    assert [c[1] for c in registro.comandos] == [
        AcaoSchtasks.QUERY,
        AcaoSchtasks.END,
        AcaoSchtasks.DELETE,
    ]
    assert all(
        c[0] == SCHTASKS and NOME_TAREFA_INSCRICOES in c for c in registro.comandos
    )
    assert "timer antigo das inscrições removido" in capsys.readouterr().err


def test_remover_agendador_antigo_windows_sem_tarefa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", Sistema.WINDOWS.value)
    registro = Registro(falhar_em=AcaoSchtasks.QUERY)
    assert not remover_agendador_antigo(tmp_path, registro)
    assert len(registro.comandos) == 1
