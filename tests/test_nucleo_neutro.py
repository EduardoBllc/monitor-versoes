"""O núcleo não carrega a VendaBem: nem as premissas do esquema dela (nome da
principal, tipos de versão) nem o nome dela ou do rastreador que ela usa."""

from __future__ import annotations

import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_MOTOR = _RAIZ / "motor"
_TESTES = _RAIZ / "tests"
_VERSIONS = _MOTOR / "migracoes" / "versions"

_PREMISSAS = re.compile(r"master|VersionType|inferir_tipo|fechada|ajustada", re.I)
# As migrações recriam o check antigo no downgrade.
_EXCLUIDOS_PREMISSAS = (_VERSIONS,)

_NOMES = re.compile(r"tickio|vendabem", re.I)
# Precisam nomear o que saiu: o histórico de migrações (não se reescreve), os
# testes da migração que derruba as colunas, o dos argumentos recusados e este
# próprio teste.
_EXCLUIDOS_NOMES = (
    _VERSIONS,
    _TESTES / "test_migracoes_sqlite.py",
    _TESTES / "test_estado_postgres.py",
    _TESTES / "test_argumentos_removidos.py",
    _TESTES / "test_nucleo_neutro.py",
)
_ARQUIVOS_AVULSOS = (
    _RAIZ / "pyproject.toml",
    _RAIZ / "README.md",
    _RAIZ / ".env.development.example",
)


def _excluido(caminho: Path, excluidos: tuple[Path, ...]) -> bool:
    return any(caminho == e or e in caminho.parents for e in excluidos)


def _ocorrencias(
    arquivos: list[Path], padrao: re.Pattern[str], excluidos: tuple[Path, ...]
) -> list[str]:
    return [
        f"{caminho.relative_to(_RAIZ)}:{numero}: {linha.strip()}"
        for caminho in arquivos
        if not _excluido(caminho, excluidos)
        # replace: o build da web em motor/daemon/static traz binário (fonte do Monaco).
        for numero, linha in enumerate(
            caminho.read_text(errors="replace").splitlines(), start=1
        )
        if padrao.search(linha)
    ]


def _arquivos_de(raiz: Path) -> list[Path]:
    return sorted(
        p for p in raiz.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    )


def test_nucleo_nao_cita_premissas_do_esquema_vendabem():
    ocorrencias = _ocorrencias(
        sorted(_MOTOR.rglob("*.py")), _PREMISSAS, _EXCLUIDOS_PREMISSAS
    )

    assert ocorrencias == [], "\n".join(ocorrencias)


def test_nucleo_nao_cita_tickio_nem_vendabem():
    arquivos = [*_arquivos_de(_MOTOR), *_arquivos_de(_TESTES), *_ARQUIVOS_AVULSOS]

    ocorrencias = _ocorrencias(arquivos, _NOMES, _EXCLUIDOS_NOMES)

    assert ocorrencias == [], "\n".join(ocorrencias)


def test_excecoes_existem():
    """Exceção que deixou de existir é exceção esquecida: some da lista."""
    assert [e for e in _EXCLUIDOS_NOMES if not e.exists()] == []
