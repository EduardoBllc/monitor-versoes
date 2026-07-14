"""Porte de internal/services/lock_store.go."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace

from motor.domain.commits import extrair_chamado, extrair_vb_id, ordenar_por_data
from motor.domain.types import (
    BaseRef,
    CommitRef,
    Exclusion,
    ExclusionReason,
    Lock,
    TargetSet,
    TaskTarget,
    VersionType,
)
from motor.domain.version import inferir_tipo
from motor.errors import MotorError
from motor.ports import GitRepo



@dataclass
class LockStore:
    git: GitRepo
    lock_dir: str

    def ler(self, branch: str) -> Lock:
        path = os.path.join(self.lock_dir, f"{branch}.lock")
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except FileNotFoundError:
            raise MotorError(f"Arquivo lock da versão '{branch}' não encontrado. Você já rodou 'motor criar {branch}'?")
        except Exception as e:
            raise MotorError(f"lendo {path}: {e}") from e
        try:
            lj = json.loads(raw)
        except Exception as e:
            raise MotorError(f"parseando {path}: {e}") from e

        versao = lj.get("versao", "")
        tipo = inferir_tipo(versao)

        tasks: TargetSet = {}
        for chamado, t in (lj.get("tasks") or {}).items():
            commits = [CommitRef(hash_origem=h) for h in t.get("commits") or []]
            tasks[chamado] = TaskTarget(
                chamado=chamado, task=t.get("task", ""), titulo=t.get("titulo", ""), commits=commits
            )

        excluidos = [
            Exclusion(
                commit=e.get("commit", ""),
                chamado=e.get("chamado", ""),
                motivo=e.get("motivo", ""),
                reason=ExclusionReason.AUTOMATICA,
            )
            for e in (lj.get("excluidos") or [])
        ]

        base = lj.get("base") or {}
        return Lock(
            versao=versao,
            tipo=tipo,
            base=BaseRef(ref=base.get("ref", ""), commit=base.get("commit", "")),
            tasks=tasks,
            excluidos=excluidos,
        )

    def escrever(self, branch: str, lock: Lock) -> None:
        lj: dict = {
            "versao": lock.versao,
            "tipo": _tipo_para_string(lock.tipo),
            "base": {"ref": lock.base.ref, "commit": lock.base.commit},
            "tasks": {},
            "excluidos": [],
        }
        for chamado, t in lock.tasks.items():
            hashes = [c.hash_origem for c in t.commits]
            lj["tasks"][chamado] = {"task": t.task, "titulo": t.titulo, "commits": hashes}
        for e in lock.excluidos:
            lj["excluidos"].append({"commit": e.commit, "chamado": e.chamado, "motivo": e.motivo})

        try:
            raw = json.dumps(lj, indent=2).encode("utf-8")
        except Exception as e:
            raise MotorError(f"serializando lock para {branch}: {e}") from e
        
        path = os.path.join(self.lock_dir, f"{branch}.lock")
        try:
            os.makedirs(self.lock_dir, exist_ok=True)
            with open(path, "wb") as f:
                f.write(raw)
        except Exception as e:
            raise MotorError(f"escrevendo {path}: {e}") from e

    def reconstruir(
        self, branch: str, base: BaseRef, versao: str, anterior: Lock | None
    ) -> tuple[Lock, list[Exclusion]]:
        """Varre os trailers de cherry-pick em base..branch e regenera o lock
        (§3). `anterior`, se fornecido, e usado so pra apontar exclusoes por
        julgamento que nao dao pra recuperar da varredura - viram orfaos.
        """
        try:
            commits = self.git.commits_in_range(base.ref, branch)
        except Exception as e:
            raise MotorError(f"varrendo commits: {e}") from e

        tipo = inferir_tipo(versao)

        tasks: TargetSet = {}
        for c in commits:
            origem_hash = _extrair_trailer(c.msg)
            if origem_hash is None:
                # commit direto na branch (sem cherry-pick -x): usa a si mesmo
                # como origem, ja tem chamado/vb_id na propria mensagem.
                origem_hash = c.hash_origem
                origem_meta = c
            else:
                try:
                    origem_meta = self.git.commit_meta(origem_hash)
                except Exception:
                    continue  # origem sumiu do historico

            chamado = extrair_chamado(origem_meta.msg)
            vb_id = extrair_vb_id(origem_meta.msg)
            if chamado is None and vb_id is None:
                continue
            chamado_str = chamado or ""
            chave = chamado_str if chamado_str != "" else (vb_id or "")

            tt = tasks.get(chave, TaskTarget())
            novo_commit = CommitRef(
                hash_origem=origem_hash,
                chamado=chamado_str,
                task=vb_id or "",
                commit_date=origem_meta.commit_date,
                msg=origem_meta.msg,
            )
            tasks[chave] = replace(
                tt,
                chamado=chamado_str,
                task=(vb_id if vb_id is not None else tt.task),
                commits=[*tt.commits, novo_commit],
            )

        for chave, tt in tasks.items():
            tasks[chave] = replace(tt, commits=ordenar_por_data(tt.commits))

        lock = Lock(versao=versao, tipo=tipo, base=base, tasks=tasks)

        orfaos: list[Exclusion] = []
        if anterior is not None:
            orfaos = [e for e in anterior.excluidos if e.reason == ExclusionReason.JULGAMENTO]

        return lock, orfaos


def _tipo_para_string(t: VersionType) -> str:
    if t == VersionType.FECHADA:
        return "fechada"
    if t == VersionType.AJUSTADA:
        return "ajustada"
    return "cliente"


def _extrair_trailer(msg: str) -> str | None:
    marca = "(cherry picked from commit "
    i = msg.find(marca)
    if i < 0:
        return None
    resto = msg[i + len(marca) :]
    fim = resto.find(")")
    if fim < 0:
        return None
    return resto[:fim]
