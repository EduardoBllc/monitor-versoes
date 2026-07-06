package tasksource

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestClickUpRestFetch(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "tok123" {
			t.Errorf("token nao propagado, header = %q", r.Header.Get("Authorization"))
		}
		resposta := map[string]interface{}{
			"tasks": []map[string]interface{}{
				{
					"id": "1", "name": "Logs pedidos ecommerce", "custom_id": "VB-2354",
					"custom_fields": []map[string]interface{}{
						{"id": "campo-chamado", "value": "255514"},
					},
				},
			},
		}
		json.NewEncoder(w).Encode(resposta)
	}))
	defer server.Close()

	fonte := ClickUpRest{BaseURL: server.URL, TeamID: "999", Token: "tok123", CampoChamadoID: "campo-chamado"}
	tasks, err := fonte.Fetch("13.7.0")
	if err != nil {
		t.Fatalf("erro inesperado: %v", err)
	}
	if len(tasks) != 1 || tasks[0].Chamado != "255514" || tasks[0].Task != "VB-2354" {
		t.Errorf("tasks = %+v", tasks)
	}
}

func TestClickUpRestErroHTTP(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
	}))
	defer server.Close()

	fonte := ClickUpRest{BaseURL: server.URL, TeamID: "999", Token: "invalido"}
	if _, err := fonte.Fetch("13.7.0"); err == nil {
		t.Error("esperava erro com 401")
	}
}
