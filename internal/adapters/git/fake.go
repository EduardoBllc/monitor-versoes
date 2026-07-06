package git

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"monitor-versoes/internal/domain"
	"monitor-versoes/internal/ports"
)

// FakeGit e um double em memoria de GitRepo, para testes de services/engine.
// Nao simula merge de verdade: conflitos e previsao de merge sao configurados
// explicitamente via os campos exportados abaixo.
type FakeGit struct {
	Commits  map[string]*FakeCommit
	Branches map[string]string
	Tags     map[string]bool
	Remotes  map[string]bool
	Files    map[string]map[string][]byte

	ConflictOn        map[string]bool
	MergePredictions  map[string]ports.MergePrediction
	CommitsInRangeErr error // fixture de teste: forca CommitsInRange a falhar (§2 fallback "ausente")

	currentBranch string
	pendingPick   string
	conflicted    []string
}

type FakeCommit struct {
	Hash       string
	Parent     string
	Msg        string
	Date       time.Time
	OrigemHash string // preenchido quando este commit foi criado via CherryPickX
}

func NewFakeGit() *FakeGit {
	return &FakeGit{
		Commits:          map[string]*FakeCommit{},
		Branches:         map[string]string{},
		Tags:             map[string]bool{},
		Remotes:          map[string]bool{},
		Files:            map[string]map[string][]byte{},
		ConflictOn:       map[string]bool{},
		MergePredictions: map[string]ports.MergePrediction{},
	}
}

// AddCommit registra um commit direto no grafo (fixture de teste).
func (g *FakeGit) AddCommit(hash, parent, msg string, date time.Time) {
	g.Commits[hash] = &FakeCommit{Hash: hash, Parent: parent, Msg: msg, Date: date}
}

// SetBranch posiciona o tip de uma branch e a torna a branch ativa (fixture de teste).
func (g *FakeGit) SetBranch(branch, hash string) {
	g.Branches[branch] = hash
	g.currentBranch = branch
}

func (g *FakeGit) MergeBase(a, b string) (string, error) {
	ancestorsOfA := map[string]bool{}
	h := g.resolveRefLocal(a)
	for h != "" {
		ancestorsOfA[h] = true
		c, ok := g.Commits[h]
		if !ok {
			break
		}
		h = c.Parent
	}

	h = g.resolveRefLocal(b)
	for h != "" {
		if ancestorsOfA[h] {
			return h, nil
		}
		c, ok := g.Commits[h]
		if !ok {
			break
		}
		h = c.Parent
	}
	return "", fmt.Errorf("merge-base nao encontrado entre %s e %s", a, b)
}

func (g *FakeGit) resolveRefLocal(ref string) string {
	if h, ok := g.Branches[ref]; ok {
		return h
	}
	return ref
}

func (g *FakeGit) IsAncestor(commit, branch string) (bool, error) {
	h := g.resolveRefLocal(branch)
	for h != "" {
		if h == commit {
			return true, nil
		}
		c, ok := g.Commits[h]
		if !ok {
			break
		}
		h = c.Parent
	}
	return false, nil
}

func (g *FakeGit) SearchCommits(padroes []string, refs string) ([]domain.CommitRef, error) {
	h := g.resolveRefLocal(refs)
	var resultado []domain.CommitRef
	for h != "" {
		c, ok := g.Commits[h]
		if !ok {
			break
		}
		for _, p := range padroes {
			if p != "" && strings.Contains(c.Msg, p) {
				resultado = append(resultado, domain.CommitRef{HashOrigem: c.Hash, Parent: c.Parent, Msg: c.Msg, CommitDate: c.Date})
				break
			}
		}
		h = c.Parent
	}
	return resultado, nil
}

func (g *FakeGit) CommitsInRange(from, to string) ([]domain.CommitRef, error) {
	if g.CommitsInRangeErr != nil {
		return nil, g.CommitsInRangeErr
	}
	stopAt := g.resolveRefLocal(from)
	h := g.resolveRefLocal(to)
	var resultado []domain.CommitRef
	for h != "" && h != stopAt {
		c, ok := g.Commits[h]
		if !ok {
			break
		}
		resultado = append(resultado, domain.CommitRef{HashOrigem: c.Hash, Parent: c.Parent, Msg: c.Msg, CommitDate: c.Date})
		h = c.Parent
	}
	return resultado, nil
}

