package engine

import "monitor-versoes/internal/ports"

type Deps struct {
	Git   ports.GitRepo
	Tasks ports.TaskSource
}
