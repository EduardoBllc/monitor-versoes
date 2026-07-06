package tasksource

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"monitor-versoes/internal/domain"
	"monitor-versoes/internal/ports"
)

// ManualList le um arquivo texto com uma task por linha:
// "chamado;VB-xxxx;titulo". Fallback sempre disponivel quando a API do
// ClickUp nao esta acessivel (§4).
type ManualList struct {
	Caminho string
}

func (m ManualList) Fetch(versao string) ([]domain.TaskTarget, error) {
	f, err := os.Open(m.Caminho)
	if err != nil {
		return nil, fmt.Errorf("abrindo lista manual %s: %w", m.Caminho, err)
	}
	defer f.Close()

	var tasks []domain.TaskTarget
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		linha := strings.TrimSpace(scanner.Text())
		if linha == "" || strings.HasPrefix(linha, "#") {
			continue
		}
		campos := strings.SplitN(linha, ";", 3)
		if len(campos) < 2 {
			return nil, fmt.Errorf("linha invalida em %s: %q (esperado chamado;VB-xxxx;titulo)", m.Caminho, linha)
		}
		titulo := ""
		if len(campos) == 3 {
			titulo = campos[2]
		}
		tasks = append(tasks, domain.TaskTarget{Chamado: campos[0], Task: campos[1], Titulo: titulo})
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return tasks, nil
}

var _ ports.TaskSource = ManualList{}
