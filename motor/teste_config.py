"""Testa uma peça da config sobre o rascunho, num subprocesso (decisão 037).

O subprocesso lê o rascunho de um `XDG_CONFIG_HOME` temporário e aplica o
`[ambiente]` dele; o processo que chama nunca vê o ambiente do rascunho.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict

from motor.config import (
    TABELA_AMBIENTE,
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
)
from motor.errors import MotorError, formatar_com_notas

TIMEOUT_TESTE = 30
TEMPO_ESGOTADO = "tempo esgotado"


def testar(
    alteracoes: list[Alteracao], versao: str, peca: PecaTestavel, repo: str | None
) -> Resultado:
    """A linha do diagnóstico de `peca` com a config como ficaria se salva."""
    texto = rascunho(alteracoes, versao)
    comando = [sys.executable, "-m", __name__, peca, caminho_config_global()]
    if repo is not None:
        comando.append(repo)
    with tempfile.TemporaryDirectory() as temporario:
        arquivo = os.path.join(temporario, "monitor-versoes", "config.toml")
        os.mkdir(os.path.dirname(arquivo))
        with open(arquivo, "w") as f:
            f.write(texto)
        try:
            saida = subprocess.run(
                comando,
                env=ambiente_base() | {VAR_XDG_CONFIG_HOME: temporario},
                capture_output=True,
                text=True,
                timeout=TIMEOUT_TESTE,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return _falha(peca, f"{TEMPO_ESGOTADO} ({TIMEOUT_TESTE} s)")
    # O stderr fica de fora: traceback de plugin pode carregar o segredo digitado.
    try:
        # Só a última linha: um plugin pode ter escrito no stdout antes.
        dados = json.loads(saida.stdout.strip().rsplit("\n", 1)[-1])
        return Resultado(
            Peca(dados["peca"]),
            Estado(dados["estado"]),
            dados["detalhe"],
            dados["correcao"],
        )
    except ValueError, KeyError, TypeError:
        return _falha(peca, "o teste terminou sem resultado legível")


def _falha(peca: PecaTestavel, detalhe: str) -> Resultado:
    return Resultado(PECA_DO_DIAGNOSTICO[peca], Estado.FALHA, detalhe)


def _main(argv: list[str]) -> None:
    nome_peca, config_real, *resto = argv
    peca = PecaTestavel(nome_peca)
    onde = f"[{TABELA_AMBIENTE}] de {config_real}"
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
