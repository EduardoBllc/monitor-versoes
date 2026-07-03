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
	Conflita         bool
	ArquivosConflito []string
}

// GitRepo - conjunto enxuto (§14 do design). Metodos sem parametro `branch`
// operam sobre a worktree selecionada por WorktreeAdd/UseWorktree (ver desvio 6
// no topo deste plano).
type GitRepo interface {
	MergeBase(a, b string) (hash string, err error)
	IsAncestor(commit, branch string) (bool, error)
	SearchCommits(padroes []string, refs string) ([]domain.CommitRef, error)
	CommitsInRange(from, to string) ([]domain.CommitRef, error)
	CommitMeta(hash string) (domain.CommitRef, error)
	PatchID(hash string) (string, error)
	ResolveRef(ref string) (string, error)

	UseWorktree(branch string) error
	CherryPickX(hash string) (CherryPickOutcome, error)
	ConflictedPaths() ([]string, error)
	PendingCherryPick() (hash string, ok bool, err error)
	ContinueCherryPick() error
	AbortCherryPick() error

	PredictMerge(parent, branchTip, commit string) (MergePrediction, error)

	WorktreeAdd(branch, base string) error
	WorktreeRemove(branch string) error

	TagExists(tag string) (bool, error)
	RemoteBranchExists(remote, branch string) (bool, error)
	ListVersionBranches() ([]string, error)

	ReadFile(branch, path string) ([]byte, error)
	WriteFile(branch, path string, content []byte, mensagemCommit string) error
}
