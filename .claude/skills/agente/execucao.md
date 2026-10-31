# Executor

Você implementa uma issue aprovada ou atende o dono num PR do agente. **Nunca faça
merge.** O workflow já deixou o branch e a identidade do bot configurados.

## Implementar

Fase `fase:execução`.

1. Leia a issue: `## Spec` é o contrato; o comentário `<!-- agente:plano -->`, quando
   existe, é o caminho. Sem plano, a spec basta. Na pequena, o corpo elaborado é o
   contrato.
2. Crie a branch `issue-N-<slug>` a partir da `main`.
3. Implemente seguindo o plano ou a spec, com as regras do
   [AGENTS.md](../../../AGENTS.md) e do [CONTRIBUTING.md](../../../CONTRIBUTING.md).
4. Rode `make check`. Verde é requisito; diga se a integração rodou ou pulou.
5. Commits em português, push e PR com o
   [template](../../../.github/pull_request_template.md) e `Closes #N`.

## PR

Fase `fase:pr`.

- Em evento de PR, rode `gh pr checkout <PR>` primeiro: o checkout do workflow é da
  `main`.
- No `workflow_run` da "Revisão IA", trate uma vez as threads abertas dela e nunca peça
  novo review.
- Em pedido do dono, faça o commit no branch do PR, responda na thread (o que mudou e em
  qual commit, ou por que não mudou) com a assinatura e resolva-a. Se for pergunta, só
  responda.

## Quando falha

Pare e comente o motivo, sem abrir PR, quando:

- o `make check` fica vermelho e a causa não está no escopo da issue;
- a spec é ambígua e seguir exigiria adivinhar uma decisão do dono;
- há conflito com a `main` que muda o que a spec pede.

Falha de ambiente se declara, não se contorna.
