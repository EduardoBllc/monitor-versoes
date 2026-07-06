package git

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"monitor-versoes/internal/domain"
	"monitor-versoes/internal/ports"
)

type GitSubprocess struct {
	RepoPath      string
	currentBranch string
}

func NewGitSubprocess(repoPath string) (*GitSubprocess, error) {
	if err := checarVersaoGit(); err != nil {
		return nil, err
	}
	g := &GitSubprocess{RepoPath: repoPath}
	if err := g.run(repoPath, "config", "rerere.enabled", "true"); err != nil {
		return nil, err
	}
	if err := g.run(repoPath, "config", "rerere.autoUpdate", "true"); err != nil {
		return nil, err
	}
	return g, nil
}

func checarVersaoGit() error {
	out, err := exec.Command("git", "version").Output()
	if err != nil {
		return fmt.Errorf("git nao encontrado: %w", err)
	}
	major, minor, err := parseGitVersion(strings.TrimSpace(string(out)))
	if err != nil {
		return nil // formato inesperado - nao bloqueia, so nao valida
	}
	if major < 2 || (major == 2 && minor < 38) {
		return fmt.Errorf("git %d.%d encontrado, motor precisa de >= 2.38 (merge-tree --write-tree)", major, minor)
	}
	return nil
}

func parseGitVersion(saida string) (major, minor int, err error) {
	_, err = fmt.Sscanf(saida, "git version %d.%d", &major, &minor)
	return major, minor, err
}

func (g *GitSubprocess) run(dir string, args ...string) error {
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("git %s: %w: %s", strings.Join(args, " "), err, out)
	}
	return nil
}

func (g *GitSubprocess) output(dir string, args ...string) (string, error) {
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("git %s: %w", strings.Join(args, " "), err)
	}
	return strings.TrimSpace(string(out)), nil
}

func (g *GitSubprocess) worktreeDir(branch string) string {
	return filepath.Join(filepath.Dir(g.RepoPath), filepath.Base(g.RepoPath)+"-worktrees", branch)
}

func (g *GitSubprocess) MergeBase(a, b string) (string, error) {
	return g.output(g.RepoPath, "merge-base", a, b)
}

func (g *GitSubprocess) IsAncestor(commit, branch string) (bool, error) {
	cmd := exec.Command("git", "merge-base", "--is-ancestor", commit, branch)
	cmd.Dir = g.RepoPath
	err := cmd.Run()
	if err == nil {
		return true, nil
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) && exitErr.ExitCode() == 1 {
		return false, nil
	}
	return false, fmt.Errorf("git merge-base --is-ancestor: %w", err)
}

const separadorCampo = "\x1f"
const separadorRegistro = "\x1e"

func parseLog(out string) ([]domain.CommitRef, error) {
	if out == "" {
		return nil, nil
	}
	var resultado []domain.CommitRef
	for _, entrada := range strings.Split(out, separadorRegistro) {
		entrada = strings.Trim(entrada, "\n")
		if entrada == "" {
			continue
		}
		campos := strings.SplitN(entrada, separadorCampo, 3)
		if len(campos) != 3 {
			continue
		}
		data, err := time.Parse(time.RFC3339, campos[1])
		if err != nil {
			return nil, fmt.Errorf("parseando data do commit %s: %w", campos[0], err)
		}
		resultado = append(resultado, domain.CommitRef{HashOrigem: campos[0], CommitDate: data, Msg: campos[2]})
	}
	return resultado, nil
}

func (g *GitSubprocess) SearchCommits(padroes []string, refs string) ([]domain.CommitRef, error) {
	args := []string{"log", refs, "--format=%H" + separadorCampo + "%aI" + separadorCampo + "%B" + separadorRegistro}
	for _, p := range padroes {
		if p != "" {
			args = append(args, "--grep="+p)
		}
	}
	out, err := g.output(g.RepoPath, args...)
	if err != nil {
		return nil, err
	}
	return parseLog(out)
}

func (g *GitSubprocess) CommitsInRange(from, to string) ([]domain.CommitRef, error) {
	out, err := g.output(g.RepoPath, "log", from+".."+to,
		"--format=%H"+separadorCampo+"%aI"+separadorCampo+"%B"+separadorRegistro)
	if err != nil {
		return nil, err
	}
	return parseLog(out)
}

func (g *GitSubprocess) CommitMeta(hash string) (domain.CommitRef, error) {
	out, err := g.output(g.RepoPath, "show", "-s", "--format=%H"+separadorCampo+"%aI"+separadorCampo+"%B", hash)
	if err != nil {
		return domain.CommitRef{}, err
	}
	campos := strings.SplitN(out, separadorCampo, 3)
	if len(campos) != 3 {
		return domain.CommitRef{}, fmt.Errorf("saida inesperada de git show: %q", out)
	}
	data, err := time.Parse(time.RFC3339, campos[1])
	if err != nil {
		return domain.CommitRef{}, err
	}
	parent, err := g.output(g.RepoPath, "rev-parse", hash+"^")
	if err != nil {
		parent = ""
	}
	return domain.CommitRef{HashOrigem: campos[0], CommitDate: data, Msg: campos[2], Parent: parent}, nil
}

