package git

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func initRepoDeTeste(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	run := func(args ...string) {
		cmd := exec.Command("git", args...)
		cmd.Dir = dir
		cmd.Env = append(os.Environ(),
			"GIT_AUTHOR_NAME=teste", "GIT_AUTHOR_EMAIL=teste@example.com",
			"GIT_COMMITTER_NAME=teste", "GIT_COMMITTER_EMAIL=teste@example.com")
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v: %s", args, err, out)
		}
	}
	run("init", "-b", "master")
	if err := os.WriteFile(filepath.Join(dir, "arquivo.txt"), []byte("v1\n"), 0644); err != nil {
		t.Fatal(err)
	}
	run("add", "arquivo.txt")
	run("commit", "-m", "fix: ch255514 corrige logs")
	return dir
}

func TestGitSubprocessWorktreeCherryPickEArquivo(t *testing.T) {
	repoDir := initRepoDeTeste(t)

	g, err := NewGitSubprocess(repoDir)
	if err != nil {
		t.Fatalf("NewGitSubprocess: %v", err)
	}

	tip, err := g.ResolveRef("master")
	if err != nil {
		t.Fatalf("ResolveRef: %v", err)
	}

	if err := g.WorktreeAdd("13.7.0", "master"); err != nil {
		t.Fatalf("WorktreeAdd: %v", err)
	}

	if err := g.WriteFile("13.7.0", "VERSAO.lock", []byte("{}"), "lock inicial"); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	conteudo, err := g.ReadFile("13.7.0", "VERSAO.lock")
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	if string(conteudo) != "{}" {
		t.Errorf("conteudo = %q, quer {}", conteudo)
	}

	ok, err := g.IsAncestor(tip, "13.7.0")
	if err != nil {
		t.Fatalf("IsAncestor: %v", err)
	}
	if !ok {
		t.Error("esperava tip de master como ancestral de 13.7.0")
	}

	existe, err := g.TagExists("13.7.0")
	if err != nil {
		t.Fatalf("TagExists: %v", err)
	}
	if existe {
		t.Error("nao esperava tag 13.7.0 ainda")
	}
}
