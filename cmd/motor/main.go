package main

import (
	"flag"
	"fmt"
	"os"

	"monitor-versoes/internal/adapters/git"
	"monitor-versoes/internal/adapters/tasksource"
	"monitor-versoes/internal/domain"
	"monitor-versoes/internal/engine"
	"monitor-versoes/internal/ports"
)

func main() {
	if len(os.Args) < 3 {
		imprimirUso()
		os.Exit(1)
	}

	comando := os.Args[1]
	versao := os.Args[2]

	fs := flag.NewFlagSet(comando, flag.ExitOnError)
	repo := fs.String("repo", "", "caminho do repositorio git (obrigatorio)")
	fonteFlag := fs.String("task-source", "manual", "rest|manual")
	listaManual := fs.String("lista", "", "arquivo da lista manual de chamados")
	token := fs.String("clickup-token", os.Getenv("CLICKUP_TOKEN"), "token da API do ClickUp")
	teamID := fs.String("clickup-team", "", "team id do ClickUp")
	campoChamado := fs.String("clickup-campo-chamado", "", "custom field id de 'Numero do chamado'")
	continuar := fs.Bool("continue", false, "continua incremento apos resolver conflito")
	abortar := fs.Bool("abort", false, "aborta incremento em conflito")
	fs.Parse(os.Args[3:])

	if *repo == "" {
		fmt.Fprintln(os.Stderr, "--repo e obrigatorio")
		os.Exit(1)
	}

	gitRepo, err := git.NewGitSubprocess(*repo)
	checar(err)

	var taskSource ports.TaskSource
	if *fonteFlag == "rest" {
		taskSource = tasksource.ClickUpRest{TeamID: *teamID, Token: *token, CampoChamadoID: *campoChamado}
	} else {
		taskSource = tasksource.ManualList{Caminho: *listaManual}
	}

	deps := engine.Deps{Git: gitRepo, Tasks: taskSource}

	switch comando {
	case "verificar":
		status, err := engine.Verificar(deps, versao)
		checar(err)
		imprimirStatus(status)
	case "criar":
		resultado, err := engine.Criar(deps, versao)
		checar(err)
		imprimirIncremento(resultado)
	case "incrementar":
		var resultado engine.IncrementResult
		switch {
		case *continuar:
			resultado, err = engine.IncrementarContinue(deps, versao)
		case *abortar:
			err = engine.IncrementarAbort(deps, versao)
		default:
			resultado, err = engine.Incrementar(deps, versao)
		}
		checar(err)
		if !*abortar {
			imprimirIncremento(resultado)
		}
	case "reconstruir-lock":
		resultado, err := engine.ReconstruirLock(deps, versao)
		checar(err)
		fmt.Printf("status: %v, orfaos: %d\n", resultado.Status, len(resultado.Orfaos))
	default:
		imprimirUso()
		os.Exit(1)
	}
}

func checar(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, "erro:", err)
		os.Exit(1)
	}
}

func imprimirUso() {
	fmt.Fprintln(os.Stderr, `uso:
  motor verificar        <X.Y.Z> --repo <path>
  motor criar             <X.Y.Z> --repo <path> [--task-source=rest|manual --clickup-token=... --clickup-team=... --clickup-campo-chamado=...] [--lista=arquivo]
  motor incrementar      <X.Y.Z> --repo <path> [--continue | --abort]
  motor reconstruir-lock <X.Y.Z> --repo <path>`)
}

func imprimirStatus(s domain.VersionStatus) {
	fmt.Printf("verde: %v\n", s.Verde)
	fmt.Printf("tasks novas: %v\n", s.TasksNovas)
	fmt.Printf("tasks removidas: %v\n", s.TasksRemovidas)
	fmt.Printf("lock integro: %v\n", s.LockIntegro)
	fmt.Printf("commits sumidos: %v\n", s.CommitsSumidos)
	fmt.Printf("faltantes: %d\n", len(s.Faltantes))
	fmt.Printf("conflitantes: %d\n", len(s.Conflitantes))
}

func imprimirIncremento(r engine.IncrementResult) {
	if r.Status == engine.StatusBlocked {
		fmt.Printf("BLOQUEADO em %s, arquivos: %v\n", r.BlockedCommit, r.ArquivosConflito)
		fmt.Println("resolva e rode: motor incrementar <versao> --repo <path> --continue")
		return
	}
	fmt.Println("concluido")
}
