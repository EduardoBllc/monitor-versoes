"""Esquema, politica e nomes de branch e de tag ja resolvidos nas camadas
config > esquema > padrao do nucleo
(docs/decisoes/025-esquema-e-atribuicao-plugaveis.md)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from motor.atribuicoes import Exata
from motor.errors import ErroDeEntrada
from motor.esquemas.semver import Semver
from motor.ports import EsquemaVersao, PoliticaAtribuicao

#: Padroes do nucleo, a camada de baixo.
BRANCH_VERSAO_PADRAO = "{versao}"
PRINCIPAL_PADRAO = "main"
TAG_PADRAO = "{versao}"


def aplicar(template: str, versao: str) -> str:
    """`str.replace`, nunca `str.format`: o resto do template e literal, e uma
    chave como `{x}` nele nao pode virar erro nem campo."""
    return template.replace("{versao}", versao)


def extrair(template: str, nome: str, esquema: EsquemaVersao) -> str | None:
    """A versao cujo nome pelo `template` e `nome`, ou `None` se `nome` nao
    casa com o template ou o miolo nao e um numero que o esquema reconhece."""
    prefixo, _, sufixo = template.partition("{versao}")
    if (
        len(nome) <= len(prefixo) + len(sufixo)
        or not nome.startswith(prefixo)
        or not nome.endswith(sufixo)
    ):
        return None
    miolo = nome[len(prefixo) : len(nome) - len(sufixo)]
    try:
        return miolo if esquema.validar(miolo) == miolo else None
    except ErroDeEntrada:
        return None


@dataclass(frozen=True)
class Versionamento:
    """`tag_liberacao` e so a camada config da liberacao; as outras duas
    (metodo do esquema e tag homonima) o `Catalogo` decide."""

    esquema: EsquemaVersao
    politica: PoliticaAtribuicao
    piso: str | None = None
    branch_versao: str = BRANCH_VERSAO_PADRAO
    principal: str = PRINCIPAL_PADRAO
    tag_liberacao: str | None = None

    def branch(self, versao: str) -> str:
        return aplicar(self.branch_versao, versao)

    def versao_da_branch(self, nome: str) -> str | None:
        return extrair(self.branch_versao, nome, self.esquema)

    def tag(self, versao: str, template: str) -> str:
        return aplicar(template, versao)

    def versao_da_tag(self, nome: str, template: str) -> str | None:
        return extrair(template, nome, self.esquema)


#: Resolvido so por quem usa: esquema ou politica que nao carregam nao podem
#: derrubar `atualizar --abort`.
FonteVersionamento = Callable[[], Versionamento]


def versionamento_padrao() -> Versionamento:
    """Sem config nenhuma: `semver`, `exata`, `{versao}`, `main` e tag homonima."""
    return Versionamento(esquema=Semver(), politica=Exata())
