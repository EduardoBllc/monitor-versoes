"""TickioRest: fonte de tarefas do Tickio.

Autentica por credencial a cada processo em vez de usar um access token colado
no .env — o CLI vive segundos, entao re-autenticar sai mais barato que refazer
o .env toda vez que o JWT expira. O refresh token nao e usado pelo mesmo
motivo: ele existe para processo longo que nao quer reter credencial.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

import httpx

from motor.errors import MotorError

_ROTA_TOKEN = "/api/v1/ws/token/"
_ROTA_CHAMADOS = "/api/v1/ws/versoes/chamados/"


@dataclass
class TickioRest:
    base_url: str
    usuario: str
    # repr=False na senha e no JWT: com --debug o logging sobe para DEBUG, e um
    # dump do dataclass (deps, repr de excecao) imprimiria credencial em claro.
    senha: str = field(repr=False)
    sistema_id: int
    client: httpx.Client | None = None
    _access: str = field(default="", init=False, repr=False)

    def fetch(self, versao: str) -> list[str]:
        # Cobrado no uso, nao na construcao: o CLI monta a fonte de tarefas para
        # todo comando, mas `atualizar --abort` e `reconstruir-estado` nunca
        # buscam nada — e sao justamente os comandos de recuperacao, que nao
        # podem travar por credencial de um servico que nao vao consultar. Sem
        # esta checagem, base_url vazia sai como reclamacao de protocolo do
        # httpx, que nao nomeia a variavel que falta.
        if faltando := [
            nome
            for nome, valor in (
                ("TICKIO_BASE_URL", self.base_url),
                ("TICKIO_USER", self.usuario),
                ("TICKIO_PASSWORD", self.senha),
            )
            if not valor
        ]:
            raise MotorError(f"faltando no .env: {', '.join(faltando)}")

        # Fecha so o que criamos: cliente injetado pertence a quem injetou.
        with contextlib.ExitStack() as pilha:
            cliente = self.client
            if cliente is None:
                cliente = pilha.enter_context(httpx.Client())
            token = self._autenticar(cliente)

            try:
                resp = cliente.get(
                    f"{self.base_url}{_ROTA_CHAMADOS}",
                    params={"sistema": self.sistema_id, "versao": versao},
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as e:
                raise MotorError(
                    f"buscando chamados da versao {versao} no Tickio: {e}"
                ) from e

            if resp.status_code != 200:
                raise MotorError(
                    f"Tickio respondeu {resp.status_code} ao listar a versao {versao}: "
                    f"{resp.text}"
                )

            try:
                corpo = resp.json()
            except ValueError as e:
                raise MotorError(f"decodificando resposta do Tickio: {e}") from e

            return _extrair_chamados(corpo)

    def _autenticar(self, cliente: httpx.Client) -> str:
        if self._access:
            return self._access
        try:
            resp = cliente.post(
                f"{self.base_url}{_ROTA_TOKEN}",
                json={"username": self.usuario, "password": self.senha},
            )
        except httpx.HTTPError as e:
            raise MotorError(f"autenticando no Tickio: {e}") from e

        if resp.status_code != 200:
            raise MotorError(
                f"autenticando no Tickio: respondeu {resp.status_code}: {resp.text}"
            )

        try:
            corpo = resp.json()
        except ValueError as e:
            raise MotorError(f"autenticando no Tickio: decodificando resposta: {e}") from e

        # str() e não cast(): o corpo vem de JSON de terceiro, e um `access`
        # numerico ou nulo entraria no header Authorization como o repr do
        # objeto. A checagem de vazio abaixo pega os dois casos.
        access = str((corpo or {}).get("access", "") or "")
        if not access:
            raise MotorError("autenticando no Tickio: resposta sem campo 'access'")
        self._access = access
        return access


def _extrair_chamados(corpo: object) -> list[str]:
    """Le a lista de chamados do corpo da resposta.

    O Tickio responde um envelope com `chamados`; as formas antigas continuam
    aceitas para compatibilidade.

    Uma forma nao reconhecida nao cai para lista vazia: isso pareceria "nenhum
    chamado nesta versao", indistinguivel de um resultado vazio legitimo.
    """
    if isinstance(corpo, dict):
        if "chamados" in corpo:
            itens = corpo["chamados"]
        elif "results" in corpo:
            itens = corpo["results"]
        else:
            raise MotorError(f"resposta do Tickio em formato inesperado: {corpo!r}")
    else:
        itens = corpo

    if not isinstance(itens, list):
        raise MotorError(f"resposta do Tickio em formato inesperado: {type(corpo)}")

    chamados: list[str] = []
    for item in itens:
        if isinstance(item, dict):
            valor = item.get("chamado") or item.get("numero")
        else:
            valor = item
        if valor is None:
            raise MotorError(f"item sem numero de chamado na resposta do Tickio: {item!r}")
        chamados.append(str(valor))
    return chamados
