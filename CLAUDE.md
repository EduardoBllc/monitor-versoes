<!-- rtk-instructions v2 -->
# RTK (Rust Token Killer) - Token-Optimized Commands

## Golden Rule

**Always prefix commands with `rtk`**. If RTK has a dedicated filter, it uses it. If not, it passes through unchanged. This means RTK is always safe to use.

**Important**: Even in command chains with `&&`, use `rtk`:
```bash
# ❌ Wrong
git add . && git commit -m "msg" && git push

# ✅ Correct
rtk git add . && rtk git commit -m "msg" && rtk git push
```

## RTK Commands by Workflow

### Build & Compile (80-90% savings)
```bash
rtk cargo build         # Cargo build output
rtk cargo check         # Cargo check output
rtk cargo clippy        # Clippy warnings grouped by file (80%)
rtk tsc                 # TypeScript errors grouped by file/code (83%)
rtk lint                # ESLint/Biome violations grouped (84%)
rtk prettier --check    # Files needing format only (70%)
rtk next build          # Next.js build with route metrics (87%)
```

### Test (90-99% savings)
```bash
rtk cargo test          # Cargo test failures only (90%)
rtk vitest run          # Vitest failures only (99.5%)
rtk playwright test     # Playwright failures only (94%)
rtk test <cmd>          # Generic test wrapper - failures only
```

### Git (59-80% savings)
```bash
rtk git status          # Compact status
rtk git log             # Compact log (works with all git flags)
rtk git diff            # Compact diff (80%)
rtk git show            # Compact show (80%)
rtk git add             # Ultra-compact confirmations (59%)
rtk git commit          # Ultra-compact confirmations (59%)
rtk git push            # Ultra-compact confirmations
rtk git pull            # Ultra-compact confirmations
rtk git branch          # Compact branch list
rtk git fetch           # Compact fetch
rtk git stash           # Compact stash
rtk git worktree        # Compact worktree
```

Note: Git passthrough works for ALL subcommands, even those not explicitly listed.

### GitHub (26-87% savings)
```bash
rtk gh pr view <num>    # Compact PR view (87%)
rtk gh pr checks        # Compact PR checks (79%)
rtk gh run list         # Compact workflow runs (82%)
rtk gh issue list       # Compact issue list (80%)
rtk gh api              # Compact API responses (26%)
```

### JavaScript/TypeScript Tooling (70-90% savings)
```bash
rtk pnpm list           # Compact dependency tree (70%)
rtk pnpm outdated       # Compact outdated packages (80%)
rtk pnpm install        # Compact install output (90%)
rtk npm run <script>    # Compact npm script output
rtk npx <cmd>           # Compact npx command output
rtk prisma              # Prisma without ASCII art (88%)
```

### Files & Search (60-75% savings)
```bash
rtk ls <path>           # Tree format, compact (65%)
rtk read <file>         # Code reading with filtering (60%)
rtk grep <pattern>      # Search grouped by file (75%)
rtk find <pattern>      # Find grouped by directory (70%)
```

### Analysis & Debug (70-90% savings)
```bash
rtk err <cmd>           # Filter errors only from any command
rtk log <file>          # Deduplicated logs with counts
rtk json <file>         # JSON structure without values
rtk deps                # Dependency overview
rtk env                 # Environment variables compact
rtk summary <cmd>       # Smart summary of command output
rtk diff                # Ultra-compact diffs
```

### Infrastructure (85% savings)
```bash
rtk docker ps           # Compact container list
rtk docker images       # Compact image list
rtk docker logs <c>     # Deduplicated logs
rtk kubectl get         # Compact resource list
rtk kubectl logs        # Deduplicated pod logs
```

### Network (65-70% savings)
```bash
rtk curl <url>          # Compact HTTP responses (70%)
rtk wget <url>          # Compact download output (65%)
```

### Meta Commands
```bash
rtk gain                # View token savings statistics
rtk gain --history      # View command history with savings
rtk discover            # Analyze Claude Code sessions for missed RTK usage
rtk proxy <cmd>         # Run command without filtering (for debugging)
rtk init                # Add RTK instructions to CLAUDE.md
rtk init --global       # Add RTK to ~/.claude/CLAUDE.md
```

## Token Savings Overview

| Category | Commands | Typical Savings |
|----------|----------|-----------------|
| Tests | vitest, playwright, cargo test | 90-99% |
| Build | next, tsc, lint, prettier | 70-87% |
| Git | status, log, diff, add, commit | 59-80% |
| GitHub | gh pr, gh run, gh issue | 26-87% |
| Package Managers | pnpm, npm, npx | 70-90% |
| Files | ls, read, grep, find | 60-75% |
| Infrastructure | docker, kubectl | 85% |
| Network | curl, wget | 65-70% |

Overall average: **60-90% token reduction** on common development operations.
<!-- /rtk-instructions -->

# monitor-versoes — armadilhas do ambiente

Duas coisas que fazem comandos corretos falharem por motivo que não é o código.

## `uv run` não funciona nesta máquina

Há um `VIRTUAL_ENV` de outro projeto (`vendabemweb`, Python 2.7) vazando para o
shell. O `uv` o prefere sobre o `.venv` do projeto e o pytest morre na coleta com
`SyntaxError: future feature annotations is not defined` — que **não** é erro de
código.

```bash
./.venv/bin/python -m pytest        # use isto
./.venv/bin/python -m alembic upgrade head
```

Se o `.venv` não existir: `unset VIRTUAL_ENV; uv sync --all-extras`.

## Testes e o `.env`

A suíte roda sem git, sem rede e sem banco. Exceção: os marcados
`@pytest.mark.integracao`, que precisam do Postgres do `compose.yml`.

- Sem `.env` (clone novo, CI) → `DATABASE_HOST` ausente → pulam.
- Com `.env` e container parado → pulam pela guarda de `OperationalError` no
  fixture.
- `env -u DATABASE_HOST` **não** faz pular: o `tests/conftest.py` chama
  `load_dotenv()` e repõe a variável. Para simular ausência, use `DATABASE_HOST=`
  vazia.

**Nunca use `monkeypatch.delenv` para testar variável ausente em teste que chama
`main()`.** O `main()` chama `load_dotenv()` a cada invocação, então a variável
volta do `.env` de verdade e o teste sai para a rede — já aconteceu. Use
`monkeypatch.setenv(VAR, "")`. Existe uma guarda autouse no `conftest.py` que
desliga esse `load_dotenv()`, mas o teste dela só discrimina em máquina com `.env`.

## Banco de desenvolvimento

```bash
docker compose up -d                       # porta 5433, não 5432
./.venv/bin/python -m alembic upgrade head
```

O fixture de integração dá `TRUNCATE` nas sete tabelas **no setup**, nunca no
teardown — toda rodada deixa as linhas do último teste. Se precisar do banco limpo,
trunque à mão.

## Ao mexer em `EstadoRepo`

`FakeEstado` e `PostgresEstado` têm de concordar. O contrato está em
`tests/test_estado_contrato.py`, que roda as mesmas asserções contra os dois — a
assertion nova vai para lá, não para uma das duas suítes. Fake mais permissivo que
o banco deixa a suíte verde num caminho que quebra em produção, e este projeto já
pagou por isso três vezes.
