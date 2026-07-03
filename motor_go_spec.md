# Motor — spec de implementação (Go)

> Cobre a **Etapa 1** de `ferramenta_versoes_design.md` (§13): motor + CLI fino, sem daemon.
> Racional e decisões de desenho ficam lá — aqui só o contrato final em Go: pacotes, tipos,
> interfaces, assinaturas. Ports-e-adaptadores conforme §14.

## 1. Estrutura de pacotes

```
monitor-versoes/
  go.mod
  cmd/
    motor/
      main.go                 # CLI fino: parseia flags, chama internal/engine
  internal/
    domain/                   # tipos + regras puras, zero I/O (§14 Domínio)
    ports/                    # TaskSource, GitRepo (interfaces, §14 Portas)
    adapters/
      git/
        subprocess.go         # GitSubprocess: implementa GitRepo via os/exec
        fake.go                # FakeGit: implementação em memória p/ testes
      tasksource/
        rest.go                # ClickUpRest: API REST c/ token
        savedview.go           # SavedView: lê view salva do ClickUp
        manuallist.go          # ManualList: lista de chamados passada via flag/arquivo
        fake.go                # FakeTaskSource: p/ testes
    services/                 # TargetResolver, PresenceOracle, LockStore,
                               # BaseResolver, PublicationGate, ConflictSession (§14)
    engine/                    # Operações: Criar, Verificar, Incrementar, ReconstruirLock
```

`internal/` porque só o `cmd/motor` (e, na Etapa 2, um `cmd/daemon` no mesmo módulo) consome —
sem necessidade de expor como biblioteca pública ainda.

## 2. Domínio (`internal/domain`) — puro, zero I/O

```go
package domain

import "time"

type VersionType int

const (
	VersionFechada VersionType = iota // X.0.0
	VersionAjustada                   // X.Y.0
	VersionCliente                    // X.Y.Z
)

type BaseRef struct {
	Ref    string // "13.6.0"
	Commit string // hash
}

type Version struct {
	Numero string // "13.7.0"
	Tipo   VersionType
	Base   BaseRef
}

type CommitRef struct {
	HashOrigem string
	Chamado    string // "255514"
	Task       string // "VB-2354"
	CommitDate time.Time
	Msg        string
}

type TaskTarget struct {
	Task    string
	Titulo  string
	Commits []CommitRef
}

// TargetSet = task→commits resolvido (§4). Chave = chamado.
type TargetSet map[string]TaskTarget

type ExclusionReason int

const (
	ExclusaoAutomatica ExclusionReason = iota // recomputável via Presente()
	ExclusaoJulgamento                        // irredutível, só existe no lock
)

type Exclusion struct {
	Commit  string
	Chamado string
	Motivo  string
	Reason  ExclusionReason
}

type Lock struct {
	Versao    string
	Tipo      VersionType
	Base      BaseRef
	Tasks     TargetSet
	Excluidos []Exclusion
}

type VersionStatus struct {
	Verde          bool
	TasksNovas     []string // em ClickUp, fora do lock
	TasksRemovidas []string // no lock, fora do ClickUp
	LockIntegro    bool
	CommitsSumidos []string // no lock, ausentes no git
	Faltantes      []CommitRef
	Conflitantes   []CommitRef // subconjunto de Faltantes que dá conflito (merge-tree)
}
```

### Regras puras (funções, não métodos — testáveis sem fake nenhum)

```go
package domain

func InferirTipo(numero string) VersionType
func InferirBase(numero string, versoesExistentes []string) (ref string, err error) // §7

// MatchExato filtra candidatos de grep por word-boundary — ch<num> e VB-<num> exatos,
// não substring (§4 "Precisão do match"). search_commits do GitRepo só traz candidatos brutos.
func MatchExato(candidatos []CommitRef, chamado, vbID string) []CommitRef

// OrdenarPorData ordena por CommitDate asc — não depende de flag do git (§5 "Ordenação").
func OrdenarPorData(commits []CommitRef) []CommitRef

// Reconciliar cruza as 3 fontes (§2, §9) e produz o VersionStatus.
func Reconciliar(alvo TargetSet, lock Lock, presentes map[string]bool, conflitantes []CommitRef) VersionStatus

// DiffTarget vs Lock — tasks novas/removidas (Δ simétrica, §5).
func DiffTasks(alvo, lockTasks TargetSet) (novas, removidas []string)
```

