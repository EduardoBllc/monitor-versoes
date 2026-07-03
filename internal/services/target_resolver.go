package services

import (
	"fmt"

	"monitor-versoes/internal/domain"
	"monitor-versoes/internal/ports"
)

type TargetResolver struct {
	Tasks ports.TaskSource
	Git   ports.GitRepo
}

// Resolve busca as tasks no ClickUp e casa cada uma com seus commits em master
// (§4). Desambiguacao multi-projeto (§11) e implicita: SearchCommits so acha
// commits que existem *neste* repo.
func (r TargetResolver) Resolve(versao string) (domain.TargetSet, error) {
	tasks, err := r.Tasks.Fetch(versao)
	if err != nil {
		return nil, fmt.Errorf("buscando tasks no ClickUp: %w", err)
	}

	resultado := domain.TargetSet{}
	for _, t := range tasks {
		padroes := []string{"ch" + t.Chamado, t.Task}
		candidatos, err := r.Git.SearchCommits(padroes, "master")
		if err != nil {
			return nil, fmt.Errorf("buscando commits do chamado %s: %w", t.Chamado, err)
		}
		commits := domain.MatchExato(candidatos, t.Chamado, t.Task)
		commits = domain.OrdenarPorData(commits)
		resultado[t.Chamado] = domain.TaskTarget{
			Chamado: t.Chamado,
			Task:    t.Task,
			Titulo:  t.Titulo,
			Commits: commits,
		}
	}
	return resultado, nil
}
