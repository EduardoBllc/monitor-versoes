package tasksource

import (
	"monitor-versoes/internal/domain"
	"monitor-versoes/internal/ports"
)

type FakeTaskSource struct {
	Tasks map[string][]domain.TaskTarget // versao -> tasks
	Err   error
}

func NewFakeTaskSource() *FakeTaskSource {
	return &FakeTaskSource{Tasks: map[string][]domain.TaskTarget{}}
}

func (f *FakeTaskSource) Fetch(versao string) ([]domain.TaskTarget, error) {
	if f.Err != nil {
		return nil, f.Err
	}
	return f.Tasks[versao], nil
}

var _ ports.TaskSource = (*FakeTaskSource)(nil)
