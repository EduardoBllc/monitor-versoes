"""ManualList: fallback sempre disponivel quando a API do Tickio nao responde.

Arquivo texto com um numero de chamado por linha; `#` comenta.
"""

from __future__ import annotations

from dataclasses import dataclass

from motor.errors import MotorError


@dataclass
class ManualList:
    caminho: str

    def fetch(self, versao: str) -> list[str]:
        try:
            with open(self.caminho, encoding="utf-8") as f:
                linhas = f.read().splitlines()
        except OSError as e:
            raise MotorError(f"abrindo lista manual {self.caminho}: {e}") from e

        chamados: list[str] = []
        for linha in linhas:
            linha = linha.strip()
            if linha == "" or linha.startswith("#"):
                continue
            if not linha.isdigit():
                raise MotorError(
                    f"linha invalida em {self.caminho}: {linha!r} "
                    "(esperado so o numero do chamado)"
                )
            chamados.append(linha)
        return chamados
