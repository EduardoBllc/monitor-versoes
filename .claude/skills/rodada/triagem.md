# Triagem

Você decide, para cada issue do lote, se ela está pronta para entrar no fluxo. Não
escreve spec nem mexe em labels: devolve o veredito e o comentário; a rodada publica.

## Uma issue elaborada tem

- **Problema:** o que está errado ou falta, e para quem.
- **Escopo:** o que entra e, quando houver dúvida, o que fica de fora.
- **Critério de aceite verificável:** algo que se confere rodando, lendo ou medindo.
- **Nenhuma decisão em aberto:** pergunta que só o dono responde não pode sobrar.

Leia o corpo e os comentários. Detalhe de implementação não é exigência: a spec cuida
disso.

## Saída

Por issue, `completa` ou `incompleta` e o texto do comentário:

```markdown
<!-- rodada:triagem -->
**Triagem:** completa | incompleta

- <o que falta, um item por lacuna> | <por que está pronta, em uma ou duas linhas>
```

Na incompleta, cada item diz o que falta e, se der, traz uma pergunta direta ao dono.
