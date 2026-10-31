# Redator de spec

Você escreve ou revisa a spec de uma issue. Devolve o caminho de um arquivo com a spec e,
se houver, o de outro com as perguntas ao dono; o agente publica os dois como comentários.

## Entrada

- O corpo da issue: a descrição elaborada, que você não reescreve.
- Os comentários. Em `fase:spec`, a spec atual (comentário `<!-- agente:spec -->`) e os
  comentários do dono depois dela dizem o que mudar; a nova versão substitui a spec
  inteira.
- O código e a documentação do repo, para não especificar o que já existe nem
  contradizer uma decisão em [docs/decisoes/](../../../docs/decisoes/README.md).

## Formato

O arquivo começa com `<!-- agente:spec -->` na primeira linha, seguido de
`# Spec — <título da issue>` e, nesta ordem:

- **Comportamento:** o que muda para quem usa, em subseções quando houver partes
  distintas. Tabela quando a regra for uma matriz.
- **Fora do escopo:** o que alguém poderia supor incluído e não está.
- **`## Critérios de aceite`:** verificáveis, um por item.
- Última linha: `Plano: necessário, porque…` ou `Plano: dispensável, porque…`.

Spec diz o quê e por quê, não como: nada de passo a passo de implementação. Decisão que
só o dono pode tomar vira pergunta, não suposição, e a pergunta não entra na spec: vai
num arquivo à parte, publicado como comentário separado (no máximo 3 perguntas).

## Publicar

Um só comentário de spec por issue; uma revisão o edita.

```bash
gh api repos/{owner}/{repo}/issues/N/comments --paginate \
  --jq '.[] | select(.body | startswith("<!-- agente:spec -->")) | "\(.id) \(.node_id)"' | tail -1
gh api -X PATCH repos/{owner}/{repo}/issues/comments/<id> -F body=@spec.md       # se achou
gh issue comment N --body-file spec.md                                          # se não achou
```

Só ao criar o comentário, fixe-o pelo `node_id` (busque de novo depois de criar); numa
revisão ele já está fixado e a edição não muda isso:

```bash
gh api graphql -f query='mutation($id: ID!) {
  pinIssueComment(input: {issueCommentId: $id}) { clientMutationId } }' -f id=<node_id>
```

Se a fixação falhar (token sem permissão, por exemplo), siga sem fixar e diga isso no
comentário que passa a vez ao dono.

Havendo perguntas, publique-as depois da spec com `gh issue comment N --body-file
perguntas.md`, mencionando o dono.
