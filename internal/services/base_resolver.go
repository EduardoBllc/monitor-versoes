package services

import (
	"fmt"

	"monitor-versoes/internal/domain"
	"monitor-versoes/internal/ports"
)

type BaseResolver struct{ Git ports.GitRepo }

func (r BaseResolver) Resolve(numero string) (domain.BaseRef, error) {
	existentes, err := r.Git.ListVersionBranches()
	if err != nil {
		return domain.BaseRef{}, err
	}
	ref, err := domain.InferirBase(numero, existentes)
	if err != nil {
		return domain.BaseRef{}, err
	}
	commit, err := r.Git.ResolveRef(ref)
	if err != nil {
		return domain.BaseRef{}, fmt.Errorf("resolvendo ref %s: %w", ref, err)
	}
	return domain.BaseRef{Ref: ref, Commit: commit}, nil
}
