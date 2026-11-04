"""ManualList: fallback sempre disponivel quando a API do Tickio nao responde.

Arquivo texto com um id de tarefa por linha; `#` comenta.
"""

from __future__ import annotations

from dataclasses import dataclass

from motor.domain.referencia import id_no_alfabeto
from motor.errors import ErroDeEntrada


@dataclass
class ManualList:
    caminho: str

    def fetch(self, versao: str, /) -> list[str]:
        try:
            with open(self.caminho, encoding="utf-8") as f:
                linhas = f.read().splitlines()
        except OSError as e:
            raise ErroDeEntrada(f"abrindo lista manual {self.caminho}: {e}") from e

        chamados: list[str] = []
        for bruta in linhas:
            linha = bruta.strip()
            if linha == "" or linha.startswith("#"):
                continue
            # ID opaco (`PAY-123`), mas no alfabeto default: espaco ou `/` na
            # linha e erro de digitacao, nao tarefa.
            if not id_no_alfabeto(linha):
                raise ErroDeEntrada(
                    f"linha invalida em {self.caminho}: {linha!r} "
                    "(esperado um id de tarefa: letras, digitos, _ e -)"
                )
            chamados.append(linha)
        return chamados