func (g *GitSubprocess) PatchID(hash string) (string, error) {
	showCmd := exec.Command("git", "show", hash)
	showCmd.Dir = g.RepoPath
	showOut, err := showCmd.StdoutPipe()
	if err != nil {
		return "", err
	}
	patchIDCmd := exec.Command("git", "patch-id", "--stable")
	patchIDCmd.Dir = g.RepoPath
	patchIDCmd.Stdin = showOut
	var buf bytes.Buffer
	patchIDCmd.Stdout = &buf

	if err := showCmd.Start(); err != nil {
		return "", err
	}
	if err := patchIDCmd.Start(); err != nil {
		return "", err
	}
	if err := showCmd.Wait(); err != nil {
		return "", err
	}
	if err := patchIDCmd.Wait(); err != nil {
		return "", err
	}
	campos := strings.Fields(buf.String())
	if len(campos) == 0 {
		return "", fmt.Errorf("patch-id vazio para %s", hash)
	}
	return campos[0], nil
}

func (g *GitSubprocess) ResolveRef(ref string) (string, error) {
	return g.output(g.RepoPath, "rev-parse", ref)
}

func (g *GitSubprocess) UseWorktree(branch string) error {
	dir := g.worktreeDir(branch)
	if _, err := os.Stat(dir); err != nil {
		return fmt.Errorf("worktree de %s nao encontrada em %s: %w", branch, dir, err)
	}
	g.currentBranch = branch
	return nil
}

func (g *GitSubprocess) CherryPickX(hash string) (ports.CherryPickOutcome, error) {
	dir := g.worktreeDir(g.currentBranch)
	cmd := exec.Command("git", "cherry-pick", "-x", hash)
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	if err == nil {
		return ports.Aplicado, nil
	}
	paths, pathErr := g.ConflictedPaths()
	if pathErr == nil && len(paths) > 0 {
		return ports.Conflito, nil
	}
	return ports.Conflito, fmt.Errorf("git cherry-pick -x %s: %w: %s", hash, err, out)
}

func (g *GitSubprocess) ConflictedPaths() ([]string, error) {
	dir := g.worktreeDir(g.currentBranch)
	out, err := g.output(dir, "diff", "--name-only", "--diff-filter=U")
	if err != nil {
		return nil, err
	}
	if out == "" {
		return nil, nil
	}
	return strings.Split(out, "\n"), nil
}

func (g *GitSubprocess) PendingCherryPick() (string, bool, error) {
	dir := g.worktreeDir(g.currentBranch)
	hash, err := g.output(dir, "rev-parse", "CHERRY_PICK_HEAD")
	if err != nil {
		return "", false, nil
	}
	return hash, true, nil
}

func (g *GitSubprocess) ContinueCherryPick() error {
	dir := g.worktreeDir(g.currentBranch)
	if err := g.run(dir, "add", "-A"); err != nil {
		return err
	}
	cmd := exec.Command("git", "cherry-pick", "--continue")
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), "GIT_EDITOR=true")
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("git cherry-pick --continue: %w: %s", err, out)
	}
	return nil
}

func (g *GitSubprocess) AbortCherryPick() error {
	return g.run(g.worktreeDir(g.currentBranch), "cherry-pick", "--abort")
}

func (g *GitSubprocess) PredictMerge(parent, branchTip, commit string) (ports.MergePrediction, error) {
	out, err := g.output(g.RepoPath, "merge-tree", "--write-tree", "--merge-base="+parent, branchTip, commit)
	if err != nil {
		return ports.MergePrediction{Conflita: true, ArquivosConflito: parseConflictFiles(out)}, nil
	}
	return ports.MergePrediction{Conflita: false}, nil
}

func parseConflictFiles(out string) []string {
	var arquivos []string
	for _, linha := range strings.Split(out, "\n") {
		if strings.Contains(linha, "CONFLICT") {
			arquivos = append(arquivos, linha)
		}
	}
	return arquivos
}

func (g *GitSubprocess) WorktreeAdd(branch, base string) error {
	dir := g.worktreeDir(branch)
	if err := g.run(g.RepoPath, "worktree", "add", "-b", branch, dir, base); err != nil {
		return err
	}
	g.currentBranch = branch
	return nil
}

func (g *GitSubprocess) WorktreeRemove(branch string) error {
	return g.run(g.RepoPath, "worktree", "remove", g.worktreeDir(branch))
}

func (g *GitSubprocess) TagExists(tag string) (bool, error) {
	out, err := g.output(g.RepoPath, "tag", "-l", tag)
	if err != nil {
		return false, err
	}
	return out != "", nil
}

func (g *GitSubprocess) RemoteBranchExists(remote, branch string) (bool, error) {
	out, err := g.output(g.RepoPath, "ls-remote", "--heads", remote, branch)
	if err != nil {
		return false, err
	}
	return out != "", nil
}

var padraoBranchVersao = regexp.MustCompile(`^\d+\.\d+\.\d+$`)

func (g *GitSubprocess) ListVersionBranches() ([]string, error) {
	out, err := g.output(g.RepoPath, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
	if err != nil {
		return nil, err
	}
	if out == "" {
		return nil, nil
	}
	var nomes []string
	for _, linha := range strings.Split(out, "\n") {
		if padraoBranchVersao.MatchString(linha) {
			nomes = append(nomes, linha)
		}
	}
	return nomes, nil
}

func (g *GitSubprocess) ReadFile(branch, path string) ([]byte, error) {
	cmd := exec.Command("git", "show", branch+":"+path)
	cmd.Dir = g.RepoPath
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("git show %s:%s: %w", branch, path, err)
	}
	return out, nil
}

func (g *GitSubprocess) WriteFile(branch, path string, content []byte, mensagemCommit string) error {
	dir := g.worktreeDir(branch)
	fullPath := filepath.Join(dir, path)
	if err := os.WriteFile(fullPath, content, 0644); err != nil {
		return err
	}
	if err := g.run(dir, "add", path); err != nil {
		return err
	}
	return g.run(dir, "commit", "-m", mensagemCommit)
}

var _ ports.GitRepo = (*GitSubprocess)(nil)
