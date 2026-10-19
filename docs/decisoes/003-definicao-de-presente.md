# Definição de "presente"

- **Status:** aceita
- **Data:** 2026-08-21 (revista em 2026-08-31: alcance do item 2 e passada dentro do lote)
- **Depende de:** [002](002-oraculo-tres-fontes.md)

```
presente(commit_origem, branch):
  1. hash exato é ancestral da branch?         (git merge-base --is-ancestor)  → sim
  2. algum commit da branch tem trailer         (git log --grep)
     "cherry picked from commit <commit_origem>"?                              → sim
  3. [legado] patch-id(commit_origem) ∈ patch-ids(base..branch)?               → sim
  senão → ausente
```

Item **2** é o principal: resiste a conflito resolvido, que muda o diff. Item **1** cobre
merge direto. Item **3** existe só para commits anteriores à convenção `-x`.

O **2 varre a branch inteira**; só o **3** se limita a `base..branch`. A assimetria é de
custo: `git log --grep` numa branch de 39k commits é uma travessia de 0,2s, enquanto o
patch-id de cada commit dela são segundos. Limitar o 2 ao range fazia entrega **herdada da
base** aparecer como faltante — o commit que carrega o trailer entrou numa versão anterior,
abaixo do corte (ch254994 na 14.11.0 do vendabemweb: 11 falsos faltantes).

Fora dos três, uma última passada **dentro do lote**: candidato ausente cujo patch-id é
igual ao de um candidato **presente** teve o conteúdo aplicado sob outro hash de origem.
Branch de PR rebasada e depois mergeada de volta deixa dois commits de origem com patch
idêntico, e um pick só leva os dois. É o item 3 com o alcance que o custo permite — o lote
tem dezenas de hashes, não 39 mil.
