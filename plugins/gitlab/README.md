# monitor-versoes-gitlab

Fonte de tarefas do [monitor-versoes](../../README.md) para o **GitLab Issues**
(gitlab.com ou self-managed).

Busca as issues da milestone cujo título é igual à versão consultada, abertas ou fechadas.
A milestone pode ser do projeto ou de um grupo ancestral dele.

## Instalação

```bash
uv tool install git+https://github.com/EduardoBllc/monitor-versoes@v0.2.0 --with "monitor-versoes-gitlab @ git+https://github.com/EduardoBllc/monitor-versoes@v0.2.0#subdirectory=plugins/gitlab" # x-release-please-version
```

As tags do núcleo e do plugin devem ser a mesma. Para atualizar, rode o comando de novo com a
nova tag nas duas URLs (veja "Instalação" no [README principal](../../README.md)).

## Configuração

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

O ID da tarefa é o `iid` da issue (o número exibido no projeto): `#123` vira `123`. O plugin
propõe a referência `#{id}` (alfabeto `0-9`), então um commit `corrige x #123` é atribuído a
`123`.

A lista manual (`--task-source manual`) não herda essa referência: nela cada linha leva só
o número, e o repo define `[referencia] padrao = "#{id}"`.

## Erros

| Situação | Tipo |
| --- | --- |
| `projeto` faltando; `url` sem `https://` | entrada |
| Com token, milestone com o título da versão não existe | entrada |
| 401 sem token (exige autenticação) ou com token recusado | entrada |
| 403 sem acesso ao projeto | entrada |
| 404: projeto inexistente ou token sem acesso; ou API não encontrada na `url` | entrada |
| Página seguinte da lista fora da `url` configurada, inválida ou repetida | resposta inválida |
| Limite de requisições (429) | serviço indisponível |
| Falha de rede ou outro status | serviço indisponível |

A página seguinte só é seguida se estiver sob a `url` configurada, para não enviar o token a
outro host. Milestone sem issues devolve lista vazia.

### Diagnóstico

Sem token, o diagnóstico informa "não verificada": não há o que checar. Com token, ele só
prova que a credencial é aceita pelo GitLab; não prova acesso ao projeto. Um token só com
`read_user` passa no diagnóstico e falha na busca.
