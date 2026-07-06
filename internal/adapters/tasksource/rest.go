package tasksource

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"

	"monitor-versoes/internal/domain"
	"monitor-versoes/internal/ports"
)

// ClickUpRest usa a API "Filter Team Tasks" (GET /team/{team_id}/task) com
// filtro por custom_fields - unico adapter deterministico (§4). BaseURL
// configuravel pra apontar num httptest.Server nos testes.
type ClickUpRest struct {
	BaseURL        string // default: "https://api.clickup.com/api/v2"
	TeamID         string
	Token          string
	CampoChamadoID string // custom field "Numero do chamado" - confirmar ID real no ClickUp
	Client         *http.Client
}

const campoVersaoDestino = "de0124a4-a15d-401e-ab48-417803082562"

type clickUpCustomField struct {
	ID    string      `json:"id"`
	Value interface{} `json:"value"`
}

type clickUpTask struct {
	ID           string               `json:"id"`
	Name         string               `json:"name"`
	CustomID     string               `json:"custom_id"`
	CustomFields []clickUpCustomField `json:"custom_fields"`
}

type clickUpResposta struct {
	Tasks []clickUpTask `json:"tasks"`
}

func (c ClickUpRest) Fetch(versao string) ([]domain.TaskTarget, error) {
	client := c.Client
	if client == nil {
		client = http.DefaultClient
	}
	baseURL := c.BaseURL
	if baseURL == "" {
		baseURL = "https://api.clickup.com/api/v2"
	}

	filtro := fmt.Sprintf(`[{"field_id":%q,"operator":"=","value":%q}]`, campoVersaoDestino, versao)
	u := fmt.Sprintf("%s/team/%s/task?custom_fields=%s", baseURL, c.TeamID, url.QueryEscape(filtro))

	req, err := http.NewRequest(http.MethodGet, u, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", c.Token)

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("chamando ClickUp: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("ClickUp respondeu %d", resp.StatusCode)
	}

	var corpo clickUpResposta
	if err := json.NewDecoder(resp.Body).Decode(&corpo); err != nil {
		return nil, fmt.Errorf("decodificando resposta do ClickUp: %w", err)
	}

	var tasks []domain.TaskTarget
	for _, t := range corpo.Tasks {
		tasks = append(tasks, domain.TaskTarget{
			Chamado: extrairCampoChamado(t.CustomFields, c.CampoChamadoID),
			Task:    t.CustomID,
			Titulo:  t.Name,
		})
	}
	return tasks, nil
}

func extrairCampoChamado(campos []clickUpCustomField, campoID string) string {
	for _, c := range campos {
		if c.ID == campoID {
			if s, ok := c.Value.(string); ok {
				return s
			}
		}
	}
	return ""
}

var _ ports.TaskSource = ClickUpRest{}
