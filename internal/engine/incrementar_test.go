package engine

import (
	"testing"
	"time"

	"monitor-versoes/internal/adapters/git"
	"monitor-versoes/internal/adapters/tasksource"
	"monitor-versoes/internal/domain"
	"monitor-versoes/internal/services"
)

func serviceLockStore(g *git.FakeGit) services.LockStore {
	return services.LockStore{Git: g}
}

func setupIncrementoBasico(t *testing.T) (*git.FakeGit, *tasksource.FakeTaskSource) {
	t.Helper()
	g := git.NewFakeGit()
	t0 := time.Now()
	g.AddCommit("origem1", "", "fix: ch255514 corrige logs", t0)
	g.AddCommit("base-tip", "", "base", t0)
	g.SetBranch("master", "origem1")
	g.SetBranch("13.6.0", "base-tip")
	g.SetBranch("13.7.0", "base-tip")
	if err := g.WriteFile("13.7.0", "VERSAO.lock", []byte(`{
		"versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
		"tasks":{}
	}`), "lock inicial"); err != nil {
		t.Fatalf("setup: %v", err)
	}

	tasks := tasksource.NewFakeTaskSource()
	tasks.Tasks["13.7.0"] = []domain.TaskTarget{{Chamado: "255514", Task: "VB-2354", Titulo: "Logs"}}
	return g, tasks
}

func TestIncrementarAplicaTudo(t *testing.T) {
	g, tasks := setupIncrementoBasico(t)

	resultado, err := Incrementar(Deps{Git: g, Tasks: tasks}, "13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if resultado.Status != StatusDone {
		t.Errorf("Status = %v, quer StatusDone", resultado.Status)
	}

	lockStore := serviceLockStore(g)
	lock, err := lockStore.Ler("13.7.0")
	if err != nil {
		t.Fatalf("erro lendo lock: %v", err)
	}
	if len(lock.Tasks["255514"].Commits) != 1 {
		t.Errorf("lock apos incrementar = %+v", lock.Tasks)
	}
}

func TestIncrementarParaEmConflito(t *testing.T) {
	g, tasks := setupIncrementoBasico(t)
	g.ConflictOn["origem1"] = true

	resultado, err := Incrementar(Deps{Git: g, Tasks: tasks}, "13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if resultado.Status != StatusBlocked {
		t.Errorf("Status = %v, quer StatusBlocked", resultado.Status)
	}
	if resultado.BlockedCommit != "origem1" {
		t.Errorf("BlockedCommit = %q, quer origem1", resultado.BlockedCommit)
	}
}

func TestIncrementarContinueRegistraNoLock(t *testing.T) {
	g, tasks := setupIncrementoBasico(t)
	g.ConflictOn["origem1"] = true

	if _, err := Incrementar(Deps{Git: g, Tasks: tasks}, "13.7.0"); err != nil {
		t.Fatalf("erro no incremento inicial: %v", err)
	}

	resultado, err := IncrementarContinue(Deps{Git: g, Tasks: tasks}, "13.7.0")
	if err != nil {
		t.Fatalf("erro no continue: %v", err)
	}
	if resultado.Status != StatusDone {
		t.Errorf("Status = %v, quer StatusDone", resultado.Status)
	}

	lockStore := serviceLockStore(g)
	lock, err := lockStore.Ler("13.7.0")
	if err != nil {
		t.Fatalf("erro lendo lock: %v", err)
	}
	if len(lock.Tasks["255514"].Commits) != 1 {
		t.Errorf("lock apos continue = %+v", lock.Tasks)
	}
}

// TestIncrementarContinuePreservaCommitsAnteriores cobre um lote de 2 commits
// onde o SEGUNDO conflita. O primeiro ja foi cherry-picked pra branch (e so
// nao esta no lock ainda, porque Incrementar escreve o lock em lote, no fim).
// IncrementarContinue precisa recuperar OS DOIS commits do git (via
// LockStore.Reconstruir), nao so o que acabou de ser resolvido - senao o
// registro do primeiro chamado se perde pra sempre do lock, mesmo estando
// correto no historico do git.
func TestIncrementarContinuePreservaCommitsAnteriores(t *testing.T) {
	g := git.NewFakeGit()
	t0 := time.Now()
	t1 := t0.Add(time.Minute)
	g.AddCommit("origem1", "", "fix: ch255514 corrige logs", t0)
	g.AddCommit("origem2", "origem1", "fix: ch255515 outra correcao VB-9999", t1)
	g.AddCommit("base-tip", "", "base", t0)
	g.SetBranch("master", "origem2")
	g.SetBranch("13.6.0", "base-tip")
	g.SetBranch("13.7.0", "base-tip")
	if err := g.WriteFile("13.7.0", "VERSAO.lock", []byte(`{
		"versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
		"tasks":{}
	}`), "lock inicial"); err != nil {
		t.Fatalf("setup: %v", err)
	}
	g.ConflictOn["origem2"] = true

	tasks := tasksource.NewFakeTaskSource()
	tasks.Tasks["13.7.0"] = []domain.TaskTarget{
		{Chamado: "255514", Task: "VB-2354", Titulo: "Logs"},
		{Chamado: "255515", Task: "VB-9999", Titulo: "Outra"},
	}

	resultado, err := Incrementar(Deps{Git: g, Tasks: tasks}, "13.7.0")
	if err != nil {
		t.Fatalf("erro no incremento inicial: %v", err)
	}
	if resultado.Status != StatusBlocked || resultado.BlockedCommit != "origem2" {
		t.Fatalf("resultado inicial = %+v, quer StatusBlocked em origem2", resultado)
	}

	resultado, err = IncrementarContinue(Deps{Git: g, Tasks: tasks}, "13.7.0")
	if err != nil {
		t.Fatalf("erro no continue: %v", err)
	}
	if resultado.Status != StatusDone {
		t.Fatalf("Status = %v, quer StatusDone", resultado.Status)
	}

	lockStore := serviceLockStore(g)
	lock, err := lockStore.Ler("13.7.0")
	if err != nil {
		t.Fatalf("erro lendo lock: %v", err)
	}
	if len(lock.Tasks["255514"].Commits) != 1 {
		t.Errorf("lock.Tasks[255514] = %+v, o commit aplicado antes do conflito nao pode se perder", lock.Tasks["255514"])
	}
	if len(lock.Tasks["255515"].Commits) != 1 {
		t.Errorf("lock.Tasks[255515] = %+v, quer 1 commit", lock.Tasks["255515"])
	}
}
