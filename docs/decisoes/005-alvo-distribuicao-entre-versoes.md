# O alvo: distribuição entre versões

- **Status:** aceita
- **Data:** 2026-08-21 (revista em 2026-08-24: liberada com tag posterior ao corte volta a
  ser fonte de alvo; em 2026-10-08: piso configurável por repo)
- **Depende de:** [004](004-estado-descartavel.md), [009](009-inferencia-de-base.md)

Uma tarefa marcada para a versão `V` no Tickio vale para `V` **e para toda versão em
construção (sem tag) cujo número seja maior**. Não é preciso remarcar a tarefa a cada versão
nova que abre. Visto do lado da versão, que é como o motor precisa:

```
versoes_abertas(branches, tags) = branches sem tag homônima, em ordem semver
liberadas_no_alvo(V, tags)      = { W com tag : W <= V, data_tag(W) > data(base_commit(V)) }
candidatas(V)                   = versoes_abertas ∪ liberadas_no_alvo(V) ∪ { V }
fontes_de_alvo(V, candidatas)   = { W em candidatas : piso(repo) <= W <= V }   # V incluso; piso padrão 13.0.0
alvo(V) = ∪ tickio.fetch(W), para todo W em fontes_de_alvo(V, candidatas)
```

A ordem é semver sobre `(x, y, z)`, não textual: `13.9.0` vem antes de `13.10.0`.

## Por que a liberada não sai de vez da união

A versão em construção entra por definição. A liberada saiu do conjunto aberto, e a primeira
versão desta decisão dizia que ela ficava de fora porque **seu conteúdo chega a `V` por
ancestralidade da base ([009](009-inferencia-de-base.md))**. Essa premissa é falsa, e o modo
de falhar é silencioso.

Ela vale quando `W` está na cadeia de bases de `V` — `14.7.0` desce de `14.6.0`, que desce de
`14.5.0`. Não vale para `X.0.0`, cuja base é o **master no ponto de corte**: uma `15.0.0`
cortada antes de a `14.6.0` existir não tem nada do que a `14.6.0` entregou depois disso. Nem
vale para versão de cliente `X.Y'.Z'` ≤ `V` fora da cadeia. No dia em que a `14.6.0` recebeu a
tag, o chamado dela saiu do alvo da `15.0.0` — exatamente onde ainda era necessário — e nada
pintou vermelho, porque tarefa que não está no alvo não é cobrada por ninguém.

O discriminador é a **data da tag contra a data do commit-base de `V`**. Entrega que virou tag
depois do corte de `V` nunca foi herdada; o que virou tag antes já chegou pela base. Tag
exatamente no corte fica de fora — é a ajustada cortada da anterior já liberada, o caso em que
a premissa antiga acertava. A data do commit-base é a que o estado já guarda
([004](004-estado-descartavel.md)), então não há ponto de corte a recomputar, e resolvida a
versão-fonte o oráculo de presença ([003](003-definicao-de-presente.md)) ainda decide commit
por commit o que de fato falta.

**Ancestralidade de branch não serve como teste aqui.** Cherry-pick troca o hash, então a tag
de uma release branch praticamente nunca é ancestral de uma `X.0.0` — testar isso puxaria
_toda_ liberada desde a `13.0.0` para o alvo de cada versão fechada.

**Custo aceito: liberada que o motor nunca operou fica fora.** Sem linha no estado ela não tem
base gravada nem snapshot a proteger, e o motor não paga leitura de git pela tag dela — o que
também impede uma tag que não resolve de matar um run que nem a tem como alvo. Na prática são
versões antigas, anteriores a qualquer corte que ainda esteja aberto.

Resolvidos os chamados, os commits saem numa **varredura só para todo o lote**, nunca uma por
versão-fonte. Como o candidato vira commit da tarefa: [006](006-match-exato-no-dominio.md).
Tarefa marcada em mais de uma versão: [007](007-tarefa-em-duas-abertas.md).
