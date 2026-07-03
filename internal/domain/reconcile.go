package domain

import "sort"

// FiltrarExcluidos remove do alvo os commits ja marcados como excluidos no
// lock (§3) - sem isso, todo verificar reportaria o mesmo falso-positivo pra
// sempre.
func FiltrarExcluidos(alvo TargetSet, excluidos []Exclusion) TargetSet {
	excluido := make(map[string]bool, len(excluidos))
	for _, e := range excluidos {
		excluido[e.Commit] = true
	}
	filtrado := make(TargetSet, len(alvo))
	for chamado, tt := range alvo {
		var commits []CommitRef
		for _, c := range tt.Commits {
			if !excluido[c.HashOrigem] {
				commits = append(commits, c)
			}
		}
		filtrado[chamado] = TaskTarget{Chamado: tt.Chamado, Task: tt.Task, Titulo: tt.Titulo, Commits: commits}
	}
	return filtrado
}

// DiffTasks calcula a diferenca simetrica entre alvo e lock (§5, §9).
func DiffTasks(alvo, lockTasks TargetSet) (novas, removidas []string) {
	for chamado := range alvo {
		if _, ok := lockTasks[chamado]; !ok {
			novas = append(novas, chamado)
		}
	}
	for chamado := range lockTasks {
		if _, ok := alvo[chamado]; !ok {
			removidas = append(removidas, chamado)
		}
	}
	sort.Strings(novas)
	sort.Strings(removidas)
	return novas, removidas
}

// Reconciliar cruza as 3 fontes (§2, §9) e produz o VersionStatus. `presentes`
// e `conflitantes` sao pre-computados pelo chamador (services.PresenceOracle e
// GitRepo.PredictMerge) - esta funcao fica pura.
func Reconciliar(alvo TargetSet, lock Lock, presentes map[string]bool, conflitantes []CommitRef) VersionStatus {
	novas, removidas := DiffTasks(alvo, lock.Tasks)

	var faltantes []CommitRef
	for _, tt := range alvo {
		for _, c := range tt.Commits {
			if !presentes[c.HashOrigem] {
				faltantes = append(faltantes, c)
			}
		}
	}

	lockIntegro := true
	var sumidos []string
	for _, tt := range lock.Tasks {
		for _, c := range tt.Commits {
			if !presentes[c.HashOrigem] {
				lockIntegro = false
				sumidos = append(sumidos, c.HashOrigem)
			}
		}
	}
	sort.Strings(sumidos)

	verde := len(novas) == 0 && len(removidas) == 0 && lockIntegro && len(faltantes) == 0

	return VersionStatus{
		Verde:          verde,
		TasksNovas:     novas,
		TasksRemovidas: removidas,
		LockIntegro:    lockIntegro,
		CommitsSumidos: sumidos,
		Faltantes:      faltantes,
		Conflitantes:   conflitantes,
	}
}
