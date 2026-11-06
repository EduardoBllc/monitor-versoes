"""Operações longas do daemon: uma thread por repo, progresso amostrado."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from motor.daemon.erros import ErroApi, RepoOcupado, erro_api
from motor.domain.types import VersionStatus
from motor.engine.atualizar import AtualizarResult
from motor.progresso import Progresso, RelatorProgresso


class Operacao(StrEnum):
    VERIFICAR = "verificar"
    PREVIA = "previa"
    ATUALIZAR = "atualizar"
    CONTINUAR = "continuar"
    ABORTAR = "abortar"
    CRIAR = "criar"


class EstadoExecucao(StrEnum):
    RODANDO = "rodando"
    CONCLUIDA = "concluida"
    FALHOU = "falhou"


@dataclass
class Execucao:
    id: str
    repo: str
    versao: str
    operacao: Operacao
    estado: EstadoExecucao
    progresso: Progresso | None = None
    resultado: VersionStatus | AtualizarResult | None = None
    erro: ErroApi | None = None


Alvo = Callable[[RelatorProgresso], VersionStatus | AtualizarResult | None]


class Execucoes:
    def __init__(self) -> None:
        # protege só o dicionário (checar e registrar atômicos), nunca a operação
        self._lock = threading.Lock()
        self._por_repo: dict[str, Execucao] = {}
        self._threads: dict[str, threading.Thread] = {}

    def iniciar(
        self, repo: str, versao: str, operacao: Operacao, alvo: Alvo
    ) -> Execucao:
        execucao = Execucao(
            uuid.uuid4().hex, repo, versao, operacao, EstadoExecucao.RODANDO
        )
        thread = threading.Thread(
            target=self._rodar, args=(execucao, alvo), daemon=True
        )
        with self._lock:
            atual = self._por_repo.get(repo)
            if atual is not None and atual.estado is EstadoExecucao.RODANDO:
                raise RepoOcupado(repo)
            self._por_repo[repo] = execucao
            self._threads[repo] = thread
        thread.start()
        return execucao

    def atual(self, repo: str) -> Execucao | None:
        return self._por_repo.get(repo)

    def aguardar(self, repo: str, timeout: float) -> bool:
        """Espera a thread do repo terminar; usado pelos testes."""
        thread = self._threads.get(repo)
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    @staticmethod
    def _rodar(execucao: Execucao, alvo: Alvo) -> None:
        # last-writer-wins sem lock, como SlotProgresso
        def relatar(progresso: Progresso) -> None:
            execucao.progresso = progresso

        try:
            execucao.resultado = alvo(relatar)
            execucao.estado = EstadoExecucao.CONCLUIDA
        except Exception as e:
            execucao.erro = erro_api(e)[1]
            execucao.estado = EstadoExecucao.FALHOU
