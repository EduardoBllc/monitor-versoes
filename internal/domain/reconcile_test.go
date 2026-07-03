package domain

import "testing"

func mkTargetSet(chamado, task string, hashes ...string) TargetSet {
	var commits []CommitRef
	for _, h := range hashes {
		commits = append(commits, CommitRef{HashOrigem: h})
	}
	return TargetSet{chamado: {Chamado: chamado, Task: task, Commits: commits}}
}

func TestReconciliarVerde(t *testing.T) {
	alvo := mkTargetSet("255514", "VB-2354", "hash1")
	lock := Lock{Tasks: mkTargetSet("255514", "VB-2354", "hash1")}
	presentes := map[string]bool{"hash1": true}

	status := Reconciliar(alvo, lock, presentes, nil)

	if !status.Verde {
		t.Errorf("esperava verde, status = %+v", status)
	}
}

func TestReconciliarTaskNova(t *testing.T) {
	alvo := mkTargetSet("255514", "VB-2354", "hash1")
	lock := Lock{Tasks: TargetSet{}}
	presentes := map[string]bool{"hash1": true}

	status := Reconciliar(alvo, lock, presentes, nil)

	if status.Verde {
		t.Error("nao deveria ser verde com task nova")
	}
	if len(status.TasksNovas) != 1 || status.TasksNovas[0] != "255514" {
		t.Errorf("TasksNovas = %v, quer [255514]", status.TasksNovas)
	}
}

func TestReconciliarTaskRemovida(t *testing.T) {
	alvo := TargetSet{}
	lock := Lock{Tasks: mkTargetSet("255514", "VB-2354", "hash1")}
	presentes := map[string]bool{"hash1": true}

	status := Reconciliar(alvo, lock, presentes, nil)

	if len(status.TasksRemovidas) != 1 || status.TasksRemovidas[0] != "255514" {
		t.Errorf("TasksRemovidas = %v, quer [255514]", status.TasksRemovidas)
	}
}

func TestReconciliarLockNaoIntegro(t *testing.T) {
	alvo := mkTargetSet("255514", "VB-2354", "hash1")
	lock := Lock{Tasks: mkTargetSet("255514", "VB-2354", "hash1")}
	presentes := map[string]bool{} // hash1 nao presente

	status := Reconciliar(alvo, lock, presentes, nil)

	if status.LockIntegro {
		t.Error("esperava LockIntegro=false")
	}
	if len(status.CommitsSumidos) != 1 || status.CommitsSumidos[0] != "hash1" {
		t.Errorf("CommitsSumidos = %v, quer [hash1]", status.CommitsSumidos)
	}
	if len(status.Faltantes) != 1 {
		t.Errorf("Faltantes = %+v, quer 1 item", status.Faltantes)
	}
}

func TestFiltrarExcluidos(t *testing.T) {
	alvo := mkTargetSet("251099", "VB-2549", "hashA", "hashB")
	excluidos := []Exclusion{{Commit: "hashA", Chamado: "251099", Motivo: "ja presente na base"}}

	filtrado := FiltrarExcluidos(alvo, excluidos)

	commits := filtrado["251099"].Commits
	if len(commits) != 1 || commits[0].HashOrigem != "hashB" {
		t.Errorf("commits apos filtro = %+v, quer so hashB", commits)
	}
}
