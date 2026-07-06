package engine

import (
	"testing"
	"time"

	"monitor-versoes/internal/adapters/git"
	"monitor-versoes/internal/adapters/tasksource"
	"monitor-versoes/internal/domain"
	"monitor-versoes/internal/ports"
)

func TestVerificarVerdeQuandoTudoAplicado(t *testing.T) {
	g := git.NewFakeGit()
	t0 := time.Now()
	g.AddCommit("origem1", "", "fix: ch255514 corrige logs", t0)
	g.AddCommit("base-tip", "", "base", t0)
	g.SetBranch("master", "origem1")
	g.SetBranch("13.6.0", "base-tip")
	g.SetBranch("13.7.0", "base-tip")
	if _, err := g.CherryPickX("origem1"); err != nil {
		t.Fatalf("setup: %v", err)
	}
	if err := g.WriteFile("13.7.0", "VERSAO.lock", []byte(`{
		"versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
		"tasks":{"255514":{"task":"VB-2354","titulo":"Logs","commits":["origem1"]}}
	}`), "lock inicial"); err != nil {
		t.Fatalf("setup: %v", err)
	}

	tasks := tasksource.NewFakeTaskSource()
	tasks.Tasks["13.7.0"] = []domain.TaskTarget{{Chamado: "255514", Task: "VB-2354", Titulo: "Logs"}}

	status, err := Verificar(Deps{Git: g, Tasks: tasks}, "13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if !status.Verde {
		t.Errorf("esperava verde, status = %+v", status)
	}
}

func TestVerificarFaltante(t *testing.T) {
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
	}`), "lock vazio"); err != nil {
		t.Fatalf("setup: %v", err)
	}

	tasks := tasksource.NewFakeTaskSource()
	tasks.Tasks["13.7.0"] = []domain.TaskTarget{{Chamado: "255514", Task: "VB-2354", Titulo: "Logs"}}

	status, err := Verificar(Deps{Git: g, Tasks: tasks}, "13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if status.Verde {
		t.Error("nao deveria ser verde")
	}
	if len(status.Faltantes) != 1 || status.Faltantes[0].HashOrigem != "origem1" {
		t.Errorf("Faltantes = %+v", status.Faltantes)
	}
}

// TestVerificarSumidoNuncaEntraEmConflitantes cobre o invariante documentado
// em domain.VersionStatus: Conflitantes e subconjunto de Faltantes (lado
// alvo), nunca de commits sumidos so-no-lock. Um commit ausente do git E do
// alvo atual nao e candidato real de cherry-pick, entao mesmo com uma previsao
// de conflito configurada pra ele, PredictMerge nao deveria nem ser chamado.
func TestVerificarSumidoNuncaEntraEmConflitantes(t *testing.T) {
	g := git.NewFakeGit()
	t0 := time.Now()
	g.AddCommit("origem1", "", "fix: ch255514 corrige logs", t0)
	g.AddCommit("base-tip", "", "base", t0)
	g.AddCommit("sumido1", "", "fix: ch999999 tarefa removida do clickup", t0)
	g.SetBranch("master", "origem1")
	g.SetBranch("13.6.0", "base-tip")
	g.SetBranch("13.7.0", "base-tip")
	if _, err := g.CherryPickX("origem1"); err != nil {
		t.Fatalf("setup: %v", err)
	}
	// sumido1 nunca foi cherry-picked pra branch nem esta mais no alvo do
	// ClickUp - so sobrevive no lock, exatamente o caso "sumido".
	if err := g.WriteFile("13.7.0", "VERSAO.lock", []byte(`{
		"versao":"13.7.0","tipo":"ajustada","base":{"ref":"13.6.0","commit":"base-tip"},
		"tasks":{
			"255514":{"task":"VB-2354","titulo":"Logs","commits":["origem1"]},
			"999999":{"task":"","titulo":"Removida","commits":["sumido1"]}
		}
	}`), "lock inicial"); err != nil {
		t.Fatalf("setup: %v", err)
	}
	g.MergePredictions["sumido1"] = ports.MergePrediction{Conflita: true}

	tasks := tasksource.NewFakeTaskSource()
	tasks.Tasks["13.7.0"] = []domain.TaskTarget{{Chamado: "255514", Task: "VB-2354", Titulo: "Logs"}}

	status, err := Verificar(Deps{Git: g, Tasks: tasks}, "13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if len(status.CommitsSumidos) != 1 || status.CommitsSumidos[0] != "sumido1" {
		t.Errorf("CommitsSumidos = %v, quer [sumido1]", status.CommitsSumidos)
	}
	for _, c := range status.Conflitantes {
		if c.HashOrigem == "sumido1" {
			t.Errorf("sumido1 nao deveria aparecer em Conflitantes: %+v", status.Conflitantes)
		}
	}
}
