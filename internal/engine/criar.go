package engine

import (
	"fmt"

	"monitor-versoes/internal/domain"
	"monitor-versoes/internal/services"
)

// Criar monta uma versao do zero (§5). Branch nova e nao publicada - rebuild
// idempotente e permitido ate a primeira publicacao (§6), mas esta operacao
// so cria; recriar do zero e responsabilidade do chamador (remover a worktree
// antes de chamar Criar de novo).
func Criar(d Deps, versao string) (IncrementResult, error) {
	gate := services.PublicationGate{Git: d.Git}
	publicada, err := gate.Publicada(versao)
	if err != nil {
		return IncrementResult{}, err
	}
	if publicada {
		return IncrementResult{}, fmt.Errorf("versao %s ja publicada - use Incrementar", versao)
	}

	baseResolver := services.BaseResolver{Git: d.Git}
	base, err := baseResolver.Resolve(versao)
	if err != nil {
		return IncrementResult{}, err
	}

	if err := d.Git.WorktreeAdd(versao, base.Ref); err != nil {
		return IncrementResult{}, err
	}

	tipo, err := domain.InferirTipo(versao)
	if err != nil {
		return IncrementResult{}, err
	}
	lockStore := services.LockStore{Git: d.Git}
	lockInicial := domain.Lock{Versao: versao, Tipo: tipo, Base: base, Tasks: domain.TargetSet{}}
	if err := lockStore.Escrever(versao, lockInicial); err != nil {
		return IncrementResult{}, err
	}

	return Incrementar(d, versao)
}
