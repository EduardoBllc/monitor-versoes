"""Imprime o OpenAPI do daemon em JSON; o tooling do front gera os tipos a partir dele."""

import json
from pathlib import Path

from motor.daemon.app import PASTA_ESTATICOS, PORTA_PADRAO, criar_app
from motor.operacoes import Runners
from motor.progresso import RelatorProgresso


def _nunca_chamada(relatar: RelatorProgresso) -> Runners:
    raise NotImplementedError


if __name__ == "__main__":
    app = criar_app(
        _nunca_chamada,
        porta=PORTA_PADRAO,
        estaticos=PASTA_ESTATICOS,
        inscricoes_em=Path("inscricoes.json"),
    )
    print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))
