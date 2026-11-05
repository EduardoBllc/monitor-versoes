"""Unico lugar que traduz refs do git em versoes: as que tem branch, as
liberadas e a data de cada liberacao
(docs/decisoes/025-esquema-e-atribuicao-plugaveis.md).

O adapter de git lista nomes sem filtro; quem sabe o que e versao e o esquema,
pelos templates ja resolvidos no `Versionamento`.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from functools import cached_property

from motor.errors import NaoEncontrado
from motor.ports import GitRepo
from motor.services.versionamento import TAG_PADRAO, Versionamento


@dataclass
class Catalogo:
    """Le as refs uma vez por instancia: monte depois do fetch, e um novo a
    cada operacao (o `criar` cria branch e o `atualizar` dele monta o seu)."""

    git: GitRepo
    versionamento: Versionamento

    @cached_property
    def _branches(self) -> list[str]:
        return self.git.listar_branches()

    @cached_property
    def _tags(self) -> list[str]:
        return self.git.listar_tags()

    def _versoes_das_tags(self, template: str) -> dict[str, str]:
        """Versao -> nome da tag, para as tags que casam com `template`."""
        v = self.versionamento
        achadas: dict[str, str] = {}
        for nome in self._tags:
            numero = v.versao_da_tag(nome, template)
            if numero is not None:
                achadas[numero] = nome
        return achadas

    def com_branch(self) -> list[str]:
        """Versoes que tem branch (local ou de rastreamento), pelo template."""
        v = self.versionamento
        numeros = {
            n for nome in self._branches if (n := v.versao_da_branch(nome)) is not None
        }
        return v.esquema.ordenar(list(numeros))

    @cached_property
    def _criterio(self) -> tuple[str, dict[str, str], dict[str, datetime.datetime]]:
        """A camada de liberacao que vale, config > esquema > padrao, com o que
        ela reconhece: `(camada, versao -> tag, versao -> data)`. So uma camada
        vale por vez; as de baixo nem sao consultadas."""
        v = self.versionamento
        if v.tag_liberacao is not None:
            return "config", self._versoes_das_tags(v.tag_liberacao), {}
        homonimas = self._versoes_das_tags(TAG_PADRAO)
        candidatas = v.esquema.ordenar(list({*self.com_branch(), *homonimas}))
        do_esquema = v.esquema.liberacoes(self.git, candidatas)
        if do_esquema is not None:
            return "esquema", {}, dict(do_esquema)
        return "padrao", homonimas, {}

    def liberadas(self) -> set[str]:
        """Versoes que o criterio da camada mais alta presente da por liberadas."""
        _, tags, datas = self._criterio
        return set(tags) | set(datas)

    def existentes(self) -> list[str]:
        """Com branch ou liberadas, em ordem crescente: o que o esquema recebe
        para escolher a base."""
        return self.versionamento.esquema.ordenar(
            list({*self.com_branch(), *self.liberadas()})
        )

    def data_liberacao(self, versao: str) -> datetime.datetime:
        """Data do repositorio, nunca do relogio: o commit apontado pela tag ou
        a que o esquema leu do git."""
        camada, tags, datas = self._criterio
        if camada == "esquema":
            if versao not in datas:
                raise NaoEncontrado(f"versao {versao} nao esta liberada")
            return datas[versao]
        if versao not in tags:
            raise NaoEncontrado(f"versao {versao} nao esta liberada")
        return self.git.commit_meta(
            self.git.resolve_ref(f"refs/tags/{tags[versao]}")
        ).commit_date

    def ref_liberada(self, versao: str) -> str:
        """A ref que representa a versao liberada: a tag nas camadas de tag, a
        branch da versao na camada do esquema (que nao tem tag)."""
        camada, _, _ = self._criterio
        if camada == "esquema":
            return self.versionamento.branch(versao)
        template = self.versionamento.tag_liberacao or TAG_PADRAO
        return f"refs/tags/{self.versionamento.tag(versao, template)}"
