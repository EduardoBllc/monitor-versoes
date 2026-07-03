package domain

import "testing"

func TestInferirTipo(t *testing.T) {
	casos := []struct {
		numero string
		quer   VersionType
	}{
		{"14.0.0", VersionFechada},
		{"13.7.0", VersionAjustada},
		{"13.7.2", VersionCliente},
	}
	for _, c := range casos {
		got, err := InferirTipo(c.numero)
		if err != nil {
			t.Fatalf("InferirTipo(%q): erro inesperado: %v", c.numero, err)
		}
		if got != c.quer {
			t.Errorf("InferirTipo(%q) = %v, quer %v", c.numero, got, c.quer)
		}
	}
}

func TestInferirTipoInvalido(t *testing.T) {
	if _, err := InferirTipo("13.7"); err == nil {
		t.Error("esperava erro para formato invalido")
	}
}

func TestInferirBaseFechada(t *testing.T) {
	base, err := InferirBase("14.0.0", nil)
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if base != "master" {
		t.Errorf("base = %q, quer master", base)
	}
}

func TestInferirBaseAjustada(t *testing.T) {
	existentes := []string{"13.5.0", "13.6.0", "13.6.1"}
	base, err := InferirBase("13.7.0", existentes)
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if base != "13.6.0" {
		t.Errorf("base = %q, quer 13.6.0", base)
	}
}

func TestInferirBaseCliente(t *testing.T) {
	existentes := []string{"13.6.0", "13.6.1"}

	base, err := InferirBase("13.6.2", existentes)
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if base != "13.6.1" {
		t.Errorf("base = %q, quer 13.6.1", base)
	}

	base2, err := InferirBase("13.6.5", existentes) // 13.6.4 nao existe
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if base2 != "13.6.0" {
		t.Errorf("base = %q, quer 13.6.0", base2)
	}
}
