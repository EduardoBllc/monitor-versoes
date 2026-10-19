# Conflito

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [012](012-divergencia-entre-fontes.md), [021](021-motor-nao-interativo.md)

1. **`git rerere` ligado, com `rerere.autoUpdate` também** — grava a resolução uma vez e
   replica em reincrementos e rebuilds. O `autoUpdate` não é opcional: sem ele, a resolução
   conhecida é reaplicada no working tree mas o arquivo continua "unmerged" até um `git add`
   explícito, e o "resolveu automaticamente, segue o pick" nunca dispara sozinho.
2. **Nunca auto-resolve heurísticamente.** Conflito novo para e entrega o controle.
3. **Checkpoint resumível** — a worktree fica no estado do conflito. O GC de worktrees
   (`WORKTREES_MANTIDAS`, ver README) nunca a descarta: cherry-pick pendente e alteração
   não commitada são guardas de remoção.
4. **Worktree isolada** — a árvore de trabalho principal nunca é tocada.

A predição de conflito não toca a working tree:
`git merge-tree --write-tree --merge-base=<parent(c)> <branch-tip> <c>` (Git ≥ 2.38) reporta
os arquivos que conflitariam **antes** de aplicar.

Em que ordem o lote é aplicado: [014](014-ordem-de-aplicacao-pelo-grafo.md).
