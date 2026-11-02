# O estado: por que existe e por que é descartável

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [002](002-oraculo-tres-fontes.md), [009](009-inferencia-de-base.md),
  [010](010-travas-publicada-e-liberada.md), [011](011-congelamento-no-banco.md),
  [021](021-motor-nao-interativo.md)

Mora em SQLite (padrão, um arquivo local, sem Docker) ou em Postgres (opt-in), escolhido por
`DATABASE_BACKEND`, escopado por repo. O contrato do estado é o mesmo nos dois, e a suíte de
contrato roda contra ambos. `migrar-estado --de <url> --para <url>` copia o estado completo
(inclusive o julgamento humano, abaixo) de um para o outro, nos dois sentidos; ele não troca
o backend sozinho. Guarda duas coisas de natureza diferente:

**Projeção, recuperável** — a derivação task → commits. `reconstruir-estado` regenera:
número, tipo e base saem do nome da branch mais a inferência
([009](009-inferencia-de-base.md)); as atribuições saem dos trailers
`cherry picked from <hash>` em `base..HEAD`, reagrupados por `ch<num>`.

**Julgamento humano, não recuperável** — exclusões ("esse commit o grep pegou mas não entra")
e registros de "não houve entrega". Só existe no banco — por isso trocar de backend é
`migrar-estado`, não `reconstruir-estado`. Para commit sem `ch<num>` na mensagem,
`reconstruir-estado` devolve `PENDING_JUDGMENT{orfaos}` e para; quem pergunta ao humano é o
front-end, nunca o motor ([021](021-motor-nao-interativo.md)).

Três consequências que valem gravar:

- **Identidade da tarefa é só o número do chamado.** Os hashes gravados são sempre os de
  **origem**, nunca os pós-cherry-pick — esses se derivam dos trailers.
- **Atribuição tem dois estados, `pendente` e `aplicado`, e a diferença importa.** Tarefa
  marcada sem nenhum commit achado nunca vira `aplicado`: marcar como entregue algo que não
  foi aplicado registraria uma entrega que não aconteceu. Fica `pendente` e aparece como
  faltante até alguém achar o commit ou registrar que não houve entrega.
- **Dependência dura: todo pick usa `-x`.** O trailer é o backbone durável; o estado é a
  camada rápida por cima. Um cherry-pick sem trailer vira um buraco que `reconstruir-estado`
  não preenche.

## Reconstruir sobre uma versão liberada

O congelamento ([010](010-travas-publicada-e-liberada.md),
[011](011-congelamento-no-banco.md)) recusa a escrita. A via é zerar a data de liberação:

```sql
update versao set liberada_em = null where repo_id = … and numero = '13.34.0';
```

**Não é `delete from versao`:** a FK de `atribuicao` foi declarada sem `ondelete`, então o
`delete` é recusado justamente quando a versão tem atribuições — o caso em que se quer
reconstruir — e apagar os filhos primeiro bate na trigger de congelamento. Zerar
`liberada_em` também preserva a base já gravada.
