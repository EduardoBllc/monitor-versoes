# Motor — transcrição 1-pra-1 Go → Python 3.14

> Port fiel do motor existente (Go, ~3300 LOC com testes, arquitetura hexagonal) para
> Python 3.14. **Não é redesenho**: mesma semântica, mesma estrutura de pacotes, mesmos
> testes. Racional e regras de negócio ficam em `ferramenta_versoes_design.md`; o contrato
> concreto é o **código `.go` atual** (não o `motor_go_spec.md`, que está desatualizado).

## Fonte da verdade

O `.go` real diverge do `motor_go_spec.md` em pontos que o port deve seguir:

- `engine.Verificar/Criar/Incrementar/...` recebem `engine.Deps`, **não** `repo string`.
- `IncrementResult` é achatado: campos `Status`, `BlockedCommit`, `ArquivosConflito`
  (não um `*ConflictSession`).
- `CommitRef` tem campo `Parent` (necessário pro `PredictMerge`).
- `TaskTarget` tem campo `Chamado` (chave externa).
- `ports.GitRepo` real é mais rico que o spec: inclui `CommitsInRange`, `ResolveRef`,
  `UseWorktree`, `PendingCherryPick`, `ListVersionBranches`, `PredictMerge`,
  `WorktreeAdd/Remove`.

Regra: quando spec e código divergirem, **o código vence**.

## Decisões (travadas)

1. **Fidelidade**: idiomática com estrutura espelhada. Mesma árvore de pacotes e mesma
   semântica, mas idiomas Python nativos (dataclasses, `typing.Protocol`, `IntEnum`,
   exceções no lugar de `(val, err)`).
2. **Dependências**: `pytest` (dev) + `httpx` (runtime). Resto stdlib (`subprocess`,
   `argparse`, `dataclasses`, `enum`, `datetime`, `json`, `urllib.parse`).
3. **Testes**: portar **todos** os `*_test.go` → `test_*.py`. Os testes são o oráculo de
   fidelidade — cada módulo só é dado como pronto quando seus testes portados passam.
4. **CLI**: `argparse` (espelho do `flag` da stdlib do Go; sem `click`/`typer`).
5. **Nomes de domínio em português** (`Criar`, `Verificar`, `Incrementar`, `Chamado`…)
   permanecem idênticos.

## Estrutura de arquivos

```
monitor-versoes/
  pyproject.toml              # runtime: httpx · [dev]: pytest   (substitui go.mod)
  motor/
    __init__.py
    __main__.py               # cmd/motor/main.go  → python -m motor
    domain/
      __init__.py
      types.py                # types.go   (dataclasses + IntEnum)
      version.py              # version.go (inferir_tipo, inferir_base)
      commits.py             # commits.go (match_exato, ordenar_por_data)
      reconcile.py            # reconcile.go (reconciliar, diff_tasks)
    ports.py                  # ports.go   (Protocols + MergePrediction/CherryPickOutcome)
    adapters/
      __init__.py
      git/
        __init__.py
        subprocess.py         # subprocess.go (GitSubprocess)
        fake.py               # fake.go (FakeGit)
      tasksource/
        __init__.py
        rest.py               # rest.go (ClickUpRest, via httpx)
        manuallist.py         # manuallist.go (ManualList)
        fake.py               # fake.go (FakeTaskSource)
    services/
      __init__.py
      target_resolver.py  presence_oracle.py  lock_store.py
      base_resolver.py    publication_gate.py
    engine/
      __init__.py
      deps.py                 # deps.go (Deps)
      criar.py  verificar.py  incrementar.py  reconstruir_lock.py
  tests/
    test_version.py  test_commits.py  test_reconcile.py
    test_git_fake.py  test_git_subprocess.py
    test_tasksource_rest.py  test_tasksource_manuallist.py  test_tasksource_fake.py
    test_target_resolver.py  test_presence_oracle.py  test_lock_store.py
    test_base_resolver.py    test_publication_gate.py
    test_criar.py  test_verificar.py  test_incrementar.py  test_reconstruir_lock.py
```

## Mapeamento de idiomas Go → Python

