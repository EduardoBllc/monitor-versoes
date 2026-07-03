package services

import (
	"testing"
	"time"

	"monitor-versoes/internal/adapters/git"
	"monitor-versoes/internal/adapters/tasksource"
	"monitor-versoes/internal/domain"
)

func TestTargetResolverResolve(t *testing.T) {
	fakeGit := git.NewFakeGit()
	base := time.Now()
	fakeGit.AddCommit("origem1", "", "fix: ch255514 corrige logs", base)
	fakeGit.AddCommit("origem2", "origem1", "fix: ch5514 nao relacionado", base)
	fakeGit.SetBranch("master", "origem2")

	fakeTasks := tasksource.NewFakeTaskSource()
	fakeTasks.Tasks["13.7.0"] = []domain.TaskTarget{
		{Chamado: "255514", Task: "VB-2354", Titulo: "Logs pedidos ecommerce"},
	}

	resolver := TargetResolver{Tasks: fakeTasks, Git: fakeGit}
	resultado, err := resolver.Resolve("13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}

	tt, ok := resultado["255514"]
	if !ok {
		t.Fatal("esperava chamado 255514 no resultado")
	}
	if len(tt.Commits) != 1 || tt.Commits[0].HashOrigem != "origem1" {
		t.Errorf("Commits = %+v, quer so origem1", tt.Commits)
	}
}
