"""Um `Get-ScheduledTask` falso para os scripts PowerShell: um módulo de mesmo nome na frente do PSModulePath."""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

VAR_PSMODULEPATH = "PSModulePath"
VAR_TAREFAS = "FALSO_TAREFAS"
MODULO = "ScheduledTasks"
_PSM1 = f"""function Get-ScheduledTask {{
    [CmdletBinding()]
    param([string]$TaskName)
    foreach ($par in ($env:{VAR_TAREFAS} -split ',')) {{
        $nome, $estado = $par -split '=', 2
        if ($nome -eq $TaskName) {{
            return [pscustomobject]@{{ TaskName = $nome; State = $estado }}
        }}
    }}
}}
Export-ModuleMember -Function Get-ScheduledTask
"""


class EstadoTarefa(StrEnum):
    ATIVADA = "Ready"
    DESATIVADA = "Disabled"


def com_tarefas(
    pasta: Path, env: dict[str, str], tarefas: dict[str, EstadoTarefa]
) -> dict[str, str]:
    """`env` com o módulo falso; tarefa fora de `tarefas` não existe."""
    modulo = pasta / MODULO
    modulo.mkdir(parents=True, exist_ok=True)
    (modulo / f"{MODULO}.psm1").write_text(_PSM1, encoding="ascii")
    caminhos = [str(pasta), env.get(VAR_PSMODULEPATH, "")]
    return {
        **env,
        VAR_PSMODULEPATH: os.pathsep.join(c for c in caminhos if c),
        VAR_TAREFAS: ",".join(f"{nome}={estado}" for nome, estado in tarefas.items()),
    }
