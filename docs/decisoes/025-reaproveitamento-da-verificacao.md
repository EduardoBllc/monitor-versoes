# `atualizar` reaproveita a verificação recente

- **Status:** aceita
- **Data:** 2026-11-03
- **Depende de:** [004](004-estado-descartavel.md), [005](005-alvo-distribuicao-entre-versoes.md),
  [013](013-conflito-e-checkpoint.md), [014](014-ordem-de-aplicacao-pelo-grafo.md),
  [015](015-estado-regravado-ao-final-do-lote.md), [022](022-fetch-origin-em-todo-entry-point.md),
  [023](023-onde-nao-se-abstrai.md)

`verificar` grava um carimbo (tabela `verificacao`): tip da branch depois do pull,
impressão das exclusões e do "sem entrega", hora e o `VersionStatus` inteiro. `atualizar` e
a prévia reaproveitam esse resultado em vez de simular o lote de novo. O carimbo **vale só
se as quatro condições** se cumprem:

- **existe**: sem carimbo, nada a reaproveitar;
- **tem até 5 minutos** (`VALIDADE_VERIFICACAO`, constante): o Tickio e as demais branches
  mudam fora do nosso alcance, e a idade limita o quanto o resultado pode ter envelhecido;
- **o tip é o mesmo**: outro commit na branch (inclusive picks de um `atualizar` anterior,
  [015](015-estado-regravado-ao-final-do-lote.md)) muda o que falta aplicar;
- **a impressão é a mesma**: exclusão ou "sem entrega" novos mudam o julgamento sem mexer
  no tip.

**O carimbo é cache**, descartável como o resto do estado
([004](004-estado-descartavel.md)): `migrar-estado` não o copia e `reconstruir-estado` não
o toca. `--auditar` e o snapshot de versão liberada não o gravam.

**A trava de tag continua sem cache**, com fetch próprio a cada chamada
([022](022-fetch-origin-em-todo-entry-point.md), [023](023-onde-nao-se-abstrai.md)): o
carimbo só poupa a simulação, nunca a checagem que protege versão liberada.

**Riscos aceitos**, os mesmos que o cherry-pick já cobre ([013](013-conflito-e-checkpoint.md),
[014](014-ordem-de-aplicacao-pelo-grafo.md)): se algo mudou dentro dos 5 minutos, o conflito
aparece na aplicação e vira checkpoint. Dois casos conhecidos:

- Tag criada em **outra** versão nesse intervalo não invalida o carimbo, e pode mudar a
  distribuição do alvo ([005](005-alvo-distribuicao-entre-versoes.md)), como uma mudança no
  Tickio — a mesma classe de risco que a validade já cobre. O congelamento dessa outra
  versão fica para o próximo `verificar`.
- A prévia da TUI mantém a worktree se o operador cancelar; é checkout descartável que o
  próximo GC limpa.

**Substitui a [023](023-onde-nao-se-abstrai.md) no ponto "sem porta de clock":** a validade
precisa de relógio, então existe `Deps.agora`, usado só para ela. A data de liberação segue
vindo do commit da tag, nunca de `now()` ([011](011-congelamento-no-banco.md)).
