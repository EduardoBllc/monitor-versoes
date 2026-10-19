# Ordem de aplicação: a do grafo — ancestral antes de descendente

- **Status:** aceita
- **Data:** 2026-10-01 (substitui a ordem por commit-date ascendente, de 2026-08-21)
- **Depende de:** [013](013-conflito-e-checkpoint.md), [018](018-portas-e-adaptadores.md)

Sem agrupar por task — commits de tasks diferentes intercalam se o histórico intercalar. O
git só responde quem descende de quem (`GitRepo.ordem_topologica`, `rev-list --topo-order`);
a ordenação em si fica no domínio (`ordenar_por_grafo`), testável com o git fake. Commit que
o git não conhece vai para o fim, na ordem em que chegou. O `verificar` simula o lote nessa
mesma ordem.

Data não entra, nem como desempate. A do autor sobrevive ao rebase: no ch257911 a PR 1273 foi
rebasada em cima da 1272, e por data o commit da 1272 caía no meio dos que já dependiam
dele. A do committer muda no rebase, mas tem resolução de segundo — 21 dos 31 commits
rebasados empataram no mesmo.
