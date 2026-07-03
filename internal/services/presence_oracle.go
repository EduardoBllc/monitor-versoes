package services

import (
	"strings"

	"monitor-versoes/internal/ports"
)

type PresenceOracle struct{ Git ports.GitRepo }

// Presente implementa o oraculo de 3 niveis (§2): ancestral direto, trailer de
// cherry-pick, e por ultimo patch-id (fallback legado). base delimita o
// intervalo varrido para os niveis 2 e 3 (desvio 8 do topo deste plano).
func (o PresenceOracle) Presente(hashOrigem, base, branch string) (bool, error) {
	ancestral, err := o.Git.IsAncestor(hashOrigem, branch)
	if err != nil {
		return false, err
	}
	if ancestral {
		return true, nil
	}

	commits, err := o.Git.CommitsInRange(base, branch)
	if err != nil {
		return false, err
	}

	trailer := "cherry picked from commit " + hashOrigem
	for _, c := range commits {
		if strings.Contains(c.Msg, trailer) {
			return true, nil
		}
	}

	patchIDOrigem, err := o.Git.PatchID(hashOrigem)
	if err != nil {
		return false, err
	}
	for _, c := range commits {
		pid, err := o.Git.PatchID(c.HashOrigem)
		if err != nil {
			continue
		}
		if pid == patchIDOrigem {
			return true, nil
		}
	}
	return false, nil
}
