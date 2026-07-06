package tasksource

import (
	"os"
	"path/filepath"
	"testing"
)

func TestManualListFetch(t *testing.T) {
	dir := t.TempDir()
	caminho := filepath.Join(dir, "lista.txt")
	conteudo := "# comentario\n255514;VB-2354;Logs pedidos ecommerce\n255074;VB-2391;Uappi status pedido\n"
	if err := os.WriteFile(caminho, []byte(conteudo), 0644); err != nil {
		t.Fatal(err)
	}

	fonte := ManualList{Caminho: caminho}
	tasks, err := fonte.Fetch("13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if len(tasks) != 2 || tasks[0].Chamado != "255514" || tasks[0].Task != "VB-2354" {
		t.Errorf("tasks = %+v", tasks)
	}
}

func TestManualListLinhaInvalida(t *testing.T) {
	dir := t.TempDir()
	caminho := filepath.Join(dir, "lista.txt")
	if err := os.WriteFile(caminho, []byte("linha sem separador\n"), 0644); err != nil {
		t.Fatal(err)
	}

	fonte := ManualList{Caminho: caminho}
	if _, err := fonte.Fetch("13.7.0"); err == nil {
		t.Error("esperava erro para linha invalida")
	}
}