## 3. Portas (`internal/ports`) — as 2 únicas fronteiras com o mundo (§14)

```go
package ports

import "monitor-versoes/internal/domain"

type TaskSource interface {
	Fetch(versao string) ([]domain.TaskTarget, error)
}

type CherryPickOutcome int

const (
	Aplicado CherryPickOutcome = iota
	Conflito
)

type MergePrediction struct {
	Conflita          bool
	ArquivosConflito  []string
}

// GitRepo — conjunto enxuto (§14). Toda chamada é síncrona; contexto/timeout fica
// por conta do adapter, não da interface.
type GitRepo interface {
	MergeBase(a, b string) (hash string, err error)
	IsAncestor(commit, branch string) (bool, error)
	SearchCommits(padroes []string, refs string) ([]domain.CommitRef, error)
	CommitMeta(hash string) (domain.CommitRef, error)
	PatchID(hash string) (string, error)

	CherryPickX(hash string) (CherryPickOutcome, error)
	ConflictedPaths() ([]string, error) // git diff --name-only --diff-filter=U
	ContinueCherryPick() error
	AbortCherryPick() error

	PredictMerge(parent, branchTip, commit string) (MergePrediction, error)

	WorktreeAdd(branch, base string) error
	WorktreeRemove(branch string) error

	TagExists(tag string) (bool, error)
	RemoteBranchExists(remote, branch string) (bool, error)

	ReadFile(branch, path string) ([]byte, error)
	WriteFile(branch, path string, content []byte, mensagemCommit string) error
}
```

`ConflictedPaths` existe porque `rerere.autoUpdate=true` (§8) resolve e stageia sozinho quando
bate 100% — o jeito de saber se "resolveu automaticamente" é checar se ainda sobra caminho
não mergeado, não inferir do retorno do `rerere` em si.

## 4. Adapters

- **`adapters/git/subprocess.go`** — `GitSubprocess` implementa `GitRepo` via `os/exec`.
  Assume `rerere.enabled=true` e `rerere.autoUpdate=true` já configurados no repo (checado/
  setado uma vez em `Criar`, não a cada chamada).
- **`adapters/git/fake.go`** — `FakeGit`: grafo de commits em memória (mapa hash→pais/trailer),
  sem shell nenhum. É o que os testes de `services`/`engine` usam.
- **`adapters/tasksource/{rest,savedview,manuallist}.go`** — os 3 adapters do §4. `rest.go` é o
  único capaz de filtro determinístico (precisa de token via env var `CLICKUP_TOKEN`).
- **`adapters/tasksource/fake.go`** — `FakeTaskSource`: retorna `[]domain.TaskTarget` fixo.

## 5. Serviços (`internal/services`)

```go
package services

type TargetResolver struct {
	Tasks ports.TaskSource
	Git   ports.GitRepo
}
func (r TargetResolver) Resolve(versao string) (domain.TargetSet, error)
// Busca candidatos com Git.SearchCommits(refs="master"), aplica domain.MatchExato.
// Desambiguação multi-projeto (§11) é implícita: só entram commits que SearchCommits achou
// *neste* repo.

type PresenceOracle struct{ Git ports.GitRepo }
func (o PresenceOracle) Presente(hashOrigem, branch string) (bool, error)
// hash-ancestral → trailer (git log --grep) → patch-id, nessa ordem (§2).

type LockStore struct{ Git ports.GitRepo }
func (s LockStore) Ler(branch string) (domain.Lock, error)
func (s LockStore) Escrever(branch string, lock domain.Lock) error
func (s LockStore) Reconstruir(branch string) (domain.Lock, orfaos []domain.Exclusion, err error)

type BaseResolver struct{ Git ports.GitRepo }
func (r BaseResolver) Resolve(numero string) (domain.BaseRef, error) // §7

type PublicationGate struct{ Git ports.GitRepo }
func (g PublicationGate) Publicada(versao string) (bool, error) // tag_exists || remote_branch_exists (§6)

// ConflictSession — estado resumível de um cherry-pick em conflito (§8).
type ConflictSession struct {
	Commit           string
	ArquivosConflito []string
}
```

