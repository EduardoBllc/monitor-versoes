# Motor — transcrição Go → Python 3.14 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transcrever 1-pra-1 o motor em Go (~3300 LOC, hexagonal) para Python 3.14, preservando semântica, estrutura de pacotes e todos os testes.

**Architecture:** Port idiomático com estrutura espelhada. Domínio puro (dataclasses + funções), portas como `typing.Protocol`, adapters (git via `subprocess`, ClickUp via `httpx`), serviços, engine, e CLI fina com `argparse`. Erro Go `(val, err)` vira exceção `MotorError`; `Blocked`/`PendingJudgment` continuam valores de retorno.

**Tech Stack:** Python 3.14 · stdlib (`subprocess`, `argparse`, `dataclasses`, `enum`, `datetime`, `json`, `re`, `urllib.parse`) · `httpx` (runtime) · `pytest` (dev).

## Abordagem de transcrição (ler antes de tudo)

O **código `.go` atual é o contrato** — não o `motor_go_spec.md`, que está desatualizado. Cada tarefa mapeia arquivos `.go` de origem para `.py` de destino. O **passo 1 de todo port de arquivo é: ler o `.go` de origem inteiro** e traduzir preservando a semântica, aplicando a tabela de idiomas abaixo. Os **testes portados são o oráculo**: um módulo só está pronto quando seus testes passam. As armadilhas de tradução por arquivo (onde um port ingênuo erra) estão em cada tarefa.

### Tabela de idiomas Go → Python (vale pra todas as tarefas)

| Go | Python |
|---|---|
| `struct` valor | `@dataclass(frozen=True)`; campos slice → `field(default_factory=list)`, string → `= ""` |
| `struct` com deps | `@dataclass` mutável (ex.: `LockStore(git=...)`) |
| `interface` | `typing.Protocol` (structural; some o `var _ = ...`) |
| `const iota` | `enum.IntEnum` (a ordem 0,1,2 importa) |
| retorno `(val, error)` | retorna `val`; erro vira `raise MotorError(msg) from e` |
| retorno `(val, ok bool)` | retorna `val | None` (ok=False → `None`) |
| `map[string]X` | `dict[str, X]` |
| `[]byte` | `bytes` |
| `time.Time` | `datetime.datetime` |
| método `PascalCase` | `snake_case` (`Fetch`→`fetch`, `CherryPickX`→`cherry_pick_x`) |
| campo `PascalCase` | `snake_case` (`HashOrigem`→`hash_origem`, `CommitDate`→`commit_date`) |
| `regexp.QuoteMeta` | `re.escape` |
| `url.QueryEscape` | `urllib.parse.quote` |
| `fmt.Errorf("...: %w", e)` | `raise MotorError("...") from e` |

## Global Constraints

- Python **3.14** (usa `X | None`, `list[T]`, `dict[K,V]` nativos — sem `typing.List`).
- Runtime depende só de `httpx` + stdlib. `pytest` é dependência **só de dev**.
- Nomes de domínio em **português** permanecem (`criar`, `verificar`, `incrementar`, `chamado`, `titulo`, `excluidos`…).
- Nada interativo no engine (invariante §14): `Blocked`/`PendingJudgment` são valores de retorno, nunca prompts.
- Toda tradução de erro usa a base única `motor.errors.MotorError`.
- Token do ClickUp nunca hard-coded: default lido de `os.environ["CLICKUP_TOKEN"]`.
- Snapshot inicial: rodar `go test ./...` uma vez e confirmar verde antes de começar (comportamento de referência).

---

### Task 1: Tooling e esqueleto do pacote

**Files:**
- Create: `pyproject.toml`
- Create: `motor/__init__.py` (vazio)
- Create: `motor/errors.py`
- Create: `motor/py.typed` (vazio, marcador de tipagem)
- Create: `motor/domain/__init__.py`, `motor/adapters/__init__.py`, `motor/adapters/git/__init__.py`, `motor/adapters/tasksource/__init__.py`, `motor/services/__init__.py`, `motor/engine/__init__.py` (todos vazios)
- Create: `tests/__init__.py` (vazio)
- Create: `conftest.py` (vazio, ancora a raiz do pytest)

**Interfaces:**
- Produces: `motor.errors.MotorError` (base de exceção usada por todo o resto).

- [ ] **Step 1: Confirmar snapshot Go verde**

Run: `go test ./...`
Expected: `ok` em todos os pacotes.

