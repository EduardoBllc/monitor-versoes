package engine

import (
	"fmt"

	"monitor-versoes/internal/domain"
	"monitor-versoes/internal/ports"
	"monitor-versoes/internal/services"
)

type IncrementStatus int

const (
	StatusDone IncrementStatus = iota
	StatusBlocked
)

type IncrementResult struct {
	Status           IncrementStatus
	BlockedCommit    string
	ArquivosConflito []string
}

// Incrementar aplica os commits faltantes por commit-date asc (§5). So adiciona
// historia - e o unico modo permitido quando a versao ja tem tag (§6, checado
// pelo chamador via services.PublicationGate antes de decidir entre Criar e
// Incrementar).
func Incrementar(d Deps, versao string) (IncrementResult, error) {
	status, err := Verificar(d, versao)
	if err != nil {
		return IncrementResult{}, err
	}

	faltam := domain.OrdenarPorData(status.Faltantes)
	lockStore := services.LockStore{Git: d.Git}
	lock, err := lockStore.Ler(versao)
	if err != nil {
		return IncrementResult{}, err
	}

	if err := d.Git.UseWorktree(versao); err != nil {
		return IncrementResult{}, err
	}

	for _, c := range faltam {
		outcome, err := d.Git.CherryPickX(c.HashOrigem)
		if err != nil {
			return IncrementResult{}, err
		}
		if outcome == ports.Conflito {
			paths, err := d.Git.ConflictedPaths()
			if err != nil {
				return IncrementResult{}, err
			}
			if len(paths) == 0 {
				// rerere.autoUpdate resolveu sozinho (§8) - segue o pick.
				if err := d.Git.ContinueCherryPick(); err != nil {
					return IncrementResult{}, err
				}
				lock = registrarCommit(lock, c)
				continue
			}
			return IncrementResult{Status: StatusBlocked, BlockedCommit: c.HashOrigem, ArquivosConflito: paths}, nil
		}
		lock = registrarCommit(lock, c)
	}

	if err := lockStore.Escrever(versao, lock); err != nil {
		return IncrementResult{}, err
	}
	return IncrementResult{Status: StatusDone}, nil
}

func registrarCommit(lock domain.Lock, c domain.CommitRef) domain.Lock {
	if lock.Tasks == nil {
		lock.Tasks = domain.TargetSet{}
	}
	tt := lock.Tasks[c.Chamado]
	tt.Chamado = c.Chamado
	tt.Task = c.Task
	tt.Commits = append(tt.Commits, c)
	lock.Tasks[c.Chamado] = tt
	return lock
}

// IncrementarContinue retoma um cherry-pick pendente resolvido manualmente
// (checkpoint resumivel, §8). E uma invocacao nova do CLI - sem contexto em
// memoria de quais commits do lote ja foram aplicados antes do conflito, por
// isso usa LockStore.Reconstruir (varre base..branch de verdade) pra
// recompor o lock inteiro antes de continuar o lote.
func IncrementarContinue(d Deps, versao string) (IncrementResult, error) {
	if err := d.Git.UseWorktree(versao); err != nil {
		return IncrementResult{}, err
	}
	_, ok, err := d.Git.PendingCherryPick()
	if err != nil {
		return IncrementResult{}, err
	}
	if !ok {
		return IncrementResult{}, fmt.Errorf("nenhum cherry-pick pendente pra continuar")
	}

	if err := d.Git.ContinueCherryPick(); err != nil {
		return IncrementResult{}, err
	}

	lockStore := services.LockStore{Git: d.Git}
	anterior, err := lockStore.Ler(versao)
	if err != nil {
		return IncrementResult{}, err
	}

	// O lote (§5) so escreve o lock no fim de um lote bem-sucedido - se o
	// conflito que trouxe a gente aqui aconteceu no meio de um lote, os
	// commits anteriores a ele ja foram cherry-picked pra branch mas ainda nao
	// estao no lock. Reconstruir varre base..branch de verdade (git) e
	// recupera todos eles de uma vez, em vez de registrar so o commit que
	// acabou de ser resolvido.
	lock, _, err := lockStore.Reconstruir(versao, anterior.Base, versao, &anterior)
	if err != nil {
		return IncrementResult{}, err
	}
	if err := lockStore.Escrever(versao, lock); err != nil {
		return IncrementResult{}, err
	}

	return Incrementar(d, versao)
}

func IncrementarAbort(d Deps, versao string) error {
	if err := d.Git.UseWorktree(versao); err != nil {
		return err
	}
	return d.Git.AbortCherryPick()
}
