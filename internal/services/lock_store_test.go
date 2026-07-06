package services

import (
	"testing"
	"time"

	"monitor-versoes/internal/adapters/git"
	"monitor-versoes/internal/domain"
)

func TestLockStoreEscreverELer(t *testing.T) {
	g := git.NewFakeGit()
	store := LockStore{Git: g}

	original := domain.Lock{
		Versao: "13.7.0",
		Tipo:   domain.VersionAjustada,
		Base:   domain.BaseRef{Ref: "13.6.0", Commit: "571fea583e"},
		Tasks: domain.TargetSet{
			"255514": {Chamado: "255514", Task: "VB-2354", Titulo: "Logs pedidos ecommerce",
				Commits: []domain.CommitRef{{HashOrigem: "d1a0ff9450"}}},
		},
		Excluidos: []domain.Exclusion{
			{Commit: "83cd5cb8a2", Chamado: "251099", Motivo: "ja presente na base 13.6.0"},
		},
	}

	if err := store.Escrever("13.7.0", original); err != nil {
		t.Fatalf("erro escrevendo: %v", err)
	}

	lido, err := store.Ler("13.7.0")
	if err != nil {
		t.Fatalf("erro lendo: %v", err)
	}

	if lido.Versao != "13.7.0" || lido.Tipo != domain.VersionAjustada {
		t.Errorf("lock lido = %+v", lido)
	}
	if lido.Base.Ref != "13.6.0" || lido.Base.Commit != "571fea583e" {
		t.Errorf("base lida = %+v", lido.Base)
	}
	tt, ok := lido.Tasks["255514"]
	if !ok || len(tt.Commits) != 1 || tt.Commits[0].HashOrigem != "d1a0ff9450" {
		t.Errorf("tasks lidas = %+v", lido.Tasks)
	}
	if len(lido.Excluidos) != 1 || lido.Excluidos[0].Commit != "83cd5cb8a2" {
		t.Errorf("excluidos lidos = %+v", lido.Excluidos)
	}
}

func TestLockStoreReconstruirReagrupaPorTrailer(t *testing.T) {
	g := git.NewFakeGit()
	t0 := time.Now()
	g.AddCommit("origem1", "", "fix: ch255514 corrige logs", t0)
	g.AddCommit("base-tip", "", "base", t0)
	g.SetBranch("13.6.0", "base-tip")
	g.SetBranch("13.7.0", "base-tip")
	if _, err := g.CherryPickX("origem1"); err != nil {
		t.Fatalf("setup: %v", err)
	}

	store := LockStore{Git: g}
	lock, orfaos, err := store.Reconstruir("13.7.0", domain.BaseRef{Ref: "13.6.0"}, "13.7.0", nil)
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if len(orfaos) != 0 {
		t.Errorf("orfaos = %+v, quer nenhum (sem lock anterior)", orfaos)
	}
	tt, ok := lock.Tasks["255514"]
	if !ok || len(tt.Commits) != 1 || tt.Commits[0].HashOrigem != "origem1" {
		t.Errorf("tasks reconstruidas = %+v", lock.Tasks)
	}
}

func TestLockStoreReconstruirRetornaOrfaosDeJulgamento(t *testing.T) {
	g := git.NewFakeGit()
	g.AddCommit("base-tip", "", "base", time.Now())
	g.SetBranch("13.6.0", "base-tip")
	g.SetBranch("13.7.0", "base-tip")

	anterior := domain.Lock{
		Excluidos: []domain.Exclusion{
			{Commit: "revertido1", Chamado: "999999", Motivo: "revertido depois", Reason: domain.ExclusaoJulgamento},
			{Commit: "auto1", Chamado: "888888", Motivo: "ja presente na base", Reason: domain.ExclusaoAutomatica},
		},
	}

	store := LockStore{Git: g}
	_, orfaos, err := store.Reconstruir("13.7.0", domain.BaseRef{Ref: "13.6.0"}, "13.7.0", &anterior)
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if len(orfaos) != 1 || orfaos[0].Commit != "revertido1" {
		t.Errorf("orfaos = %+v, quer so a exclusao por julgamento", orfaos)
	}
}

func TestLockStoreReconstruirOrdenaCommitsPorData(t *testing.T) {
	g := git.NewFakeGit()
	t0 := time.Now()
	t1 := t0.Add(time.Hour)
	g.AddCommit("origem1", "", "fix: ch255514 primeira parte", t0)
	g.AddCommit("origem2", "", "fix: ch255514 segunda parte", t1)
	g.AddCommit("base-tip", "", "base", t0)
	g.SetBranch("13.6.0", "base-tip")
	g.SetBranch("13.7.0", "base-tip")
	if _, err := g.CherryPickX("origem1"); err != nil {
		t.Fatalf("setup: %v", err)
	}
	if _, err := g.CherryPickX("origem2"); err != nil {
		t.Fatalf("setup: %v", err)
	}

	store := LockStore{Git: g}
	lock, _, err := store.Reconstruir("13.7.0", domain.BaseRef{Ref: "13.6.0"}, "13.7.0", nil)
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	commits := lock.Tasks["255514"].Commits
	if len(commits) != 2 {
		t.Fatalf("esperava 2 commits, veio %+v", commits)
	}
	if commits[0].HashOrigem != "origem1" || commits[1].HashOrigem != "origem2" {
		t.Errorf("ordem = [%s, %s], quer [origem1, origem2] (CommitDate asc)", commits[0].HashOrigem, commits[1].HashOrigem)
	}
}
