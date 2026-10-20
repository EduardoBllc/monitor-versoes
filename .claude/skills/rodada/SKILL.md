---
name: rodada
description: Use quando o dono pedir uma rodada, `/rodada`, para processar issues ou avançar issues do monitor-versoes pelo ciclo de labels `estado:` (triagem, spec, plano, execução). Aceita milestone ou `#N` como filtro.
---

# Rodada

Avança cada issue aberta **um passo** no [ciclo da issue](../../../CONTRIBUTING.md#ciclo-da-issue)
e para no próximo portão humano. O significado de cada label está lá; aqui está só o
algoritmo.

Regras invioláveis:

- **Nunca faça merge.** A rodada para no PR; o dono mergeia.
- Um passo por issue por rodada.
- Só issues. Pull requests nunca são processados.
- No máximo 3 subagentes ao mesmo tempo.
- Todo comentário da rodada começa com o marcador `<!-- rodada:<papel> -->`
  (`triagem`, `plano`, `travada`). É ele que diz o que a rodada já escreveu.

Nos comandos, `{owner}` e `{repo}` ficam literais (o `gh api` os preenche) e `{dono}` é
`gh repo view --json owner --jq .owner.login`.

## 1. Argumento

- milestone: `gh issue list --state open --milestone "<milestone>" ...`;
- `#N`: só a issue N. Se `gh api repos/{owner}/{repo}/issues/N --jq .pull_request` não vier
  vazio, é PR: avise e pare;
- nenhum: todas as issues abertas.

## 2. Coleta

```bash
gh issue list --state open --json number,title,labels,body,updatedAt --limit 200
gh api repos/{owner}/{repo}/issues/N/dependencies/blocked_by --jq '[.[] | select(.state == "open")] | length'
```

O estado é a label `estado:` da issue; sem nenhuma, conta como `estado:rascunho`.

## 3. Filtro

Pule a issue, e diga o motivo no relatório, quando:

- tem `ia:travada`;
- tem bloqueio aberto (contagem acima maior que zero);
- tem mais de uma label `estado:`. Não adivinhe qual vale: comente
  `<!-- rodada:travada -->` pedindo ao dono que deixe só uma, aplique `ia:travada` e não
  mexa nas labels `estado:`. Assim as rodadas seguintes não repetem o comentário.

## 4. Despacho

| Estado | Passo |
| --- | --- |
| `rascunho` | Triagem (seção 5), se a regra de repetição deixar. |
| `elaborada`, `spec-ajustes` | Spec (seção 6). → `spec-em-revisão` |
| `spec-aprovada`, `plano-ajustes` | Plano (seção 6). → `plano-em-revisão` |
| `aguardando-execução` | Execução (seção 7). → `em-execução` |
| `spec-em-revisão`, `plano-em-revisão`, `em-execução` | Nada; esperando o dono ou o PR. |

## 5. Triagem

**Repetição.** Triagem só roda se a issue nunca foi triada, ou se mudou depois da
última triagem. Seja `T` o `created_at` do último comentário `rodada:triagem`:

```bash
gh api repos/{owner}/{repo}/issues/N/comments --paginate \
  --jq '.[] | [.created_at, .user.login, (.body | startswith("<!-- rodada:triagem -->"))] | @tsv'
gh api graphql -F owner='{owner}' -F name='{repo}' -F n=N \
  -f query='query($owner:String!,$name:String!,$n:Int!){repository(owner:$owner,name:$name){issue(number:$n){lastEditedAt}}}' \
  --jq .data.repository.issue.lastEditedAt
```

Refaça se não há `T`, se `lastEditedAt > T` (vazio = nunca editada) ou se `{dono}` comentou depois de `T`.
Mudança só de label não conta.

**Execução.** Um único subagente, em lote, com [triagem.md](triagem.md) e a lista das
issues (corpo e comentários). Ele devolve, por issue, `completa` ou `incompleta` e o
texto do comentário. A rodada publica:

- incompleta: `gh issue comment N --body-file <arquivo>` (o que falta) e
  `--remove-label ia:elaborada` se ela estiver lá;
- completa: o comentário com o porquê e `gh issue edit N --add-label ia:elaborada`.

## 6. Spec e plano

Um subagente redator por issue, com [spec.md](spec.md) ou [plano.md](plano.md). O ciclo:

1. o redator escreve o documento num arquivo e devolve o caminho;
2. um subagente **novo** roda com [revisor.md](revisor.md), recebendo só o documento e a
   issue;
3. a rodada repassa a crítica ao mesmo redator (SendMessage), que corrige o arquivo;
4. a rodada publica e troca a label. Não há segunda revisão.

**Publicar a spec.** A descrição original fica intacta; `## Spec` é sempre a última
seção do corpo, e uma revisão a substitui:

```bash
gh issue view N --json body --jq .body > corpo.md
awk '/^## Spec$/{exit} {print}' corpo.md > novo.md   # tudo antes da spec antiga
cat spec.md >> novo.md                                # spec.md começa com "## Spec"
gh issue edit N --body-file novo.md
```

**Publicar o plano.** Um só comentário de plano por issue; uma revisão o edita:

```bash
gh api repos/{owner}/{repo}/issues/N/comments --paginate \
  --jq '.[] | select(.body | startswith("<!-- rodada:plano -->")) | .id' | tail -1
gh api -X PATCH repos/{owner}/{repo}/issues/comments/<id> -F body=@plano.md   # se achou
gh issue comment N --body-file plano.md                                # se não achou
```

## 7. Execução

1. Antes de despachar, troque a label para `estado:em-execução`. Ela é a trava.
2. Um subagente por issue, com `isolation: "worktree"` e [execucao.md](execucao.md).
3. Ele devolve a URL do PR ou o motivo da falha.

## 8. Troca de label

Sempre num só comando, removendo a anterior:

```bash
gh issue edit N --remove-label "estado:<anterior>" --add-label "estado:<nova>"
```

Ao sair de `estado:elaborada`, inclua `--remove-label ia:elaborada` se ela estiver na
issue. Issue sem label `estado:` (rascunho implícito) não tem o que remover.

## 9. Falha

Portão vermelho, spec ambígua na execução, conflito, subagente sem resultado:

1. comente `<!-- rodada:travada -->` com o motivo;
2. aplique `ia:travada`;
3. volte a label ao estado anterior ao passo (na execução, `em-execução` →
   `aguardando-execução`).

## 10. Relatório

Uma linha por issue tocada ou pulada:

```
#N  <estado anterior> → <estado novo>  <link do comentário, do corpo ou do PR>
#N  pulada: <motivo>
```
