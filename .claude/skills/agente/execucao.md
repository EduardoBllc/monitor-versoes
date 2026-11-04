# Executor

Você implementa uma issue aprovada ou atende o dono num PR do agente. **Nunca faça
merge.** No Actions, o workflow já deixou a identidade git do bot configurada e o checkout na `main`.

## Implementar

Fase `fase:execução`.

1. Leia a issue: o comentário `<!-- agente:spec -->` é o contrato; o comentário
   `<!-- agente:plano -->`, quando existe, é o caminho. Sem plano, a spec basta. Na
   pequena, o corpo elaborado é o contrato.
2. Comente na issue que vai executar e o que fará, em uma linha. A vez não é do dono:
   sem menção.
3. Crie a branch `issue-N-<slug>` a partir da `main`.
4. Implemente seguindo o plano ou a spec, com as regras do
   [AGENTS.md](../../../AGENTS.md) e do [CONTRIBUTING.md](../../../CONTRIBUTING.md).
5. Rode `make check`. Verde é requisito; diga se a integração rodou ou pulou.
6. Commits em português, push e PR com o
   [template](../../../.github/pull_request_template.md) e `Closes #N`.
7. Comente na issue o link do PR, mencionando o dono: a vez passa a ser dele.

Não edite comentário que já existe, fora o do plano: o corpo do PR vai só por
`gh pr create` ou `gh pr edit`, e aviso ao dono é sempre comentário novo.

## PR

Fase `fase:pr`.

- Em evento de PR, rode `gh pr checkout <PR>` primeiro: o checkout do workflow é da
  `main`.
- No `workflow_run` da "Revisão IA", leia o último comentário de resumo dela no PR (o de
  `github-actions[bot]` que tem `**Veredito:**`) e conte quantos desse autor há. Pare e mencione o dono, dizendo por quê,
  se o veredito for `aprovaria` ou se já houver 3. Senão, trate os apontamentos (threads e
  resumo), responda e resolva as threads da IA que atendeu, como nas do dono, e faça um
  único push no fim: o push dispara a próxima revisão. Nunca peça review. Sem nada a
  commitar, mencione o dono e pare.
- Em pedido do dono, faça o commit no branch do PR, responda na thread e resolva-a, no
  formato do [CONTRIBUTING.md](../../../CONTRIBUTING.md#fluxo). Se for pergunta, só
  responda.
- Resolver thread: `gh api graphql` com a mutation `resolveReviewThread`.

## Quando falha

Pare e comente o motivo, sem abrir PR, quando:

- o `make check` fica vermelho e a causa não está no escopo da issue;
- a spec é ambígua e seguir exigiria adivinhar uma decisão do dono;
- há conflito com a `main` que muda o que a spec pede.

Falha de ambiente se declara, não se contorna.
