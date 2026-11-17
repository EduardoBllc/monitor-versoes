# monitor-versoes-github

Host GitHub do [monitor-versoes](../../README.md) (github.com ou GitHub Enterprise Server),
com dois papéis no mesmo pacote:

- **Fonte de tarefas** (`[tarefas] fonte = "github"`): busca as issues da milestone cujo
  título é igual à versão consultada, abertas ou fechadas. Pull requests não entram.
- **Fonte de PR** (`[prs] fonte = "github"`): entrega os commits dos pull requests
  mergeados que chegaram à principal. Veja [Fonte de PR](#fonte-de-pr).

Instalar não liga nada: cada papel só vale com a `fonte` da sua seção.

## Instalação

Escolha o GitHub Issues (tarefas) ou o GitHub (PR) no `monitor-versoes configurar`, ou:

```bash
monitor-versoes plugin instalar "git+https://github.com/EduardoBllc/monitor-versoes#subdirectory=plugins/github"
```

O plugin acompanha a tag do motor, e o `monitor-versoes atualizar-motor` o atualiza junto
(veja "Instalação" no [README principal](../../README.md)).

## Configuração

Esta seção é a da fonte de tarefas; a da fonte de PR está em [Fonte de PR](#fonte-de-pr).

| Onde | Chave | Obrigatória | Significado |
| --- | --- | --- | --- |
| `[tarefas]` | `fonte = "github"` | sim | escolhe o plugin |
| `[tarefas]` | `repo` | sim | repositório das issues, `dono/nome`, ex.: `empresa/produto` |
| `[tarefas]` | `api_url` | não | URL da API; só muda no GitHub Enterprise Server. Padrão: `https://api.github.com`. Deve começar com `https://` |
| `[ambiente]` | `GITHUB_TOKEN` | não | token com leitura das issues |

Sem `GITHUB_TOKEN` só se acessa repo público, e o GitHub limita a 60 requisições por hora
por IP: buscas de versões grandes podem falhar. `repo` e `api_url` também valem em
`[repos.<nome>.tarefas]`. O formato do config está no [README principal](../../README.md).

```toml
[tarefas]
fonte = "github"
repo = "empresa/produto"

[ambiente]
GITHUB_TOKEN = "..."
```

### Token

Em Settings, Developer settings, Personal access tokens:

- **Fine-grained** (recomendado): escolha o repositório e a permissão "Issues: read". Para a
  fonte de PR, acrescente "Pull requests: read" e "Contents: read".
- **Classic**: o escopo `repo`, necessário para repo privado.

Use-o em `GITHUB_TOKEN`.

## ID e referência

O ID da tarefa é o número da issue: `#123` vira `123`. O plugin propõe a referência `#{id}`
(alfabeto `0-9`), então um commit `corrige x #123` é atribuído a `123`.

O commit só é atribuído à issue se a mensagem citar `#<issue>`. O squash acrescenta ao título
o número do PR (`corrige x (#195)`), e não o da issue: sem `#<issue>` na mensagem, o commit
não é achado para a issue. Cite a issue no título ou no corpo usado como mensagem do squash.
Na extração livre (reconstruir o estado, por exemplo), vale a primeira referência da mensagem.

A lista manual (`--task-source manual`) não herda essa referência: nela cada linha leva só
o número, e o repo define `[referencia] padrao = "#{id}"`.

## Fonte de PR

Os commits de cada tarefa saem dos PRs mergeados cujo título ou branch casa com a
referência. Varredura incremental, casamento, cache e filtro pela principal são do motor
([036](../../docs/decisoes/036-fonte-de-pr-plugavel.md)); o plugin só lista os PRs e os
commits de cada um.

| Onde | Chave | Obrigatória | Significado |
| --- | --- | --- | --- |
| `[prs]` | `fonte = "github"` | sim | escolhe o plugin |
| `[prs]` | `api_url` | não | URL da API; só muda no GitHub Enterprise Server. Padrão: `https://api.github.com`. Deve começar com `https://` |
| `[ambiente]` | `GITHUB_TOKEN` | sim | token com leitura de pull requests e do conteúdo do repo; o mesmo da fonte de tarefas |

`[prs] api_url` é independente de `[tarefas] api_url`: quem usa os dois papéis num GitHub
Enterprise Server define as duas. Não há acesso anônimo: sem `GITHUB_TOKEN`, a primeira
busca de commits falha com erro de entrada.

```toml
[prs]
fonte = "github"

[ambiente]
GITHUB_TOKEN = "..."
```

O repositório (`dono/nome`) sai da URL do remote `origin`, em SSH
(`git@host:dono/nome.git`) ou HTTPS (`https://[usuario@]host/dono/nome[.git]`). Não há
chave `repo` em `[prs]`.

### Modos de merge

O GitHub não informa como o PR foi mergeado; o plugin o infere pelo commit de
`merge_commit_sha`:

| Modo | Como se reconhece | Commits devolvidos |
| --- | --- | --- |
| Merge comum | o commit tem dois pais ou mais | os commits do PR, sem merge commits |
| Rebase | um pai, e mesma mensagem e mesma data de autoria do último commit do PR que não é merge commit | os commits da principal que terminam nele, pelo primeiro pai, um para cada commit do PR que não é merge commit |
| Squash | um pai, e não é rebase | só ele |

Na dúvida entre rebase e squash, vale squash: o plugin nunca devolve commit de outro PR. No
rebase, cada commit do caminho é conferido contra o commit do PR na mesma posição, pela
mensagem e pela data de autoria. Um merge commit, um commit não encontrado ou uma divergência
encerra a lista. PR sem `merge_commit_sha`, ou com ele não encontrado, não entrega commit: a tarefa cai no grep da
principal.

A API lista no máximo 250 commits por PR. Num PR maior, o merge comum entrega os que a API
listar e o rebase é tratado como squash.

## Erros

| Situação | Tipo |
| --- | --- |
| `repo` faltando; `api_url` sem `https://` | entrada |
| Fonte de PR sem `GITHUB_TOKEN` | entrada |
| Milestone com o título da versão não existe no repo | entrada |
| 401 sem token (repo exige autenticação) ou com token recusado | entrada |
| 403 sem acesso ao repo | entrada |
| 404: repo inexistente ou token sem acesso a ele; ou API não encontrada na `api_url` | entrada |
| Remote `origin` do qual não se extraem dono e nome (fonte de PR) | resposta inválida |
| Página seguinte da lista fora da `api_url`, inválida ou repetida | resposta inválida |
| Limite de requisições (429, ou 403 com limite esgotado) | serviço indisponível |
| Falha de rede ou outro status | serviço indisponível |

A página seguinte só é seguida se estiver sob a `api_url`, para não enviar o token a outro
host. Milestone sem issues devolve lista vazia. Na fonte de PR, as mensagens citam `[prs]`
onde as de tarefas citam `[tarefas]`, e o 404 do repo cita o `dono/nome` derivado do
`origin` e manda conferir o remote e o `GITHUB_TOKEN`.

### Diagnóstico

Os dois papéis consultam `GET /user` na `api_url`. Com token, o diagnóstico só prova que a
credencial é aceita pelo GitHub; não prova acesso ao repo, o que só a busca confirma. Sem
token, a fonte de tarefas informa "não verificada", porque acessa repo público sem ele; a
fonte de PR falha, porque o token é obrigatório.
