package git

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"monitor-versoes/internal/ports"
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

// TestGitSubprocessWriteFileNoopQuandoConteudoIgual cobre o achado do teste
// e2e da tarefa 21: WriteFile grava, `git add` e comita sem checar se ha algo
// de fato staged. Quando o conteudo escrito e byte-identico ao ja commitado
// (ex: Criar grava o lock inicial, Incrementar tenta gravar o mesmo lock de
// novo por nao ter Faltantes), `git commit` sem --allow-empty falha com
// "nothing to commit, working tree clean" e aborta a operacao inteira.
func TestGitSubprocessWriteFileNoopQuandoConteudoIgual(t *testing.T) {
	repoDir := initRepoDeTeste(t)

	g, err := NewGitSubprocess(repoDir)
	if err != nil {
		t.Fatalf("NewGitSubprocess: %v", err)
	}
	if err := g.WorktreeAdd("13.8.0", "master"); err != nil {
		t.Fatalf("WorktreeAdd: %v", err)
	}

	if err := g.WriteFile("13.8.0", "VERSAO.lock", []byte("{}"), "lock inicial"); err != nil {
		t.Fatalf("1a WriteFile (primeiro commit do arquivo): %v", err)
	}
	primeiroHash, err := g.output(g.worktreeDir("13.8.0"), "rev-parse", "HEAD")
	if err != nil {
		t.Fatalf("rev-parse apos 1a WriteFile: %v", err)
	}

	// 2a chamada com o MESMO conteudo: nada staged apos o `git add`, entao
	// `git commit` deve ser evitado (sem --allow-empty ele falharia aqui).
	if err := g.WriteFile("13.8.0", "VERSAO.lock", []byte("{}"), "lock inalterado"); err != nil {
		t.Fatalf("2a WriteFile (mesmo conteudo, deveria ser no-op): %v", err)
	}
	segundoHash, err := g.output(g.worktreeDir("13.8.0"), "rev-parse", "HEAD")
	if err != nil {
		t.Fatalf("rev-parse apos 2a WriteFile: %v", err)
	}
	if segundoHash != primeiroHash {
		t.Errorf("2a WriteFile com conteudo igual criou commit novo: HEAD mudou de %s para %s", primeiroHash, segundoHash)
	}
	conteudo, err := g.ReadFile("13.8.0", "VERSAO.lock")
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	if string(conteudo) != "{}" {
		t.Errorf("conteudo = %q, quer {}", conteudo)
	}

	// 3a chamada com conteudo DIFERENTE: precisa gerar commit real, provando
	// que a checagem de "nada staged" nao suprime commits legitimos.
	if err := g.WriteFile("13.8.0", "VERSAO.lock", []byte(`{"v":1}`), "lock atualizado"); err != nil {
		t.Fatalf("3a WriteFile (conteudo diferente): %v", err)
	}
	terceiroHash, err := g.output(g.worktreeDir("13.8.0"), "rev-parse", "HEAD")
	if err != nil {
		t.Fatalf("rev-parse apos 3a WriteFile: %v", err)
	}
	if terceiroHash == segundoHash {
		t.Error("3a WriteFile com conteudo diferente nao criou commit novo")
	}
	conteudo3, err := g.ReadFile("13.8.0", "VERSAO.lock")
	if err != nil {
		t.Fatalf("ReadFile apos 3a WriteFile: %v", err)
	}
	if string(conteudo3) != `{"v":1}` {
		t.Errorf("conteudo apos 3a WriteFile = %q, quer {\"v\":1}", conteudo3)
	}
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

// TestGitSubprocessCherryPickXRerereAutoResolvido cobre o achado critico da
// revisao da tarefa 18: quando rerere.autoUpdate resolve e re-stagea o
// conflito sozinho, `git cherry-pick` ainda sai com erro (git nunca chama
// --continue por conta propria) e ConflictedPaths() fica vazio. CherryPickX
// precisa classificar isso como (Conflito, nil) - nao como erro - usando
// PendingCherryPick (CHERRY_PICK_HEAD) em vez de ConflictedPaths para decidir.
func TestGitSubprocessCherryPickXRerereAutoResolvido(t *testing.T) {
	dir := t.TempDir()
	run := func(gitDir string, args ...string) {
		cmd := exec.Command("git", args...)
		cmd.Dir = gitDir
		cmd.Env = append(os.Environ(),
			"GIT_AUTHOR_NAME=teste", "GIT_AUTHOR_EMAIL=teste@example.com",
			"GIT_COMMITTER_NAME=teste", "GIT_COMMITTER_EMAIL=teste@example.com")
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v (dir=%s): %v: %s", args, gitDir, err, out)
		}
	}
	run(dir, "init", "-b", "master")
	if err := os.WriteFile(filepath.Join(dir, "arquivo.txt"), []byte("linha1\nlinha2\nlinha3\n"), 0644); err != nil {
		t.Fatal(err)
	}
	run(dir, "add", "arquivo.txt")
	run(dir, "commit", "-m", "base")

	g, err := NewGitSubprocess(dir)
	if err != nil {
		t.Fatalf("NewGitSubprocess: %v", err)
	}
	baseHash, err := g.ResolveRef("master")
	if err != nil {
		t.Fatalf("ResolveRef base: %v", err)
	}

	if err := os.WriteFile(filepath.Join(dir, "arquivo.txt"), []byte("linha1\nlinha2-X\nlinha3\n"), 0644); err != nil {
		t.Fatal(err)
	}
	run(dir, "add", "arquivo.txt")
	run(dir, "commit", "-m", "muda linha2 para X")
	commitX, err := g.ResolveRef("master")
	if err != nil {
		t.Fatalf("ResolveRef commitX: %v", err)
	}

	// 1a tentativa: conflito real, resolvido a mao - grava a resolucao no rerere.
	if err := g.WorktreeAdd("13.7.0", baseHash); err != nil {
		t.Fatalf("WorktreeAdd 13.7.0: %v", err)
	}
	if err := g.WriteFile("13.7.0", "arquivo.txt", []byte("linha1\nlinha2-Y\nlinha3\n"), "muda linha2 para Y"); err != nil {
		t.Fatalf("WriteFile 13.7.0: %v", err)
	}

	outcome, err := g.CherryPickX(commitX)
	if err != nil {
		t.Fatalf("CherryPickX (1a tentativa): %v", err)
	}
	if outcome != ports.Conflito {
		t.Fatalf("outcome = %v, quer Conflito", outcome)
	}
	paths, err := g.ConflictedPaths()
	if err != nil {
		t.Fatalf("ConflictedPaths (1a tentativa): %v", err)
	}
	if len(paths) == 0 {
		t.Fatal("esperava conflito real com arquivo ainda nao resolvido")
	}

	if err := os.WriteFile(filepath.Join(g.worktreeDir("13.7.0"), "arquivo.txt"), []byte("linha1\nlinha2-X\nlinha3\n"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := g.ContinueCherryPick(); err != nil {
		t.Fatalf("ContinueCherryPick (1a tentativa): %v", err)
	}

	// 2a tentativa: mesmo conflito em branch equivalente - rerere.autoUpdate
	// deve resolver e re-stagear o arquivo sozinho, mas o cherry-pick continua
	// pendente (git nao chama --continue por conta propria).
	if err := g.WorktreeAdd("13.7.1", baseHash); err != nil {
		t.Fatalf("WorktreeAdd 13.7.1: %v", err)
	}
	if err := g.WriteFile("13.7.1", "arquivo.txt", []byte("linha1\nlinha2-Y\nlinha3\n"), "muda linha2 para Y"); err != nil {
		t.Fatalf("WriteFile 13.7.1: %v", err)
	}

	outcome2, err := g.CherryPickX(commitX)
	if err != nil {
		t.Fatalf("CherryPickX (2a tentativa, rerere deveria ter resolvido sozinho): %v", err)
	}
	if outcome2 != ports.Conflito {
		t.Fatalf("outcome2 = %v, quer Conflito (git ainda espera --continue mesmo com rerere resolvendo)", outcome2)
	}
	paths2, err := g.ConflictedPaths()
	if err != nil {
		t.Fatalf("ConflictedPaths (2a tentativa): %v", err)
	}
	if len(paths2) != 0 {
		t.Fatalf("esperava rerere ter resolvido e deixado ConflictedPaths vazio, veio %v", paths2)
	}
	if _, pendente, err := g.PendingCherryPick(); err != nil || !pendente {
		t.Fatalf("esperava cherry-pick pendente apos rerere auto-resolver: pendente=%v err=%v", pendente, err)
	}

	if err := g.ContinueCherryPick(); err != nil {
		t.Fatalf("ContinueCherryPick (2a tentativa): %v", err)
	}
}
