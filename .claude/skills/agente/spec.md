# Redator de spec

Você escreve ou revisa a seção `## Spec` de uma issue. Devolve o caminho de um arquivo
que começa com `## Spec`; o agente publica no corpo.

## Entrada

- O corpo da issue. A descrição original fica intacta: você não a reescreve.
- Os comentários. Em `fase:spec`, os comentários do dono depois da spec atual
  dizem o que mudar; a nova versão substitui a seção inteira.
- O código e a documentação do repo, para não especificar o que já existe nem
  contradizer uma decisão em [docs/decisoes/](../../../docs/decisoes/README.md).

## Formato

A seção traz, nesta ordem:

- **Comportamento:** o que muda para quem usa, em subseções `###` quando houver partes
  distintas. Tabela quando a regra for uma matriz.
- **Fora do escopo:** o que alguém poderia supor incluído e não está.
- **`### Critérios de aceite`:** verificáveis, um por item.
- Última linha da seção: `Plano: necessário, porque…` ou `Plano: dispensável, porque…`.

Tudo isso fica dentro de `## Spec`, só com subseções `###`: um `## ` dentro dela seria
lido como o fim da spec e a próxima revisão o preservaria fora dela.

Spec diz o quê e por quê, não como: nada de passo a passo de implementação. Decisão que
só o dono pode tomar vira pergunta explícita na spec, não suposição.

## Publicar

O resto do corpo fica intacto: a revisão substitui só de `## Spec` até o próximo `## `.

```bash
gh issue view N --json body --jq .body > corpo.md
if grep -q '^## Spec$' corpo.md; then
  awk -v f=spec.md '/^## Spec$/{while((getline l<f)>0)print l; skip=1; next}
    skip && /^## /{skip=0} !skip' corpo.md > novo.md
else
  { cat corpo.md; echo; cat spec.md; } > novo.md
fi
gh issue edit N --body-file novo.md
```
