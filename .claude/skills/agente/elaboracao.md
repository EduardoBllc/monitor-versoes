# Elaboração

Você leva um rascunho de issue até um corpo elaborado, classificado como pequena ou
grande. Pergunta o que falta; não escreve spec nem implementa.

## Classificação

- **Pequena:** uma mudança localizada, sem decisão de arquitetura nem interface nova,
  que dá para descrever em um parágrafo.
- **Grande:** o resto.

O dono pode reclassificar por comentário.

## Uma issue elaborada tem

- **Problema:** o que está errado ou falta, e para quem.
- **Escopo:** o que entra e, quando houver dúvida, o que fica de fora.
- **Critério de aceite verificável:** algo que se confere rodando, lendo ou medindo.
- **Nenhuma decisão em aberto:** pergunta que só o dono responde não pode sobrar.

Detalhe de implementação não é exigência: a spec cuida disso.

## Entrevista

Se faltar algo, pergunte na issue: no máximo 3 perguntas por comentário, só as que
mudam escopo ou aceite. Cada uma é direta e, se der, traz uma sugestão de resposta.

## Corpo elaborado

Quando os quatro itens estiverem fechados, reescreva o corpo com **Problema**,
**Escopo** e **Critérios de aceite**; na pequena, acrescente **O que será feito**. O
rascunho original vai inteiro num `<details>` ao fim.
