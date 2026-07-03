package git

import (
	"testing"
	"time"

	"monitor-versoes/internal/ports"
)

func TestFakeGitCherryPickAplicaEEncadeiaTrailer(t *testing.T) {
	g := NewFakeGit()
	base := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	g.AddCommit("origem1", "", "fix: ch255514 corrige logs", base)
	g.AddCommit("base-tip", "", "base", base)
	g.SetBranch("13.7.0", "base-tip")

	outcome, err := g.CherryPickX("origem1")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if outcome != ports.Aplicado {
		t.Errorf("outcome = %v, quer Aplicado", outcome)
	}

	novoTip := g.Branches["13.7.0"]
	commit := g.Commits[novoTip]
	if commit.OrigemHash != "origem1" {
		t.Errorf("OrigemHash = %q, quer origem1", commit.OrigemHash)
	}
}

func TestFakeGitCherryPickConflitoEContinue(t *testing.T) {
	g := NewFakeGit()
	g.AddCommit("origem1", "", "fix: algo", time.Now())
	g.AddCommit("base-tip", "", "base", time.Now())
	g.SetBranch("13.7.0", "base-tip")
	g.ConflictOn["origem1"] = true

	outcome, err := g.CherryPickX("origem1")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if outcome != ports.Conflito {
		t.Errorf("outcome = %v, quer Conflito", outcome)
	}
	paths, _ := g.ConflictedPaths()
	if len(paths) == 0 {
		t.Error("esperava arquivos em conflito")
	}
	if hash, ok, _ := g.PendingCherryPick(); !ok || hash != "origem1" {
		t.Errorf("PendingCherryPick = %q, %v; quer origem1, true", hash, ok)
	}

	if err := g.ContinueCherryPick(); err != nil {
		t.Fatalf("continue falhou: %v", err)
	}
	if paths, _ := g.ConflictedPaths(); len(paths) != 0 {
		t.Error("apos continue, nao deveria sobrar conflito")
	}
	if _, ok, _ := g.PendingCherryPick(); ok {
		t.Error("nao deveria sobrar cherry-pick pendente apos continue")
	}
}

func TestFakeGitReadWriteFile(t *testing.T) {
	g := NewFakeGit()
	if err := g.WriteFile("13.7.0", "VERSAO.lock", []byte("{}"), "atualiza lock"); err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	conteudo, err := g.ReadFile("13.7.0", "VERSAO.lock")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if string(conteudo) != "{}" {
		t.Errorf("conteudo = %q, quer {}", conteudo)
	}
}

func TestFakeGitIsAncestorEMergeBase(t *testing.T) {
	g := NewFakeGit()
	t0 := time.Now()
	g.AddCommit("c1", "", "primeiro", t0)
	g.AddCommit("c2", "c1", "segundo", t0)
	g.SetBranch("master", "c2")

	ok, err := g.IsAncestor("c1", "master")
	if err != nil || !ok {
		t.Errorf("IsAncestor(c1, master) = %v, %v; quer true, nil", ok, err)
	}

	ok, err = g.IsAncestor("naoexiste", "master")
	if err != nil || ok {
		t.Errorf("IsAncestor(naoexiste, master) = %v, %v; quer false, nil", ok, err)
	}
}