func (g *FakeGit) CommitMeta(hash string) (domain.CommitRef, error) {
	c, ok := g.Commits[hash]
	if !ok {
		return domain.CommitRef{}, fmt.Errorf("commit %s nao encontrado", hash)
	}
	return domain.CommitRef{HashOrigem: c.Hash, Parent: c.Parent, Msg: c.Msg, CommitDate: c.Date}, nil
}

func (g *FakeGit) PatchID(hash string) (string, error) {
	if _, ok := g.Commits[hash]; !ok {
		return "", fmt.Errorf("commit %s nao encontrado", hash)
	}
	return "patchid-" + hash, nil
}

func (g *FakeGit) ResolveRef(ref string) (string, error) {
	if h, ok := g.Branches[ref]; ok {
		return h, nil
	}
	if _, ok := g.Commits[ref]; ok {
		return ref, nil
	}
	return "", fmt.Errorf("ref %s nao encontrada", ref)
}

func (g *FakeGit) UseWorktree(branch string) error {
	if _, ok := g.Branches[branch]; !ok {
		return fmt.Errorf("branch %s nao existe", branch)
	}
	g.currentBranch = branch
	return nil
}

func (g *FakeGit) CherryPickX(hash string) (ports.CherryPickOutcome, error) {
	origem, ok := g.Commits[hash]
	if !ok {
		return ports.Conflito, fmt.Errorf("commit %s nao encontrado", hash)
	}
	if g.ConflictOn[hash] {
		g.pendingPick = hash
		g.conflicted = []string{"arquivo-conflito.txt"}
		return ports.Conflito, nil
	}
	g.aplicarPick(origem)
	return ports.Aplicado, nil
}

func (g *FakeGit) aplicarPick(origem *FakeCommit) {
	novoHash := "pick-" + origem.Hash
	tip := g.Branches[g.currentBranch]
	g.Commits[novoHash] = &FakeCommit{
		Hash:       novoHash,
		Parent:     tip,
		Msg:        origem.Msg + fmt.Sprintf("\n\n(cherry picked from commit %s)", origem.Hash),
		Date:       origem.Date,
		OrigemHash: origem.Hash,
	}
	g.Branches[g.currentBranch] = novoHash
}

func (g *FakeGit) ConflictedPaths() ([]string, error) {
	return g.conflicted, nil
}

func (g *FakeGit) PendingCherryPick() (string, bool, error) {
	if g.pendingPick == "" {
		return "", false, nil
	}
	return g.pendingPick, true, nil
}

func (g *FakeGit) ContinueCherryPick() error {
	if g.pendingPick == "" {
		return fmt.Errorf("nenhum cherry-pick pendente")
	}
	origem := g.Commits[g.pendingPick]
	g.aplicarPick(origem)
	g.pendingPick = ""
	g.conflicted = nil
	return nil
}

func (g *FakeGit) AbortCherryPick() error {
	g.pendingPick = ""
	g.conflicted = nil
	return nil
}

func (g *FakeGit) PredictMerge(parent, branchTip, commit string) (ports.MergePrediction, error) {
	return g.MergePredictions[commit], nil
}

func (g *FakeGit) WorktreeAdd(branch, base string) error {
	if _, existe := g.Branches[branch]; existe {
		return fmt.Errorf("branch %s ja existe", branch)
	}
	g.Branches[branch] = g.resolveRefLocal(base)
	g.currentBranch = branch
	return nil
}

func (g *FakeGit) WorktreeRemove(branch string) error {
	delete(g.Branches, branch)
	return nil
}

func (g *FakeGit) TagExists(tag string) (bool, error) {
	return g.Tags[tag], nil
}

func (g *FakeGit) RemoteBranchExists(remote, branch string) (bool, error) {
	return g.Remotes[branch], nil
}

func (g *FakeGit) ListVersionBranches() ([]string, error) {
	var nomes []string
	for b := range g.Branches {
		nomes = append(nomes, b)
	}
	sort.Strings(nomes)
	return nomes, nil
}

func (g *FakeGit) ReadFile(branch, path string) ([]byte, error) {
	arquivos, ok := g.Files[branch]
	if !ok {
		return nil, fmt.Errorf("branch %s nao tem arquivos", branch)
	}
	conteudo, ok := arquivos[path]
	if !ok {
		return nil, fmt.Errorf("arquivo %s nao encontrado em %s", path, branch)
	}
	return conteudo, nil
}

func (g *FakeGit) WriteFile(branch, path string, content []byte, mensagemCommit string) error {
	if g.Files[branch] == nil {
		g.Files[branch] = map[string][]byte{}
	}
	g.Files[branch][path] = content
	return nil
}

var _ ports.GitRepo = (*FakeGit)(nil)
