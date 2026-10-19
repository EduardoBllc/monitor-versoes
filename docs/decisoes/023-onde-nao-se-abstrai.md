# Onde deliberadamente não se abstrai

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [011](011-congelamento-no-banco.md), [014](014-ordem-de-aplicacao-pelo-grafo.md),
  [016](016-multi-projeto-premissas.md), [018](018-portas-e-adaptadores.md),
  [022](022-fetch-origin-em-todo-entry-point.md)

- **Sem porta de "clock".** A ordenação usa o grafo ([014](014-ordem-de-aplicacao-pelo-grafo.md)),
  e a data de liberação vem do commit apontado pela tag — nunca de `now()`
  ([011](011-congelamento-no-banco.md)). Não há relógio para injetar.
- **Sem camada de config por projeto** — o projeto é uma linha de tabela
  ([016](016-multi-projeto-premissas.md)).
- **Sem cache para as checagens de tag e branch remota.** Checagem direta a cada chamada,
  sempre depois do fetch ([022](022-fetch-origin-em-todo-entry-point.md)). Latência de rede
  é desprezível para uso sob demanda, e esse gate trava rebuild e congelamento: dado stale
  aqui permitiria escrever numa versão já liberada — mais perigoso que uma chamada de rede a
  mais.
- **Sem trigger na tabela `versao`** — limitação conhecida, não simplicidade deliberada
  ([011](011-congelamento-no-banco.md)).