- [ ] **Step 2: Escrever `pyproject.toml`**

```toml
[project]
name = "motor-versoes"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = ["httpx"]

[project.optional-dependencies]
dev = ["pytest"]

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Escrever `motor/errors.py`**

```python
class MotorError(Exception):
    """Erro genérico do motor (espelha o error genérico do Go)."""
```

- [ ] **Step 4: Criar os `__init__.py` vazios e `conftest.py`**

Todos vazios. `conftest.py` na raiz garante que `motor` é importável nos testes.

- [ ] **Step 5: Verificar ambiente**

Run: `python -c "import motor.errors; print(motor.errors.MotorError)"`
Expected: `<class 'motor.errors.MotorError'>`
Run: `pytest -q`
Expected: `no tests ran` (sem erro de coleta).

- [ ] **Step 6: Commit**

```bash
rtk git add pyproject.toml conftest.py motor/ tests/
rtk git commit -m "chore(python): esqueleto do pacote motor + pyproject + MotorError"
```

---

### Task 2: Domínio (`motor/domain/`)

**Origem:** `internal/domain/{types,version,commits,reconcile}.go`

**Files:**
- Create: `motor/domain/types.py` ← `types.go`
- Create: `motor/domain/version.py` ← `version.go`
- Create: `motor/domain/commits.py` ← `commits.go`
- Create: `motor/domain/reconcile.py` ← `reconcile.go`
- Test: `tests/test_version.py` ← `version_test.go`
- Test: `tests/test_commits.py` ← `commits_test.go`
- Test: `tests/test_reconcile.py` ← `reconcile_test.go`

**Interfaces:**
- Consumes: `motor.errors.MotorError`.
- Produces (usado por ports/services/engine — assinaturas exatas):
  - `types.py`: `VersionType(IntEnum)` {`FECHADA=0`,`AJUSTADA=1`,`CLIENTE=2`}; `ExclusionReason(IntEnum)` {`AUTOMATICA=0`,`JULGAMENTO=1`}; dataclasses `BaseRef(ref, commit)`, `Version(numero, tipo, base)`, `CommitRef(hash_origem, parent, chamado, task, commit_date, msg)`, `TaskTarget(chamado, task, titulo, commits)`, `Exclusion(commit, chamado, motivo, reason)`, `Lock(versao, tipo, base, tasks, excluidos)`, `VersionStatus(verde, tasks_novas, tasks_removidas, lock_integro, commits_sumidos, faltantes, conflitantes)`; alias `TargetSet = dict[str, TaskTarget]`.
  - `version.py`: `inferir_tipo(numero: str) -> VersionType`; `inferir_base(numero: str, versoes_existentes: list[str]) -> str`.
  - `commits.py`: `match_exato(candidatos: list[CommitRef], chamado: str, vb_id: str) -> list[CommitRef]`; `extrair_chamado(msg: str) -> str | None`; `extrair_vb_id(msg: str) -> str | None`; `ordenar_por_data(commits: list[CommitRef]) -> list[CommitRef]`.
  - `reconcile.py`: `filtrar_excluidos(alvo, excluidos) -> TargetSet`; `diff_tasks(alvo, lock_tasks) -> tuple[list[str], list[str]]`; `reconciliar(alvo, lock, presentes: dict[str, bool], conflitantes: list[CommitRef]) -> VersionStatus`.

**Armadilhas de tradução:**
- `types.py`: dataclasses com listas → `field(default_factory=list)`, nunca `= []`. `commit_date: datetime`. `IntEnum` respeitando a ordem do `iota`.
- `version.py`: `parse_versao` deve `raise MotorError` em formato inválido ou componente `< 0`. `inferir_tipo` retorna o enum (não `(tipo, err)`). `inferir_base` levanta `MotorError` quando não acha base `X.Y.0`. Descartar o helper `contains` — usar `alvo in versoes_existentes`.
- `commits.py`: regex idênticas — `padrao_chamado = re.compile(r"\bch(\d+)\b")`, `padrao_vb = re.compile(r"\b(VB-\d+)\b")`. Em `match_exato`, montar padrões com `re.escape`. **Teste crítico**: `\bch255514\b` NÃO pode casar `"ch5514"`. `extrair_*` retornam `str | None`. `ordenar_por_data` usa `sorted(commits, key=lambda c: c.commit_date)` (não muta a entrada).
- `reconcile.py`: `diff_tasks` retorna `(novas, removidas)` **ambos ordenados** (`sorted(...)`). `reconciliar` ordena `commits_sumidos`; `faltantes` e `conflitantes` não são ordenados no Go — manter assim. `verde` = sem novas, sem removidas, lock íntegro, sem faltantes.

- [ ] **Step 1:** Ler `internal/domain/*.go` inteiros. Portar `types.py` (nenhum comportamento, só dados) primeiro.
- [ ] **Step 2:** Portar `tests/test_version.py` a partir de `version_test.go` (incluir o caso de formato inválido esperando `pytest.raises(MotorError)`). Rodar e ver falhar.

Run: `pytest tests/test_version.py -q` → Expected: FAIL (ImportError/NameError, `version.py` ainda não existe).

- [ ] **Step 3:** Portar `version.py`. Rodar até passar.

Run: `pytest tests/test_version.py -q` → Expected: PASS.

- [ ] **Step 4:** Portar `tests/test_commits.py` ← `commits_test.go` (casos: substring `ch5514` vs `255514`, VB-ID, extrair chamado/vb, ordenar sem mutar). Rodar → FAIL.
- [ ] **Step 5:** Portar `commits.py`. Rodar → PASS.

Run: `pytest tests/test_commits.py -q` → Expected: PASS.

- [ ] **Step 6:** Portar `tests/test_reconcile.py` ← `reconcile_test.go` (verde, task nova, task removida, lock não-íntegro, filtrar excluídos). Rodar → FAIL.
- [ ] **Step 7:** Portar `reconcile.py`. Rodar → PASS.

Run: `pytest tests/test_reconcile.py -q` → Expected: PASS.

- [ ] **Step 8:** Rodar o domínio inteiro.

Run: `pytest tests/test_version.py tests/test_commits.py tests/test_reconcile.py -q`
Expected: todos PASS.

- [ ] **Step 9: Commit**

```bash
rtk git add motor/domain tests/test_version.py tests/test_commits.py tests/test_reconcile.py
rtk git commit -m "feat(domain): port de types/version/commits/reconcile + testes"
```

---

### Task 3: Portas (`motor/ports.py`)

**Origem:** `internal/ports/ports.go` (usar o arquivo real, mais rico que o spec).

**Files:**
- Create: `motor/ports.py`

**Interfaces:**
- Consumes: `motor.domain.types` (`CommitRef`, `TaskTarget`).
- Produces:
  - `CherryPickOutcome(IntEnum)` {`APLICADO=0`, `CONFLITO=1`}.
  - `@dataclass MergePrediction(conflita: bool, arquivos_conflito: list[str])`.
  - `class TaskSource(Protocol)`: `fetch(self, versao: str) -> list[TaskTarget]`.
  - `class GitRepo(Protocol)` com todos os métodos de `ports.go` em snake_case: `merge_base(a, b) -> str`; `is_ancestor(commit, branch) -> bool`; `search_commits(padroes: list[str], refs: str) -> list[CommitRef]`; `commits_in_range(from_, to) -> list[CommitRef]`; `commit_meta(hash) -> CommitRef`; `patch_id(hash) -> str`; `resolve_ref(ref) -> str`; `use_worktree(branch) -> None`; `cherry_pick_x(hash) -> CherryPickOutcome`; `conflicted_paths() -> list[str]`; `pending_cherry_pick() -> tuple[str, bool]`; `continue_cherry_pick() -> None`; `abort_cherry_pick() -> None`; `predict_merge(parent, branch_tip, commit) -> MergePrediction`; `worktree_add(branch, base) -> None`; `worktree_remove(branch) -> None`; `tag_exists(tag) -> bool`; `remote_branch_exists(remote, branch) -> bool`; `list_version_branches() -> list[str]`; `read_file(branch, path) -> bytes`; `write_file(branch, path, content: bytes, mensagem_commit: str) -> None`.

**Armadilhas:**
- `from_` (com underscore) porque `from` é reservada em Python.
- `pending_cherry_pick` retorna `(hash, ok)` — manter tupla aqui (é `(val, ok)` puro, sem erro), OU `str | None`. **Decisão: `tuple[str, bool]`** pra casar 1-pra-1 com quem consome no engine; conferir no port do engine.
- Protocol não precisa de implementação; corpo dos métodos é `...`. Sem teste dedicado.

- [ ] **Step 1:** Ler `ports.go` real. Portar `motor/ports.py`.
- [ ] **Step 2:** Verificar import.

Run: `python -c "import motor.ports; print(motor.ports.GitRepo, motor.ports.TaskSource)"`
Expected: imprime as duas classes sem erro.

- [ ] **Step 3: Commit**

```bash
rtk git add motor/ports.py
rtk git commit -m "feat(ports): Protocols TaskSource/GitRepo + MergePrediction"
```

---

### Task 4: Fakes de teste (`motor/adapters/git/fake.py`, `motor/adapters/tasksource/fake.py`)

**Origem:** `internal/adapters/git/fake.go` (291 LOC), `internal/adapters/tasksource/fake.go` (24 LOC), e seus `_test.go`.

**Files:**
- Create: `motor/adapters/git/fake.py` ← `git/fake.go`
- Create: `motor/adapters/tasksource/fake.py` ← `tasksource/fake.go`
- Test: `tests/test_git_fake.py` ← `git/fake_test.go`
- Test: `tests/test_tasksource_fake.py` ← `tasksource/fake_test.go`

**Interfaces:**
- Consumes: `motor.ports` (implementa `GitRepo`/`TaskSource` estruturalmente), `motor.domain.types`.
- Produces: `FakeGit` (grafo de commits em memória, implementa todos os métodos de `GitRepo`), `FakeTaskSource` (retorna `list[TaskTarget]` fixo). São o que os testes de services/engine consomem.

**Armadilhas:**
- `fake.go` do git é o arquivo mais denso — **ler inteiro antes de traduzir**. Mapear estruturas de dados em memória (mapa hash→pais/trailer) pra `dict`. Estado mutável de cherry-pick (pendente, arquivos em conflito) → atributos de instância.
- `FakeGit` precisa satisfazer o `Protocol GitRepo` inteiro (todos os métodos), mesmo os que o teste não exercita — senão o type-check e o uso no engine quebram. Métodos não usados podem levantar `NotImplementedError`, mas só se o Go também não os implementa; conferir 1-pra-1.
- Comparar por conteúdo: dataclasses com `eq=True` (padrão) tornam asserts de igualdade diretos.

- [ ] **Step 1:** Ler `git/fake.go` e `tasksource/fake.go` inteiros.
- [ ] **Step 2:** Portar `tests/test_tasksource_fake.py` ← `tasksource/fake_test.go`; rodar → FAIL.
- [ ] **Step 3:** Portar `tasksource/fake.py`; rodar → PASS.

Run: `pytest tests/test_tasksource_fake.py -q` → Expected: PASS.

- [ ] **Step 4:** Portar `tests/test_git_fake.py` ← `git/fake_test.go`; rodar → FAIL.
- [ ] **Step 5:** Portar `git/fake.py`; rodar → PASS.

Run: `pytest tests/test_git_fake.py -q` → Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add motor/adapters/git/fake.py motor/adapters/tasksource/fake.py tests/test_git_fake.py tests/test_tasksource_fake.py
rtk git commit -m "feat(adapters): FakeGit e FakeTaskSource + testes"
```

---

### Task 5: Serviços (`motor/services/`)

**Origem:** `internal/services/{target_resolver,presence_oracle,lock_store,base_resolver,publication_gate}.go` + `_test.go`.

**Files:**
- Create: `motor/services/target_resolver.py` ← `target_resolver.go`
- Create: `motor/services/presence_oracle.py` ← `presence_oracle.go`
- Create: `motor/services/lock_store.py` ← `lock_store.go`
- Create: `motor/services/base_resolver.py` ← `base_resolver.go`
- Create: `motor/services/publication_gate.py` ← `publication_gate.go`
- Test: `tests/test_target_resolver.py`, `tests/test_presence_oracle.py`, `tests/test_lock_store.py`, `tests/test_base_resolver.py`, `tests/test_publication_gate.py` (cada ← seu `_test.go`)

**Interfaces:**
- Consumes: `motor.ports.GitRepo`/`TaskSource`, `motor.domain.*`, `FakeGit`/`FakeTaskSource` (nos testes).
- Produces (dataclasses com deps injetadas):
  - `TargetResolver(tasks: TaskSource, git: GitRepo)` → `resolve(versao: str) -> TargetSet`.
  - `PresenceOracle(git: GitRepo)` → `presente(hash_origem: str, branch: str) -> bool`.
  - `LockStore(git: GitRepo)` → `ler(branch) -> Lock`; `escrever(branch, lock) -> None`; `reconstruir(branch) -> tuple[Lock, list[Exclusion]]`.
  - `BaseResolver(git: GitRepo)` → `resolve(numero: str) -> BaseRef`.
  - `PublicationGate(git: GitRepo)` → `publicada(versao: str) -> bool`.

**Armadilhas:**
- Serviços são `@dataclass` mutáveis segurando as deps (ex.: `@dataclass class LockStore: git: GitRepo`). Chamada: `LockStore(git=fake).ler("13.7.0")`.
- `LockStore.reconstruir` retorna `(lock, orfaos)` — tupla. Ordena commits por `commit_date` dentro de cada chamado (ver commit `e625a14` no histórico Go — bug já corrigido lá, replicar).
- `PresenceOracle.presente`: ordem hash-ancestral → trailer (`search_commits`) → patch-id. Preservar o curto-circuito.
- Erros de I/O do git viram `MotorError` (via `from e`).

- [ ] **Step 1:** Ler os 5 `.go` de serviço + `_test.go` inteiros.
- [ ] **Step 2 (repetir por serviço, ordem: base_resolver, publication_gate, presence_oracle, target_resolver, lock_store):** portar o `test_*.py` (→ FAIL), depois o `*.py` (→ PASS).

Run por serviço, ex.: `pytest tests/test_presence_oracle.py -q` → Expected: PASS.

- [ ] **Step 3:** Rodar a camada inteira.

Run: `pytest tests/test_target_resolver.py tests/test_presence_oracle.py tests/test_lock_store.py tests/test_base_resolver.py tests/test_publication_gate.py -q`
Expected: todos PASS.

- [ ] **Step 4: Commit**

```bash
rtk git add motor/services tests/test_target_resolver.py tests/test_presence_oracle.py tests/test_lock_store.py tests/test_base_resolver.py tests/test_publication_gate.py
rtk git commit -m "feat(services): port dos 5 serviços + testes"
```

---

### Task 6: Engine (`motor/engine/`)

**Origem:** `internal/engine/{deps,criar,verificar,incrementar,reconstruir_lock}.go` + `_test.go`.

**Files:**
- Create: `motor/engine/deps.py` ← `deps.go`
- Create: `motor/engine/verificar.py` ← `verificar.go`
- Create: `motor/engine/criar.py` ← `criar.go`
- Create: `motor/engine/incrementar.py` ← `incrementar.go`
- Create: `motor/engine/reconstruir_lock.py` ← `reconstruir_lock.go`
- Test: `tests/test_verificar.py`, `tests/test_criar.py`, `tests/test_incrementar.py`, `tests/test_reconstruir_lock.py`

**Interfaces:**
- Consumes: `motor.services.*`, `motor.domain.*`, `motor.ports.*`, fakes (testes).
- Produces (assinaturas conforme `main.go` real — recebem `Deps`, não `repo: str`):
  - `@dataclass Deps(git: GitRepo, tasks: TaskSource)`.
  - `IncrementStatus(IntEnum)` {`DONE=0`, `BLOCKED=1`}; `@dataclass IncrementResult(status, blocked_commit: str = "", arquivos_conflito: list[str] = <factory>)`.
  - `ReconstructStatus(IntEnum)` {`DONE=0`, `PENDING_JUDGMENT=1`}; `@dataclass ReconstructResult(status, orfaos: list[Exclusion] = <factory>)`.
  - `verificar(deps: Deps, versao: str) -> VersionStatus`.
  - `criar(deps: Deps, versao: str) -> IncrementResult`.
  - `incrementar(deps: Deps, versao: str) -> IncrementResult`.
  - `incrementar_continue(deps: Deps, versao: str) -> IncrementResult`.
  - `incrementar_abort(deps: Deps, versao: str) -> None`.
  - `reconstruir_lock(deps: Deps, versao: str) -> ReconstructResult`.

**Armadilhas:**
- `IncrementResult` é **achatado** (campos `status`, `blocked_commit`, `arquivos_conflito`) — NÃO um `ConflictSession` aninhado (o spec está errado; `main.go` é a verdade).
- `incrementar_continue` reconstrói o lock inteiro (ver commit `7ce6af6`: bug de `Conflitantes` vazando sumidos já corrigido no Go — replicar).
- `criar` seta `rerere.enabled`/`rerere.autoUpdate` na primeira criação da worktree.
- Nada de prompt: em conflito, retornar `IncrementResult(status=BLOCKED, ...)`.

- [ ] **Step 1:** Ler os 5 `.go` de engine + `_test.go` inteiros. Portar `deps.py` e os enums/dataclasses de resultado primeiro (ficam em seus respectivos módulos ou em `deps.py`; seguir a organização do Go).
- [ ] **Step 2 (repetir por operação, ordem: verificar, criar, incrementar, reconstruir_lock):** portar `test_*.py` (→ FAIL), depois `*.py` (→ PASS). Incluir os casos do `incrementar_test.go`: feliz (aplica tudo) e conflito (`FakeGit` simula conflito → `status=BLOCKED` com o commit certo).

Run por operação, ex.: `pytest tests/test_incrementar.py -q` → Expected: PASS.

- [ ] **Step 3:** Rodar o engine inteiro.

Run: `pytest tests/test_verificar.py tests/test_criar.py tests/test_incrementar.py tests/test_reconstruir_lock.py -q`
Expected: todos PASS.

- [ ] **Step 4: Commit**

```bash
rtk git add motor/engine tests/test_verificar.py tests/test_criar.py tests/test_incrementar.py tests/test_reconstruir_lock.py
rtk git commit -m "feat(engine): port de verificar/criar/incrementar/reconstruir-lock + testes"
```

---

### Task 7: Adapters reais (`git/subprocess.py`, `tasksource/rest.py`, `tasksource/manuallist.py`)

**Origem:** `internal/adapters/git/subprocess.go` (373 LOC) + `subprocess_test.go` (250 LOC, git real); `internal/adapters/tasksource/rest.go` + `rest_test.go`; `internal/adapters/tasksource/manuallist.go` + `manuallist_test.go`.

**Files:**
- Create: `motor/adapters/git/subprocess.py` ← `subprocess.go`
- Create: `motor/adapters/tasksource/rest.py` ← `rest.go`
- Create: `motor/adapters/tasksource/manuallist.py` ← `manuallist.go`
- Test: `tests/test_git_subprocess.py` ← `subprocess_test.go`
- Test: `tests/test_tasksource_rest.py` ← `rest_test.go`
- Test: `tests/test_tasksource_manuallist.py` ← `manuallist_test.go`

**Interfaces:**
- Consumes: `motor.ports`, `motor.domain.types`, `subprocess`, `httpx`, `urllib.parse`, `json`.
- Produces:
  - `GitSubprocess` (fábrica `new_git_subprocess(repo: str) -> GitSubprocess` espelhando `git.NewGitSubprocess`) — implementa `GitRepo` via `subprocess`.
  - `@dataclass ClickUpRest(base_url="", team_id="", token="", campo_chamado_id="", client: httpx.Client | None = None)` → `fetch(versao) -> list[TaskTarget]`.
  - `@dataclass ManualList(caminho: str)` → `fetch(versao) -> list[TaskTarget]`.

**Armadilhas:**
- **`subprocess.py`**: cada chamada `os/exec` → `subprocess.run([...], cwd=repo, capture_output=True, text=...)`. Cuidado com bytes vs str: `read_file` retorna `bytes` (usar `text=False` ou `.stdout` cru). Exit codes: mapear a lógica de classificação de conflito do `cherry_pick_x`/`predict_merge` (ver commits `0c9b5db`, `2fbda6e` — bugs já corrigidos no Go). `write_file` não falha quando o conteúdo não muda (commit `2fbda6e`). Assume `git >= 2.38` (`merge-tree --write-tree`).
- **`rest.py`**: `httpx.Client(base_url=...)`; header `Authorization = token` (sem `Bearer`, igual ao Go). Filtro: montar o JSON `[{"field_id":..,"operator":"=","value":versao}]` e passar via `params={"custom_fields": filtro}` (httpx faz o escape) ou `urllib.parse.quote`. `status != 200` → `raise MotorError(f"ClickUp respondeu {status}")`. Campo `campo_versao_destino = "de0124a4-a15d-401e-ab48-417803082562"` (constante, copiar). `extrair_campo_chamado` percorre custom_fields.
- Teste do rest usa `httpx.MockTransport` num `httpx.Client(transport=..., base_url=...)` — sem servidor real.
- Teste do subprocess usa `tmp_path` do pytest + `git init`/commits reais. Marcar com skip se `git` ausente é opcional; o Go não pula, então não pular.

- [ ] **Step 1:** Ler os 3 `.go` de adapter + seus `_test.go`.
- [ ] **Step 2:** Portar `manuallist` (mais simples): `test_tasksource_manuallist.py` → FAIL; `manuallist.py` → PASS.

Run: `pytest tests/test_tasksource_manuallist.py -q` → Expected: PASS.

- [ ] **Step 3:** Portar `rest` com `MockTransport`: `test_tasksource_rest.py` → FAIL; `rest.py` → PASS.

Run: `pytest tests/test_tasksource_rest.py -q` → Expected: PASS.

- [ ] **Step 4:** Portar `subprocess`: `test_git_subprocess.py` (usa `tmp_path` + git real) → FAIL; `subprocess.py` → PASS.

Run: `pytest tests/test_git_subprocess.py -q` → Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add motor/adapters tests/test_git_subprocess.py tests/test_tasksource_rest.py tests/test_tasksource_manuallist.py
rtk git commit -m "feat(adapters): GitSubprocess, ClickUpRest (httpx) e ManualList + testes"
```

---

### Task 8: CLI (`motor/__main__.py`) e fecho

**Origem:** `cmd/motor/main.go`.

**Files:**
- Create: `motor/__main__.py` ← `main.go`

**Interfaces:**
- Consumes: `motor.engine.*`, `motor.adapters.git.subprocess.new_git_subprocess`, `motor.adapters.tasksource.{rest.ClickUpRest, manuallist.ManualList}`.
- Produces: entrypoint `python -m motor <comando> <versao> [flags]`.

**Comportamento (espelhar `main.go`):**
```
python -m motor verificar        <X.Y.Z> --repo <path>
python -m motor criar             <X.Y.Z> --repo <path> [--task-source=rest|manual --clickup-token=... --clickup-team=... --clickup-campo-chamado=...] [--lista=arquivo]
python -m motor incrementar      <X.Y.Z> --repo <path> [--continue | --abort]
python -m motor reconstruir-lock <X.Y.Z> --repo <path>
```

**Armadilhas:**
- `argparse` com subparsers; `versao` posicional em cada subcomando; `--repo` obrigatório (erro → stderr + `sys.exit(1)`).
- `--clickup-token` default `os.environ.get("CLICKUP_TOKEN")`.
- `--task-source` default `"manual"`; `rest` → `ClickUpRest`, senão `ManualList`.
- `--continue`/`--abort` no subcomando `incrementar` (usar `dest="continuar"`/`dest="abortar"`; `continue` é reservada). Em `--abort`, não imprime resultado.
- Funções de saída `imprimir_status`/`imprimir_incremento`/`imprimir_uso` com o mesmo texto do Go. Erro genérico → `print("erro:", e, file=sys.stderr); sys.exit(1)`.
- CLI é fina: só parseia, monta `Deps(git=new_git_subprocess(repo), tasks=...)`, chama o engine.

- [ ] **Step 1:** Ler `main.go`. Portar `motor/__main__.py`.
- [ ] **Step 2:** Rodar a suíte inteira.

Run: `pytest -q`
Expected: **todos** os testes PASS.

- [ ] **Step 3:** Smoke da CLI num repo de teste (o mesmo usado pelo `subprocess_test`, ou um `git init` temporário).

Run: `python -m motor verificar 13.7.0 --repo /caminho/repo/teste`
Expected: imprime `verde: ...`, `tasks novas: ...`, etc., sem stacktrace. Comparar a saída com `./motor verificar 13.7.0 --repo <mesmo>` (binário Go), se disponível — devem bater.

- [ ] **Step 4: Commit**

```bash
rtk git add motor/__main__.py
rtk git commit -m "feat(cli): entrypoint python -m motor (argparse)"
```

---

## Verificação final (Definition of Done)

- [ ] `pytest -q` inteiramente verde (todos os 17 arquivos de teste portados passando).
- [ ] Contagem de testes bate com o Go: cada função `Test*` do Go tem equivalente `test_*` no Python.
- [ ] Smoke `python -m motor verificar ...` produz a mesma saída que o `motor` Go no mesmo repo.
- [ ] `pip install -e .` funciona (só `httpx` de runtime).

## Fora de escopo (não fazer neste plano)

- `savedview.py` (não existe no Go), daemon/Etapa 2, libs interativas (`typer`/`rich`/`textual`), remoção do código Go.
