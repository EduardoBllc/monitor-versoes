# Todo entry point faz `git fetch origin` antes de ler qualquer ref

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [005](005-alvo-distribuicao-entre-versoes.md),
  [009](009-inferencia-de-base.md), [010](010-travas-publicada-e-liberada.md)

Sem isso, uma versão liberada em outra máquina fica invisível e o run sobrescreveria o
snapshot de uma versão que já saiu. O fetch resolve os dois casos por caminhos diferentes:
**tag** chega como `refs/tags/X`; **branch** chega como `refs/remotes/origin/X` e o fetch
**nunca** cria head local. Por isso a listagem de versões é `refs/heads/` ∪ `refs/tags/` ∪
`refs/remotes/origin/` — só com `refs/heads/`, uma versão aberta em outra máquina continuaria
invisível depois do fetch, e a distribuição ([005](005-alvo-distribuicao-entre-versoes.md)) a
omitiria em silêncio.

**`origin`, não qualquer remoto**, de propósito: é o único que o motor usa e o único que a
resolução de base ([009](009-inferencia-de-base.md)) tenta. Aceitar qualquer remoto
colocaria no conjunto aberto uma versão que a resolução de base depois não resolve — versão
fantasma no alvo e erro desconcertante na base.

Custo aceito: um `refs/remotes/origin/X` velho, de branch apagada e nunca liberada, lê como
aberta até alguém rodar `git fetch --prune`.
