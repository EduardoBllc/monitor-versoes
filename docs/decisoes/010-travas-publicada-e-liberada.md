# Duas travas: `publicada` e `liberada`

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [005](005-alvo-distribuicao-entre-versoes.md),
  [022](022-fetch-origin-em-todo-entry-point.md)

```
liberada(X.Y.Z):   a tag X.Y.Z existe?                                 # SÓ a tag
publicada(X.Y.Z):  liberada(X.Y.Z) OU existe branch remota X.Y.Z?
```

- **`publicada`** trava o **rebuild**: `criar` recusa se a versão já tem tag ou já existe como
  branch remota — impede recriar do zero uma branch que outra máquina já tem. Enquanto a
  branch é nova e não publicada, recriar do zero a cada tentativa é permitido e útil (o
  `rerere` replica as resoluções), então dá para refazer a composição antes do primeiro build.
- **`liberada`** **congela**: `atualizar` recusa por completo, e o snapshot das atribuições
  vira imutável. Tag só nasce quando a versão sai em produção, então "com tag" = imutável.
  Tarefa esquecida vai para a **próxima versão em construção**
  ([005](005-alvo-distribuicao-entre-versoes.md)), nunca para a que já saiu.

A recusa do `atualizar` roda **antes** de tocar a worktree ou a branch, e o `--continue` a
reavalia — a versão pode ter sido liberada enquanto um conflito estava aberto. Nenhum commit
entra na branch de uma versão liberada por essa via.

Para recalcular uma versão liberada sem descongelar o snapshot dela existe o modo de
auditoria: usa a tag como alvo e pula toda escrita no estado e na worktree.

Como o congelamento é imposto: [011](011-congelamento-no-banco.md).