| Go | Python | Nota |
|---|---|---|
| `struct` (valor) | `@dataclass(frozen=True)` | `BaseRef`, `CommitRef`, `Version`, `Exclusion`, `TaskTarget`, `VersionStatus`, `Lock`, `MergePrediction` |
| `struct` (com deps) | `@dataclass` (mutável) | serviços: `LockStore(git=...)`, `TargetResolver(tasks=..., git=...)` |
| `interface` | `typing.Protocol` | `TaskSource`, `GitRepo`. Structural: some o `var _ = ...` do Go |
| `const iota` | `enum.IntEnum` | `VersionType`, `ExclusionReason`, `CherryPickOutcome`, `IncrementStatus`, `ReconstructStatus` |
| `(val, error)` | retorna `val`; erro = **exceção** | `raise MotorError(msg) from e` reproduz o `fmt.Errorf("...: %w", err)` |
| `map[string]X` | `dict[str, X]` | `TargetSet = dict[str, TaskTarget]` |
| `[]byte` | `bytes` | `read_file` / `write_file` |
| `time.Time` | `datetime.datetime` | `CommitRef.commit_date` |
| método `PascalCase` | `snake_case` | `Fetch→fetch`, `MergeBase→merge_base`, `CherryPickX→cherry_pick_x` |
| func de pacote | func de módulo | regras puras de `domain` |

**Erros**: uma única base `class MotorError(Exception)` (Go usa erro genérico; não vale
inventar hierarquia — YAGNI). Encadeamento com `raise ... from e`.

**Não são erros**: `Blocked`/`PendingJudgment` continuam **valores de retorno**
(`IncrementResult`, `ReconstructResult` como dataclasses), fiel ao invariante §14 de que o
engine nunca é interativo.

## CLI (`motor/__main__.py`)

Espelho fino do `main.go`, sem lógica própria: parseia, monta `Deps`, chama `engine`.

```
python -m motor verificar        <X.Y.Z> --repo <path>
python -m motor criar             <X.Y.Z> --repo <path> [--task-source=rest|manual --clickup-token=... --clickup-team=... --clickup-campo-chamado=...] [--lista=arquivo]
python -m motor incrementar      <X.Y.Z> --repo <path> [--continue | --abort]
python -m motor reconstruir-lock <X.Y.Z> --repo <path>
```

- `argparse` com subparsers (um por comando); `versao` é posicional.
- `--clickup-token` default = `os.environ.get("CLICKUP_TOKEN")` (nunca hard-coded).
- `--task-source=rest` → `ClickUpRest`; senão `ManualList`.
- Saída idêntica ao Go (`imprimir_status`, `imprimir_incremento`, `imprimir_uso`); erro →
  stderr + `sys.exit(1)`.

## Ordem de execução (bottom-up, cada módulo verde antes do próximo)

Snapshot inicial: rodar `go test ./...` uma vez pra registrar o comportamento esperado.

1. **Tooling**: `pyproject.toml`, config do pytest, skeleton de `__init__.py`.
2. **domain** + testes — puro, zero I/O.
3. **ports** (Protocols) — sem teste, só contrato.
4. **fakes** (`git/fake`, `tasksource/fake`) + testes — pré-requisito de service/engine.
5. **services** (5) + testes (usam fakes).
6. **engine** (deps + 4 operações) + testes (usam fakes).
7. **adapters reais**: `git/subprocess` + `tasksource/rest` + `manuallist` + testes.
8. **CLI** (`__main__.py`).
9. **Fecho**: `pytest` inteiro verde + smoke da CLI num repo de teste.

## Estratégia de teste (os 2 seams não-triviais)

- **`test_tasksource_rest`**: Go usa `httptest.Server` + injeção de `BaseURL`.
  Python → `httpx.MockTransport` num `httpx.Client(base_url=...)`. Sem subir servidor.
- **`test_git_subprocess`** (250 linhas, git real): Go cria repo temporário.
  Python → `tmp_path` do pytest + `subprocess` chamando `git`. Tradução direta, mesmos asserts.

## Fora de escopo

- `savedview.py` — não existe no Go ainda.
- Daemon / `cmd/daemon` — Etapa 2 do design.
- Qualquer lib interativa (`typer`, `rich`, `questionary`, `textual`) — migração futura,
   barata porque a CLI é fina. Fica com `argparse`.
- Remoção do código Go — decisão separada; o port convive com o Go durante a validação.
```

## Verificação de fidelidade

Port considerado correto quando: (a) `pytest` todo verde com os testes traduzidos 1-pra-1,
e (b) smoke manual da CLI (`python -m motor verificar ...`) contra um repo real produz a
mesma saída que o `motor` Go.
