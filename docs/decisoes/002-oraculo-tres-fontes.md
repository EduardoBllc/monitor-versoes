# O oráculo de presença: três fontes de verdade

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [001](001-problema-completude-de-commits.md)

Como o hash muda, a presença é respondida cruzando três camadas:

| Fonte                  | Representa                                           | Muda quando                                                                                                     |
| ---------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| **Tickio**             | o que _deveria_ estar (alvo)                         | task marcada para uma versão ([005](005-alvo-distribuicao-entre-versoes.md))                                    |
| **estado (SQLite/Postgres)**| o que o tool _declarou_ colocar (intenção auditável) | `verificar`/`atualizar` sobrescrevem; versão liberada nunca muda ([010](010-travas-publicada-e-liberada.md))     |
| **git (trailer `-x`)** | o que está _fisicamente_ aplicado (prova)            | um cherry-pick acontece                                                                                         |

Verde só quando `Tickio = estado = git`. Cada camada pega o que a outra não pega:

- **estado × Tickio** → task nova esquecida, ou task desmarcada do alvo.
- **estado × git** → estado "mentindo" (commit sumiu num rebase, ou `UPDATE`/`DELETE` manual
  na tabela).
- **git × estado** → cherry-pick feito à mão sem o tool (regularizar o estado).

**Por que não comparar só Tickio × git?** Porque o mapa task → commits é derivado por grep na
mensagem (`ch<num>`) — é _fuzzy_. Duas execuções podem derivar coisas diferentes. O estado
congela essa derivação numa decisão explícita e auditável, em vez de re-derivar a cada
operação. É o motivo de existir a camada do meio; sem ela sobram duas fontes e nenhuma
memória do que foi decidido.

Como a presença é decidida commit a commit: [003](003-definicao-de-presente.md). O que fazer
quando as fontes divergem: [012](012-divergencia-entre-fontes.md).
