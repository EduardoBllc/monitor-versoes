# Front-end web: daemon local e SPA com build versionado

- **Status:** aceita; o ponto "uma operação longa por repo, dentro do processo do daemon"
  foi substituído pela [032](032-lock-por-repo-entre-processos.md)
- **Data:** 2026-11-06
- **Depende de:** [019](019-montagem-no-front-end.md), [021](021-motor-nao-interativo.md)

**`motor serve` sobe um daemon local (FastAPI) que serve uma SPA em React + TypeScript + Vite +
Mantine.** O daemon é só mais um front-end: importa `montagem` e chama o motor, como CLI e TUI
([019](019-montagem-no-front-end.md), [021](021-motor-nao-interativo.md)). A web é de uso
diário e o editor de conflito precisa de UI rica, o que pesou a favor de uma SPA.

- **Build versionado em `motor/daemon/static/`.** `uv tool install git+…` compila do fonte e
  não pode exigir Node. O `make web-dist` guarda contra build velho: compara um build novo
  com a árvore de trabalho.
- **Contrato tipado de ponta a ponta.** Os tipos TS são gerados do OpenAPI do daemon e os
  enums TS espelham os do Python; `assertNever` faz um valor novo quebrar o `tsc`.
- **Só em `127.0.0.1`, sem login.** Checagem de `Host` e `Origin` contra DNS rebinding e
  requisições cross-site.
- **Uma operação longa por repo**, dentro do processo do daemon: o lock vale só dentro dele.

Alternativas rejeitadas:

- **htmx / HTML no servidor:** menos rico para o editor de conflito.
- **Preact + htm sem build:** sem tipos e sem o ecossistema npm.
- **NiceGUI:** lock-in e componente próprio para o Monaco.
- **textual-serve:** é o terminal no navegador, sem Monaco.
- **Elixir/Phoenix LiveView:** segundo runtime; o daemon precisa ser só mais um front-end
  Python importando `montagem`.
