# O invariante que sustenta tudo: o motor é não-interativo

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [018](018-portas-e-adaptadores.md)

**O motor é não-interativo e determinístico. Nunca pergunta, nunca bloqueia esperando
humano — retorna um valor.** Conflito de cherry-pick vira `BLOCKED{commit, arquivos}`; commit
órfão vira `PENDING_JUDGMENT{orfaos}`. Quem dirige o humano (resolver no editor, decidir os
órfãos) é o front-end.

É o que faz o mesmo núcleo servir CLI e TUI sem uma linha de diferença, e o que faria um
daemon ser só mais um front-end. Também é o motivo de não existir objeto "sessão de conflito":
retomar reconstrói tudo do git e do estado a cada chamada, sem nada em memória entre
invocações.
