package services

import (
	"testing"

	"monitor-versoes/internal/adapters/git"
)

func TestPublicationGateTagLocal(t *testing.T) {
	g := git.NewFakeGit()
	g.Tags["13.7.0"] = true

	gate := PublicationGate{Git: g}
	ok, err := gate.Publicada("13.7.0")
	if err != nil || !ok {
		t.Errorf("Publicada = %v, %v; quer true, nil", ok, err)
	}
}

func TestPublicationGateBranchRemota(t *testing.T) {
	g := git.NewFakeGit()
	g.Remotes["13.7.0"] = true

	gate := PublicationGate{Git: g}
	ok, err := gate.Publicada("13.7.0")
	if err != nil || !ok {
		t.Errorf("Publicada = %v, %v; quer true, nil", ok, err)
	}
}

func TestPublicationGateNaoPublicada(t *testing.T) {
	g := git.NewFakeGit()

	gate := PublicationGate{Git: g}
	ok, err := gate.Publicada("13.7.0")
	if err != nil || ok {
		t.Errorf("Publicada = %v, %v; quer false, nil", ok, err)
	}
}
