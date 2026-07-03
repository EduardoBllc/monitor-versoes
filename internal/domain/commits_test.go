package domain

import (
	"testing"
	"time"
)

func TestMatchExatoEvitaSubstring(t *testing.T) {
	candidatos := []CommitRef{
		{HashOrigem: "aaa", Msg: "fix: ch255514 corrige logs"},
		{HashOrigem: "bbb", Msg: "fix: ch5514 outro chamado nao relacionado"},
	}
	resultado := MatchExato(candidatos, "255514", "")
	if len(resultado) != 1 || resultado[0].HashOrigem != "aaa" {
		t.Errorf("MatchExato deveria pegar so aaa, pegou %+v", resultado)
	}
}

func TestMatchExatoVBID(t *testing.T) {
	candidatos := []CommitRef{
		{HashOrigem: "ccc", Msg: "VB-2354: logs pedidos ecommerce"},
		{HashOrigem: "ddd", Msg: "nao relacionado VB-23540"},
	}
	resultado := MatchExato(candidatos, "", "VB-2354")
	if len(resultado) != 1 || resultado[0].HashOrigem != "ccc" {
		t.Errorf("MatchExato deveria pegar so ccc, pegou %+v", resultado)
	}
}

func TestExtrairChamado(t *testing.T) {
	chamado, ok := ExtrairChamado("fix: ch255514 corrige logs")
	if !ok || chamado != "255514" {
		t.Errorf("ExtrairChamado = %q, %v; quer 255514, true", chamado, ok)
	}
	if _, ok := ExtrairChamado("sem chamado nenhum"); ok {
		t.Error("nao deveria achar chamado")
	}
}

func TestExtrairVBID(t *testing.T) {
	vbID, ok := ExtrairVBID("VB-2354: logs pedidos ecommerce")
	if !ok || vbID != "VB-2354" {
		t.Errorf("ExtrairVBID = %q, %v; quer VB-2354, true", vbID, ok)
	}
}

func TestOrdenarPorData(t *testing.T) {
	t1 := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	t2 := time.Date(2024, 2, 1, 0, 0, 0, 0, time.UTC)
	t3 := time.Date(2024, 3, 1, 0, 0, 0, 0, time.UTC)
	entrada := []CommitRef{
		{HashOrigem: "c", CommitDate: t3},
		{HashOrigem: "a", CommitDate: t1},
		{HashOrigem: "b", CommitDate: t2},
	}
	resultado := OrdenarPorData(entrada)
	quer := []string{"a", "b", "c"}
	for i, hash := range quer {
		if resultado[i].HashOrigem != hash {
			t.Errorf("posicao %d = %s, quer %s", i, resultado[i].HashOrigem, hash)
		}
	}
	if entrada[0].HashOrigem != "c" {
		t.Error("OrdenarPorData nao deveria mutar a fatia de entrada")
	}
}
