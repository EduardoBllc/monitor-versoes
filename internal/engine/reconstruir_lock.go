package engine

import (
	"monitor-versoes/internal/domain"
	"monitor-versoes/internal/services"
)

type ReconstructStatus int

const (
	ReconstructDone ReconstructStatus = iota
	ReconstructPendingJudgment
)

type ReconstructResult struct {
	Status ReconstructStatus
	Orfaos []domain.Exclusion
}

// ReconstruirLock regenera VERSAO.lock a partir dos trailers quando ele e
// apagado/corrompido (§3). Nunca interativo - PendingJudgment e um valor de
// retorno, quem pergunta ao humano e o front-end (§14).
func ReconstruirLock(d Deps, versao string) (ReconstructResult, error) {
	lockStore := services.LockStore{Git: d.Git}

	var anterior *domain.Lock
	if l, err := lockStore.Ler(versao); err == nil {
		anterior = &l
	}

	baseResolver := services.BaseResolver{Git: d.Git}
	base, err := baseResolver.Resolve(versao)
	if err != nil {
		return ReconstructResult{}, err
	}

	novoLock, orfaos, err := lockStore.Reconstruir(versao, base, versao, anterior)
	if err != nil {
		return ReconstructResult{}, err
	}
	if err := lockStore.Escrever(versao, novoLock); err != nil {
		return ReconstructResult{}, err
	}

	if len(orfaos) > 0 {
		return ReconstructResult{Status: ReconstructPendingJudgment, Orfaos: orfaos}, nil
	}
	return ReconstructResult{Status: ReconstructDone}, nil
}
