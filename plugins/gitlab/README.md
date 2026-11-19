# monitor-versoes-gitlab

Host GitLab do [monitor-versoes](../../README.md) (gitlab.com ou self-managed), com dois
papéis no mesmo pacote:

- **Fonte de tarefas** (`[tarefas] fonte = "gitlab"`): GitLab Issues, descrita abaixo.
- **Fonte de PR** (`[prs] fonte = "gitlab"`): entrega os commits dos merge requests
  mergeados que chegaram à principal. Veja [Fonte de PR](#fonte-de-pr).

Instalar não liga nada: cada papel só vale com a `fonte` da sua seção.

## Fonte de tarefas

Busca as issues da milestone cujo título é igual à versão consultada, abertas ou fechadas.
A milestone pode ser do projeto ou de um grupo ancestral dele; a de grupo exige GitLab
16.7+ (`include_ancestors`). Em self-managed mais antigo ela não é encontrada e, com
token, vira erro de entrada.

## Instalação

Escolha o GitLab Issues (tarefas) ou o GitLab (PR) no `monitor-versoes configurar`, ou:

```bash
monitor-versoes plugin instalar "git+https://github.com/EduardoBllc/monitor-versoes#subdirectory=plugins/gitlab"
```

O plugin acompanha a tag do motor, e o `monitor-versoes atualizar-motor` o atualiza junto
(veja "Instalação" no [README principal](../../README.md)).

## Configuração

Esta seção é a da fonte de tarefas; a da fonte de PR está em [Fonte de PR](#fonte-de-pr).

| Onde | Chave | Obrigatória | Significado |
| --- | --- | --- | --- |
| `[tarefas]` | `fonte = "gitlab"` | sim | escolhe o plugin |
| `[tarefas]` | `projeto` | sim | caminho completo (`grupo/subgrupo/nome`) ou ID numérico do projeto |
| `[tarefas]` | `url` | não | URL do GitLab; só muda em self-managed. Padrão: `https://gitlab.com`. Deve começar com `https://` |
| `[ambiente]` | `GITLAB_TOKEN` | não | token com escopo `read_api` |

Sem `GITLAB_TOKEN` só se acessa projeto público. Além disso, a API do GitLab responde 401 na
lista de milestones mesmo em projeto público, então sem token o plugin não confere se a
milestone existe: uma versão inexistente (digitada errada) aparece como versão sem tarefas.
Com token, versão inexistente é erro de entrada.

`projeto` e `url` também valem em `[repos.<nome>.tarefas]`. O formato do config está no
[README principal](../../README.md).

```toml
[tarefas]
fonte = "gitlab"
projeto = "empresa/produto"

[ambiente]
GITLAB_TOKEN = "..."
```

### Token

Em Preferences, Access tokens (pessoal) ou Settings, Access tokens (do projeto ou do grupo),
crie um token com o escopo `read_api` e use-o em `GITLAB_TOKEN`.

## ID e referência

Vale para a fonte de tarefas.

O ID da tarefa é o `iid` da issue (o número exibido no projeto): `#123` vira `123`. O plugin
propõe a referência `#{id}` (alfabeto `0-9`), então um commit `corrige x #123` é atribuído a
`123`.

A lista manual (`--task-source manual`) não herda essa referência: nela cada linha leva só
o número, e o repo define `[referencia] padrao = "#{id}"`.

## Fonte de PR

Os commits de cada tarefa saem dos MRs mergeados cujo título ou branch casa com a
referência. Varredura incremental, casamento, cache e filtro pela principal são do motor
([036](../../docs/decisoes/036-fonte-de-pr-plugavel.md)); o plugin só lista os MRs e os
commits de cada um.

| Onde | Chave | Obrigatória | Significado |
| --- | --- | --- | --- |
| `[prs]` | `fonte = "gitlab"` | sim | escolhe o plugin |
| `[prs]` | `url` | não | URL do GitLab; só muda em self-managed. Padrão: `https://gitlab.com`. Deve começar com `https://` |
| `[ambiente]` | `GITLAB_TOKEN` | sim | token com escopo `read_api`; o mesmo da fonte de tarefas |

`[prs] url` é independente de `[tarefas] url`: quem usa os dois papéis num self-managed define
as duas. Não há acesso anônimo, nem para projeto público: sem `GITLAB_TOKEN`, a primeira
busca de commits falha com erro de entrada.

```toml
[prs]
fonte = "gitlab"

[ambiente]
GITLAB_TOKEN = "..."
```

O caminho do projeto (`grupo/subgrupo/nome`, com quantos subgrupos houver) sai da URL do
remote `origin`, em SSH (`git@host:grupo/nome.git`, `ssh://git@host[:porta]/grupo/nome.git`)
ou HTTPS (`https://[usuario@]host[:porta]/grupo/nome[.git]`). Numa instância em subcaminho
(`[prs] url = "https://empresa.com/gitlab"`), o subcaminho é removido do remote HTTPS só
quando esquema, host e porta batem com a `[prs] url`; remote SSH nunca é alterado. Não há chave `projeto` em `[prs]`.

### Squash

| Caso | Commits devolvidos |
| --- | --- |
| MR com `squash_commit_sha` | só o commit dele, no lugar dos originais |
| Os demais (merge commit, semilinear, fast-forward) | os commits do MR, sem merge commits |

Com squash, o commit vai para a tarefa pelo título ou branch do MR, mesmo que a mensagem
dele não cite a referência. Em instância antiga, um MR com squash e sem `squash_commit_sha`
cai no segundo caso: os originais não estão na principal, e a tarefa cai no grep. Um 404 em qualquer
consulta dos commits do MR (o MR, o commit de squash, qualquer página da lista de commits do
MR ou um commit dela) devolve lista vazia, sem erro, e a tarefa também cai no grep.

## Erros

Valem para os dois papéis; na fonte de PR, as mensagens citam `[prs] url` onde as de tarefas
citam `[tarefas] url`.

| Situação | Tipo |
| --- | --- |
| `projeto` faltando (tarefas); `url` sem `https://` | entrada |
| Fonte de PR sem `GITLAB_TOKEN` | entrada |
| Com token, milestone com o título da versão não existe | entrada |
| 401 sem token (exige autenticação) ou com token recusado | entrada |
| 403 sem acesso ao projeto | entrada |
| 404: projeto inexistente ou token sem acesso; ou API não encontrada na `url` | entrada |
| Remote `origin` do qual não se extraem grupo e nome (fonte de PR) | resposta inválida |
| Página seguinte da lista fora da `url` configurada, inválida ou repetida | resposta inválida |
| Limite de requisições (429) | serviço indisponível |
| Falha de rede ou outro status | serviço indisponível |

A página seguinte só é seguida se estiver sob a `url` configurada, para não enviar o token a
outro host. Milestone sem issues devolve lista vazia. Na fonte de PR, o 404 do projeto cita o
caminho derivado do `origin` e manda conferir o remote e o `GITLAB_TOKEN`.

### Diagnóstico

Os dois papéis consultam `GET /api/v4/user` na `url`. Sem token, a fonte de tarefas informa
"não verificada": não há o que checar; a fonte de PR falha, porque o token é obrigatório. Com
token, o diagnóstico só prova que a credencial é aceita pelo GitLab; não prova acesso ao projeto. Um token só com
`read_user` passa no diagnóstico e falha na busca.
