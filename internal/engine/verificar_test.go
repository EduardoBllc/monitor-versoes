package engine

import (
	"testing"
	"time"

	"monitor-versoes/internal/adapters/git"
	"monitor-versoes/internal/adapters/tasksource"
	"monitor-versoes/internal/domain"
)

func TestVerificarVerdeQuandoTudoAplicado(t *testing.T) {
	g := git.NewFakeGit()
	t0 := time.Now()
	g.AddCommit("origem1", "", "fix: ch255514 corrige logs", t0)
	g.AddCommit("base-tip", "", "base", t0)
	g.SetBranch("master", "origem1")
	g.SetBranch("13.6.0", "base-tip")
	g.SetBranch("13.7.0", "base-tip")
	if _, err := g.CherryPickX("origem1"); err != nil {
		t.Fatalf("setup: %v", err)
	}
	if err := g.WriteFile("13.7.0", "VERSAO.lock", []byte(`{
		"versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
		"tasks":{"255514":{"task":"VB-2354","titulo":"Logs","commits":["origem1"]}}
	}`), "lock inicial"); err != nil {
		t.Fatalf("setup: %v", err)
	}

	tasks := tasksource.NewFakeTaskSource()
	tasks.Tasks["13.7.0"] = []domain.TaskTarget{{Chamado: "255514", Task: "VB-2354", Titulo: "Logs"}}

	status, err := Verificar(Deps{Git: g, Tasks: tasks}, "13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if !status.Verde {
		t.Errorf("esperava verde, status = %+v", status)
	}
}

func TestVerificarFaltante(t *testing.T) {
	g := git.NewFakeGit()
	t0 := time.Now()
	g.AddCommit("origem1", "", "fix: ch255514 corrige logs", t0)
	g.AddCommit("base-tip", "", "base", t0)
	g.SetBranch("master", "origem1")
	g.SetBranch("13.6.0", "base-tip")
	g.SetBranch("13.7.0", "base-tip")
	if err := g.WriteFile("13.7.0", "VERSAO.lock", []byte(`{
		"versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
		"tasks":{}
	}`), "lock vazio"); err != nil {
		t.Fatalf("setup: %v", err)
	}

	tasks := tasksource.NewFakeTaskSource()
	tasks.Tasks["13.7.0"] = []domain.TaskTarget{{Chamado: "255514", Task: "VB-2354", Titulo: "Logs"}}

	status, err := Verificar(Deps{Git: g, Tasks: tasks}, "13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if status.Verde {
		t.Error("nao deveria ser verde")
	}
	if len(status.Faltantes) != 1 || status.Faltantes[0].HashOrigem != "origem1" {
		t.Errorf("Faltantes = %+v", status.Faltantes)
	}
}
