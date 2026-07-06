package engine

import (
	"testing"
	"time"

	"monitor-versoes/internal/adapters/git"
)

func TestReconstruirLockSemAnterior(t *testing.T) {
	g := git.NewFakeGit()
	t0 := time.Now()
	g.AddCommit("origem1", "", "fix: ch255514 corrige logs", t0)
	g.AddCommit("hash136", "", "base 13.6.0", t0)
	g.SetBranch("13.6.0", "hash136")
	g.SetBranch("13.7.0", "hash136")
	if _, err := g.CherryPickX("origem1"); err != nil {
		t.Fatalf("setup: %v", err)
	}

	resultado, err := ReconstruirLock(Deps{Git: g}, "13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if resultado.Status != ReconstructDone {
		t.Errorf("Status = %v, quer ReconstructDone", resultado.Status)
	}

	lockStore := serviceLockStore(g)
	lock, err := lockStore.Ler("13.7.0")
	if err != nil {
		t.Fatalf("erro lendo lock reconstruido: %v", err)
	}
	if len(lock.Tasks["255514"].Commits) != 1 {
		t.Errorf("tasks reconstruidas = %+v", lock.Tasks)
	}
}
