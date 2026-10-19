# Autenticação no Tickio, e o custo do erro tardio

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [005](005-alvo-distribuicao-entre-versoes.md),
  [019](019-montagem-no-front-end.md)

A autenticação no Tickio é por **credencial, não token**: o adapter troca usuário e senha por
um `access` a cada execução. Não existe flag de token. O CLI vive segundos, e reautenticar a
cada run sai mais barato do que reeditar o `.env` toda vez que o JWT expira.

As variáveis do Tickio são cobradas **na primeira busca, não na construção do adapter**. Isso
é deliberado: deixa `reconstruir-estado` e `atualizar --abort` rodarem sem credencial
configurada — são comandos de recuperação que nunca consultam o Tickio. O custo aceito: em
`criar` e `atualizar`, uma credencial faltante só aparece **depois** que o fetch de refs, a
worktree e o registro inicial da versão já aconteceram. O erro chega tarde.

Sem credencial, o alvo não é determinístico; o fallback é a lista manual.
