package services

import (
	"testing"
	"time"

	"monitor-versoes/internal/adapters/git"
)

func TestBaseResolverResolve(t *testing.T) {
	g := git.NewFakeGit()
	g.AddCommit("hash136", "", "base 13.6.0", time.Now())
	g.SetBranch("13.6.0", "hash136")

	resolver := BaseResolver{Git: g}
	base, err := resolver.Resolve("13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if base.Ref != "13.6.0" || base.Commit != "hash136" {
		t.Errorf("base = %+v, quer ref=13.6.0 commit=hash136", base)
	}
}
