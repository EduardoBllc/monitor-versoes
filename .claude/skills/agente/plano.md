# Redator de plano

Você escreve ou revisa o plano de uma issue com spec aprovada. Devolve o caminho de um
arquivo; o agente o publica como comentário.

## Entrada

- A issue: o comentário `<!-- agente:spec -->` é o contrato.
- Em `fase:plano`, o plano atual (comentário `<!-- agente:plano -->`) e os
  comentários do dono depois dele. A nova versão substitui o plano inteiro.
- O código e os padrões de [código](../../../docs/padroes/codigo.md) e de
  [teste](../../../docs/padroes/testes.md).

## Formato

O arquivo começa com `<!-- agente:plano -->` na primeira linha, seguido de:

- `# Plano — <título da issue>`, com **Objetivo** (uma frase), **Arquitetura** (duas ou
  três) e **Spec:** `comentário fixado desta issue (#N)`.
- `## Restrições globais`: os valores exatos que a spec fixa e valem para todas as
  tarefas.
- `## Pontos de atenção na revisão`: as entradas ou falhas que a spec implica e nenhum
  teste cobre, uma por linha.
- `### Tarefa N: <nome>`, cada uma com **Arquivos** (criar, modificar e testar, com o
  caminho exato) e passos em checkbox. Cada passo é uma ação com resultado verificável:
  o teste com suas asserções, a assinatura do código, ou o comando e a saída esperada.
  A tarefa termina com `make check` verde e um commit.

O plano decide o que o executor não decidiria sozinho (arquivos, nomes, assinaturas,
valores, testes) e não transcreve o código. Se a skill superpowers:writing-plans estiver
disponível, ela detalha esse formato; este arquivo basta sem ela.

O plano cobre só a spec. O que ela não pede não entra; ambiguidade da spec vira pergunta
no topo do plano, não suposição.

## Publicar

Um só comentário de plano por issue; uma revisão o edita.

```bash
gh api repos/{owner}/{repo}/issues/N/comments --paginate \
  --jq '.[] | select(.body | startswith("<!-- agente:plano -->")) | .id' | tail -1
gh api -X PATCH repos/{owner}/{repo}/issues/comments/<id> -F body=@plano.md   # se achou
gh issue comment N --body-file plano.md                                      # se não achou
```
