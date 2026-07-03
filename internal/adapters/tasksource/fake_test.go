package tasksource

import (
	"errors"
	"testing"

	"monitor-versoes/internal/domain"
)

func TestFakeTaskSourceFetch(t *testing.T) {
	f := NewFakeTaskSource()
	f.Tasks["13.7.0"] = []domain.TaskTarget{{Chamado: "255514", Task: "VB-2354"}}

	tasks, err := f.Fetch("13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if len(tasks) != 1 || tasks[0].Chamado != "255514" {
		t.Errorf("tasks = %+v", tasks)
	}
}

func TestFakeTaskSourceErro(t *testing.T) {
	f := NewFakeTaskSource()
	f.Err = errors.New("falha simulada")

	if _, err := f.Fetch("13.7.0"); err == nil {
		t.Error("esperava erro")
	}
}
