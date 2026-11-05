"""Desfechos de uma execução de inscrição e os eventos que merecem notificação."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from motor.domain.types import VersionStatus


class Desfecho(StrEnum):
    APLICOU = "aplicou"
    NADA = "nada"
    BLOQUEADA = "bloqueada"
    PULADA = "pulada"
    ERRO = "erro"
    ENCERRADA = "encerrada"


class TipoVermelho(StrEnum):
    AMBIGUA = "ambigua"
    SEM_COMMITS = "sem_commits"
    SUMIDO = "sumido"
    CONFLITANTE = "conflitante"


class TipoEvento(StrEnum):
    APLICOU = "aplicou"
    BLOQUEOU = "bloqueou"
    NOVO_VERMELHO = "novo_vermelho"
    ERRO = "erro"
    ENCERRADA = "encerrada"


@dataclass(frozen=True)
class Resultado:
    desfecho: Desfecho
    vermelhos: frozenset[str] | None = None  # None = execução sem status
    chamados_aplicados: tuple[str, ...] = ()
    n_aplicados: int = 0
    commit_bloqueado: str = ""
    arquivos: tuple[str, ...] = ()
    culpados: tuple[str, ...] = ()
    mensagem: str = ""


@dataclass(frozen=True)
class UltimaExecucao:
    hora: datetime
    desfecho: Desfecho
    desfecho_aviso: Desfecho  # último desfecho que não foi PULADA
    vermelhos: frozenset[str]
    mensagem: str = ""


@dataclass(frozen=True)
class Evento:
    tipo: TipoEvento
    detalhe: str


def vermelhos_de(status: VersionStatus) -> frozenset[str]:
    def chaves(tipo: TipoVermelho, ids: list[str]) -> set[str]:
        return {f"{tipo}:{i}" for i in ids}

    return frozenset(
        chaves(TipoVermelho.AMBIGUA, status.tasks_ambiguas)
        | chaves(TipoVermelho.SEM_COMMITS, status.tasks_sem_commits)
        | chaves(TipoVermelho.SUMIDO, status.commits_sumidos)
        | chaves(TipoVermelho.CONFLITANTE, [c.hash_origem for c in status.conflitantes])
    )


def consolidar(
    anterior: UltimaExecucao | None, r: Resultado, hora: datetime
) -> UltimaExecucao:
    vermelhos = (
        r.vermelhos
        if r.vermelhos is not None
        else (anterior.vermelhos if anterior else frozenset())
    )
    aviso = (
        anterior.desfecho_aviso
        if r.desfecho == Desfecho.PULADA and anterior
        else r.desfecho
    )
    return UltimaExecucao(hora, r.desfecho, aviso, vermelhos, r.mensagem)


def eventos(anterior: UltimaExecucao | None, r: Resultado) -> list[Evento]:
    out: list[Evento] = []
    match r.desfecho:
        case Desfecho.APLICOU:
            out.append(
                Evento(
                    TipoEvento.APLICOU,
                    f"{r.n_aplicados} commits aplicados dos chamados "
                    + ", ".join(r.chamados_aplicados),
                )
            )
        case Desfecho.BLOQUEADA:
            out.append(
                Evento(
                    TipoEvento.BLOQUEOU,
                    f"Commit {r.commit_bloqueado} em conflito nos arquivos "
                    + ", ".join(r.arquivos)
                    + "; chamados culpados: "
                    + ", ".join(r.culpados),
                )
            )
        case Desfecho.ERRO if anterior is None or anterior.desfecho_aviso != (
            Desfecho.ERRO
        ):
            out.append(Evento(TipoEvento.ERRO, r.mensagem))
        case Desfecho.ENCERRADA:
            out.append(
                Evento(TipoEvento.ENCERRADA, "Versão liberada, inscrição removida")
            )
    if r.vermelhos is not None:
        novos = r.vermelhos - (anterior.vermelhos if anterior else frozenset())
        if novos:
            out.append(
                Evento(
                    TipoEvento.NOVO_VERMELHO,
                    "Novos itens vermelhos: " + ", ".join(sorted(novos)),
                )
            )
    return out
