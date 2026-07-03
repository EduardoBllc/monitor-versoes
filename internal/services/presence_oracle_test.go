package services

import (
	"testing"
	"time"

	"monitor-versoes/internal/adapters/git"
)

func TestPresenceOracleAncestralDireto(t *testing.T) {
	g := git.NewFakeGit()
	t0 := time.Now()
	g.AddCommit("c1", "", "primeiro", t0)
	g.AddCommit("c2", "c1", "segundo", t0)
	g.SetBranch("14.0.0", "c2")

	oracle := PresenceOracle{Git: g}
	ok, err := oracle.Presente("c1", "master", "14.0.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if !ok {
		t.Error("esperava presente=true (ancestral direto)")
	}
}

func TestPresenceOracleViaTrailer(t *testing.T) {
	g := git.NewFakeGit()
	t0 := time.Now()
	g.AddCommit("origem1", "", "fix: algo", t0)
	g.AddCommit("base-tip", "", "base", t0)
	g.SetBranch("13.6.0", "base-tip")
	g.SetBranch("13.7.0", "base-tip")

	if _, err := g.CherryPickX("origem1"); err != nil {
		t.Fatalf("setup: cherry-pick falhou: %v", err)
	}

	oracle := PresenceOracle{Git: g}
	ok, err := oracle.Presente("origem1", "13.6.0", "13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if !ok {
		t.Error("esperava presente=true (via trailer)")
	}
}

func TestPresenceOracleAusente(t *testing.T) {
	g := git.NewFakeGit()
	t0 := time.Now()
	g.AddCommit("origem1", "", "fix: nunca aplicado", t0)
	g.AddCommit("base-tip", "", "base", t0)
	g.SetBranch("13.6.0", "base-tip")
	g.SetBranch("13.7.0", "base-tip")

	oracle := PresenceOracle{Git: g}
	ok, err := oracle.Presente("origem1", "13.6.0", "13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if ok {
		t.Error("esperava presente=false")
	}
}
