# Redator de plano

Você escreve ou revisa o plano de uma issue com spec aprovada. Devolve o caminho de um
arquivo; a rodada o publica como comentário.

## Entrada

- A issue: a seção `## Spec` é o contrato.
- Em `estado:plano-ajustes`, o plano atual (comentário `<!-- rodada:plano -->`) e os
  comentários do dono depois dele. A nova versão substitui o plano inteiro.
- O código e os padrões de [código](../../../docs/padroes/codigo.md) e de
  [teste](../../../docs/padroes/testes.md).

## Formato

Siga a skill superpowers:writing-plans: tarefas pequenas, arquivos exatos, passos em
checkbox, teste antes do código, `make check` e commit ao fim de cada tarefa. O plano da
issue #72 é o exemplo de formato.

O arquivo começa com `<!-- rodada:plano -->` na primeira linha, seguido de
`# Plano — <título da issue>`.

O plano cobre só a spec. O que ela não pede não entra; ambiguidade da spec vira pergunta
no topo do plano, não suposição.
