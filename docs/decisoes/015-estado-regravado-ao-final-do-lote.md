# O estado é regravado uma vez, ao final do lote

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [004](004-estado-descartavel.md), [012](012-divergencia-entre-fontes.md)

O estado é regravado uma vez, ao final do lote, não por commit aplicado. Se o processo for
interrompido no meio, os cherry-picks já feitos ficam com trailer (prova em git) e o estado
atrasado; a próxima rodada lê isso como "pick manual sem o tool"
([012](012-divergencia-entre-fontes.md)) e oferece regularizar. Aceitável porque a
interrupção é rara e sempre recuperável.

`atualizar` **só adiciona história** — nunca reescreve.