## 6. Operações (`internal/engine`) — API que `cmd/motor` chama

```go
package engine

type IncrementStatus int

const (
	StatusDone IncrementStatus = iota
	StatusBlocked
)

type IncrementResult struct {
	Status  IncrementStatus
	Blocked *services.ConflictSession // não-nil só se Status == StatusBlocked
}

type ReconstructStatus int

const (
	ReconstructDone ReconstructStatus = iota
	ReconstructPendingJudgment
)

type ReconstructResult struct {
	Status ReconstructStatus
	Orfaos []domain.Exclusion // não-vazio só se Status == ReconstructPendingJudgment
}

func Verificar(repo string, versao string) (domain.VersionStatus, error)
func Criar(repo string, versao string) (IncrementResult, error)
func Incrementar(repo string, versao string) (IncrementResult, error)
func IncrementarContinue(repo string, versao string) (IncrementResult, error) // após resolver manualmente
func IncrementarAbort(repo string, versao string) error
func ReconstruirLock(repo string, versao string) (ReconstructResult, error)
```

Nenhuma operação pergunta nada — **nunca interativa** (§14 invariante). `Blocked`/
`PendingJudgment` são valores de retorno; quem decide o próximo passo é o `cmd/motor` (ou, na
Etapa 2/3, o daemon).

## 7. CLI (`cmd/motor`) — fino, sem lógica própria

```
motor verificar   <X.Y.Z> --repo <path>
motor criar        <X.Y.Z> --repo <path> [--task-source=rest|view|manual --clickup-token=...]
motor incrementar <X.Y.Z> --repo <path> [--continue | --abort]
motor reconstruir-lock <X.Y.Z> --repo <path>
```

`flag` da stdlib basta — sem `cobra`/`urfave-cli` (uma dependência a menos pra 4 subcomandos).
`--repo` seleciona o projeto (§11); sem flag de config por projeto, por decisão do §11.

## 8. Testes

Tudo em `internal/domain` e `internal/services` é testável com `testing` da stdlib +
`FakeGit`/`FakeTaskSource` — sem repo real, sem rede, sem framework de teste. Tabela mínima por
pacote:

- `domain`: `MatchExato` (caso de substring, ex. `5514` vs `255514`), `OrdenarPorData`,
  `Reconciliar` (as 5 linhas da tabela do §9), `InferirBase` (os 3 casos do §7).
- `services`: `PresenceOracle.Presente` (os 3 níveis do §2) contra um `FakeGit` com grafo
  fabricado; `PublicationGate.Publicada` (tag local / branch remota / nenhum).
- `engine`: `Incrementar` feliz (aplica tudo) e com conflito (`FakeGit` simula conflito em um
  commit específico) → confere que devolve `StatusBlocked` com o commit certo.

Só o `adapters/git/subprocess.go` fica sem teste automatizado de unidade (é I/O real) — cobertura
ali é manual/smoke, rodando contra um repo de teste local.

## 9. Execução / config

- `git config rerere.enabled true && git config rerere.autoUpdate true` — setado por `Criar`
  na primeira vez que a worktree da versão é criada (§8).
- Token do ClickUp via env var `CLICKUP_TOKEN` (nunca em flag, evita ficar no shell history).
- Git do sistema precisa ser ≥ 2.38 (requisito do `merge-tree --write-tree`, §5) — `motor` pode
  checar `git version` no arranque e falhar cedo com mensagem clara se for mais antigo.
