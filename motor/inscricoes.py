"""Arquivo local de inscrições, registro de execuções e o laço do `rodar`."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from motor.config import diretorio_dados
from motor.domain.inscricao import (
    Desfecho,
    Resultado,
    TipoEvento,
    UltimaExecucao,
    consolidar,
    eventos,
)
from motor.errors import ErroDeEntrada, MotorError, RespostaInvalida
from motor.ports import Notificador

log = logging.getLogger(__name__)

INTERVALO_PADRAO = "30m"
ARQUIVO_INSCRICOES = "inscricoes.json"
SEM_PROCESSO = -1
TEMPO_ESGOTADO = -2
# Folga para o pior `atualizar`; sem limite, um filho travado prende o oneshot e para todas.
LIMITE_EXECUCAO_S = 60 * 60
SEGUNDOS_POR_MINUTO = 60
MINUTOS_POR_HORA = 60
PREFIXO_TITULO = "monitor-versoes"
MENSAGEM_SEM_RESULTADO = "execução terminou com código {codigo} sem gravar resultado"
MENSAGEM_TEMPO_ESGOTADO = "execução excedeu {limite}s e foi interrompida"
# Antes de #143 a inscrição guardava o caminho do clone, não o nome do repo.
CAMPO_CLONE_ANTIGO = "clone"
AVISO_INSCRICAO_ANTIGA = (
    "aviso: inscrição antiga de {clone} {versao} descartada; reinscreva com "
    "`motor inscricao adicionar {versao} --repo <nome>`"
)
_PADRAO_INTERVALO = re.compile(r"([1-9]\d*)([mh])")


class UnidadeIntervalo(StrEnum):
    MINUTOS = "m"
    HORAS = "h"


class Campo(StrEnum):
    REPO = "repo"
    VERSAO = "versao"
    INTERVALO_S = "intervalo_s"
    ULTIMA = "ultima"
    HORA = "hora"
    DESFECHO = "desfecho"
    DESFECHO_AVISO = "desfecho_aviso"
    VERMELHOS = "vermelhos"
    MENSAGEM = "mensagem"


class RotuloEvento(StrEnum):
    APLICOU = "Aplicou"
    BLOQUEOU = "Bloqueou"
    NOVO_VERMELHO = "Atenção"
    ERRO = "Erro"
    ENCERRADA = "Encerrada"


_ROTULOS = {TipoEvento(r.name.lower()): r for r in RotuloEvento}


@dataclass(frozen=True)
class Inscricao:
    repo: str
    versao: str
    intervalo: timedelta
    ultima: UltimaExecucao | None = None


def parse_intervalo(texto: str) -> timedelta:
    m = _PADRAO_INTERVALO.fullmatch(texto)
    if m is None:
        raise ErroDeEntrada(
            f"intervalo inválido: {texto!r} (esperado Nm ou Nh, N >= 1)"
        )
    n = int(m.group(1))
    if m.group(2) == UnidadeIntervalo.MINUTOS:
        return timedelta(minutes=n)
    return timedelta(hours=n)


def formatar_intervalo(intervalo: timedelta) -> str:
    minutos = int(intervalo.total_seconds()) // SEGUNDOS_POR_MINUTO
    if minutos % MINUTOS_POR_HORA == 0:
        return f"{minutos // MINUTOS_POR_HORA}{UnidadeIntervalo.HORAS}"
    return f"{minutos}{UnidadeIntervalo.MINUTOS}"


def caminho_arquivo() -> Path:
    return Path(diretorio_dados()) / ARQUIVO_INSCRICOES


def _ultima_para_json(u: UltimaExecucao | None) -> dict[str, Any] | None:
    if u is None:
        return None
    return {
        Campo.HORA: u.hora.isoformat(),
        Campo.DESFECHO: u.desfecho.value,
        Campo.DESFECHO_AVISO: u.desfecho_aviso.value,
        Campo.VERMELHOS: sorted(u.vermelhos),
        Campo.MENSAGEM: u.mensagem,
    }


def _para_json(i: Inscricao) -> dict[str, Any]:
    return {
        Campo.REPO: i.repo,
        Campo.VERSAO: i.versao,
        Campo.INTERVALO_S: int(i.intervalo.total_seconds()),
        Campo.ULTIMA: _ultima_para_json(i.ultima),
    }


def _ultima_de_json(d: dict[str, Any] | None) -> UltimaExecucao | None:
    if d is None:
        return None
    hora = datetime.fromisoformat(d[Campo.HORA])
    if hora.tzinfo is None:
        raise ValueError("hora sem fuso")
    return UltimaExecucao(
        hora,
        Desfecho(d[Campo.DESFECHO]),
        Desfecho(d[Campo.DESFECHO_AVISO]),
        frozenset(str(v) for v in d[Campo.VERMELHOS]),
        str(d[Campo.MENSAGEM]),
    )


def _de_json(d: dict[str, Any]) -> Inscricao:
    return Inscricao(
        str(d[Campo.REPO]),
        str(d[Campo.VERSAO]),
        timedelta(seconds=int(d[Campo.INTERVALO_S])),
        _ultima_de_json(d[Campo.ULTIMA]),
    )


def _inscricoes_de(dados: list[Any]) -> list[Inscricao]:
    inscricoes = []
    for d in dados:
        if isinstance(d, dict) and Campo.REPO not in d and CAMPO_CLONE_ANTIGO in d:
            print(
                AVISO_INSCRICAO_ANTIGA.format(
                    clone=d[CAMPO_CLONE_ANTIGO], versao=d.get(Campo.VERSAO)
                ),
                file=sys.stderr,
            )
            continue
        inscricoes.append(_de_json(d))
    return inscricoes


def carregar(caminho: Path) -> list[Inscricao]:
    try:
        return _inscricoes_de(json.loads(caminho.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return []
    except OSError as e:
        raise RespostaInvalida(f"{caminho}: não foi possível ler ({e})") from e
    except (ValueError, KeyError, TypeError) as e:
        raise RespostaInvalida(
            f"{caminho}: arquivo de inscrições inválido ({e!r})"
        ) from e


def salvar(caminho: Path, inscricoes: list[Inscricao]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=caminho.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump([_para_json(i) for i in inscricoes], f, indent=2)
        os.replace(tmp, caminho)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def inscrever(caminho: Path, nova: Inscricao) -> None:
    atuais = carregar(caminho)
    for n, i in enumerate(atuais):
        if (i.repo, i.versao) == (nova.repo, nova.versao):
            atuais[n] = replace(i, intervalo=nova.intervalo)
            break
    else:
        atuais.append(nova)
    salvar(caminho, atuais)


def remover(caminho: Path, repo: str, versao: str) -> None:
    atuais = carregar(caminho)
    restantes = [i for i in atuais if (i.repo, i.versao) != (repo, versao)]
    if len(restantes) == len(atuais):
        raise ErroDeEntrada(f"inscrição não encontrada: {repo} {versao}")
    salvar(caminho, restantes)


def vencidas(inscricoes: list[Inscricao], agora: datetime) -> list[Inscricao]:
    return [
        i
        for i in inscricoes
        if i.ultima is None or agora - i.ultima.hora >= i.intervalo
    ]


def registrar_execucao(
    caminho: Path,
    inscricao: Inscricao,
    r: Resultado,
    notificador: Notificador,
    agora: datetime,
) -> None:
    atuais = carregar(caminho)
    alvo = next(
        (i for i in atuais if (i.repo, i.versao) == (inscricao.repo, inscricao.versao)),
        None,
    )
    if alvo is None:
        return
    titulo = f"{PREFIXO_TITULO} {inscricao.versao}"
    for e in eventos(alvo.ultima, r):
        try:
            notificador.notificar(titulo, f"{_ROTULOS[e.tipo]}: {e.detalhe}")
        except MotorError as erro:
            log.error("notificação falhou: %s", erro)
    if r.desfecho == Desfecho.ENCERRADA:
        novas = [i for i in atuais if i is not alvo]
    else:
        ultima = consolidar(alvo.ultima, r, agora)
        novas = [replace(i, ultima=ultima) if i is alvo else i for i in atuais]
    salvar(caminho, novas)


def _ultima_de(
    caminho: Path, repo: str, versao: str
) -> tuple[bool, UltimaExecucao | None]:
    for i in carregar(caminho):
        if (i.repo, i.versao) == (repo, versao):
            return True, i.ultima
    return False, None


def rodar(
    caminho: Path,
    agora: datetime,
    disparar: Callable[[Inscricao], int],
    notificador: Notificador,
) -> None:
    for i in vencidas(carregar(caminho), agora):
        codigo = disparar(i)
        existe, depois = _ultima_de(caminho, i.repo, i.versao)
        if existe and depois == i.ultima:
            mensagem = (
                MENSAGEM_TEMPO_ESGOTADO.format(limite=LIMITE_EXECUCAO_S)
                if codigo == TEMPO_ESGOTADO
                else MENSAGEM_SEM_RESULTADO.format(codigo=codigo)
            )
            r = Resultado(Desfecho.ERRO, mensagem=mensagem)
            registrar_execucao(caminho, i, r, notificador, agora)


def disparar_subprocesso(i: Inscricao, env: Mapping[str, str]) -> int:
    # -P: o cwd herdado não pode sombrear o pacote `motor` instalado.
    cmd = [
        sys.executable, "-P", "-m", "motor",
        "inscricao", "executar", i.versao, "--repo", i.repo,
    ]  # fmt: skip
    try:
        return subprocess.run(
            cmd,
            check=False,
            env=dict(env),
            timeout=LIMITE_EXECUCAO_S,
        ).returncode
    except subprocess.TimeoutExpired:
        return TEMPO_ESGOTADO
    except OSError:
        return SEM_PROCESSO
