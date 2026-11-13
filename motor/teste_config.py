"""Testa uma peça da config sobre o rascunho, num subprocesso (decisão 037)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import asdict

from motor.config import (
    AMBIENTE_PADRAO,
    SECAO_REPOS,
    VAR_XDG_CONFIG_HOME,
    ambiente_base,
    ambiente_central,
    aplicar_ambiente_central,
    caminho_config_global,
    carregar_config_global,
    repos_configurados,
)
from motor.config_edicao import Alteracao, rascunho
from motor.diagnostico import (
    PECA_DO_DIAGNOSTICO,
    Estado,
    Peca,
    PecaTestavel,
    Resultado,
    diagnosticar_peca,
    onde_das_credenciais,
    repo_existente,
)
from motor.errors import MotorError, formatar_com_notas

TIMEOUT_TESTE = 30
TEMPO_ESGOTADO = "tempo esgotado"


def testar(
    alteracoes: list[Alteracao],
    versao: str,
    peca: PecaTestavel,
    repo: str | None,
    *,
    ambiente: str = AMBIENTE_PADRAO,
) -> Resultado:
    """A linha do diagnóstico de `peca` com a config como ficaria se salva."""
    texto = rascunho(alteracoes, versao)
    if peca is PecaTestavel.REPO:
        repo_existente(repo, tomllib.loads(texto).get(SECAO_REPOS, {}))
    onde = onde_das_credenciais(caminho_config_global(), ambiente)
    comando = [sys.executable, "-P", "-m", __name__, peca, onde]
    if repo is not None:
        comando.append(repo)
    with tempfile.TemporaryDirectory() as temporario:
        arquivo = os.path.join(temporario, "monitor-versoes", "config.toml")
        os.mkdir(os.path.dirname(arquivo))
        with open(arquivo, "w", encoding="utf-8") as f:
            f.write(texto)
        try:
            # stderr descartado: traceback de plugin pode carregar o segredo digitado.
            saida = subprocess.run(
                comando,
                env=ambiente_base() | {VAR_XDG_CONFIG_HOME: temporario},
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                errors="replace",
                timeout=TIMEOUT_TESTE,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return _falha(peca, f"{TEMPO_ESGOTADO} ({TIMEOUT_TESTE} s)")
    try:
        # Só a última linha: um plugin pode ter escrito no stdout antes.
        dados = json.loads(saida.stdout.strip().rsplit("\n", 1)[-1])
        # Plugin cita a config lida, que no subprocesso é o arquivo temporário.
        real = caminho_config_global()
        return Resultado(
            Peca(dados["peca"]),
            Estado(dados["estado"]),
            dados["detalhe"].replace(arquivo, real),
            dados["correcao"].replace(arquivo, real),
        )
    except ValueError, KeyError, TypeError:
        return _falha(peca, "o teste terminou sem resultado legível")


def _falha(peca: PecaTestavel, detalhe: str) -> Resultado:
    return Resultado(PECA_DO_DIAGNOSTICO[peca], Estado.FALHA, detalhe)


def _main(argv: list[str]) -> None:
    nome_peca, onde, *resto = argv
    peca = PecaTestavel(nome_peca)
    repo = resto[0] if resto else None
    try:
        aplicar_ambiente_central(ambiente_central())
        resultado = diagnosticar_peca(
            peca,
            config_central=carregar_config_global,
            repos=repos_configurados,
            onde=onde,
            repo=repo,
        )
    except MotorError as e:
        resultado = _falha(peca, formatar_com_notas(e))
    print(json.dumps(asdict(resultado), default=lambda e: e.value))


if __name__ == "__main__":
    _main(sys.argv[1:])
