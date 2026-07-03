package services

import "monitor-versoes/internal/ports"

type PublicationGate struct{ Git ports.GitRepo }

// Publicada implementa a trava de rebuild (§6): tag local OU branch remota.
func (g PublicationGate) Publicada(versao string) (bool, error) {
	tagOk, err := g.Git.TagExists(versao)
	if err != nil {
		return false, err
	}
	if tagOk {
		return true, nil
	}
	return g.Git.RemoteBranchExists("origin", versao)
}
