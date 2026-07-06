package engine

import (
	"testing"
	"time"

	"monitor-versoes/internal/adapters/git"
	"monitor-versoes/internal/adapters/tasksource"
	"monitor-versoes/internal/domain"
)

func TestCriarNovaVersao(t *testing.T) {
	g := git.NewFakeGit()
	t0 := time.Now()
	g.AddCommit("origem1", "", "fix: ch255514 corrige logs", t0)
	g.AddCommit("hash136", "", "base 13.6.0", t0)
	g.SetBranch("master", "origem1")
	g.SetBranch("13.6.0", "hash136")

	tasks := tasksource.NewFakeTaskSource()
	tasks.Tasks["13.7.0"] = []domain.TaskTarget{{Chamado: "255514", Task: "VB-2354", Titulo: "Logs"}}

	resultado, err := Criar(Deps{Git: g, Tasks: tasks}, "13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if resultado.Status != StatusDone {
		t.Errorf("Status = %v, quer StatusDone", resultado.Status)
	}
	if _, existe := g.Branches["13.7.0"]; !existe {
		t.Error("esperava branch 13.7.0 criada")
	}
}

func TestCriarFalhaSeJaPublicada(t *testing.T) {
	g := git.NewFakeGit()
	g.Tags["13.7.0"] = true
	tasks := tasksource.NewFakeTaskSource()

	if _, err := Criar(Deps{Git: g, Tasks: tasks}, "13.7.0"); err == nil {
		t.Error("esperava erro pra versao ja publicada")
	}
}
