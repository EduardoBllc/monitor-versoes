# monitor-versoes-github

Fonte de tarefas do [monitor-versoes](../../README.md) para o **GitHub Issues**
(github.com ou GitHub Enterprise Server).

Busca as issues da milestone cujo título é igual à versão consultada, abertas ou fechadas.
Pull requests não entram.

## Instalação

```bash
uv tool install git+https://github.com/EduardoBllc/monitor-versoes@v0.2.0 --with "monitor-versoes-github @ git+https://github.com/EduardoBllc/monitor-versoes@v0.2.0#subdirectory=plugins/github" # x-release-please-version
```

As tags do núcleo e do plugin devem ser a mesma. Para atualizar, rode o comando de novo com a
nova tag nas duas URLs (veja "Instalação" no [README principal](../../README.md)).

## Configuração

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

- **Fine-grained** (recomendado): escolha o repositório e a permissão "Issues: read".
- **Classic**: o escopo `repo`, necessário para repo privado.

Use-o em `GITHUB_TOKEN`.

## ID e referência

O ID da tarefa é o número da issue: `#123` vira `123`. O plugin propõe a referência `#{id}`
(alfabeto `0-9`), então um commit `corrige x #123` é atribuído a `123`.

No GitHub, a mensagem de um merge com squash traz o número do PR (`corrige x (#195)`), que
também casa com `#{id}`. Esse número só é atribuído a uma tarefa se existir uma issue com ele
na versão.

A lista manual (`--task-source manual`) não herda essa referência: nela cada linha leva só
o número, e o repo define `[referencia] padrao = "#{id}"`.

## Erros

| Situação | Tipo |
| --- | --- |
| `repo` faltando; `api_url` sem `https://` | entrada |
| Milestone com o título da versão não existe no repo | entrada |
| 401 sem token (repo exige autenticação) ou com token recusado | entrada |
| 403 sem acesso ao repo | entrada |
| 404: repo inexistente ou token sem acesso a ele | entrada |
| Limite de requisições (429, ou 403 com limite esgotado) | serviço indisponível |
| Falha de rede ou outro status | serviço indisponível |

Milestone sem issues devolve lista vazia.

### Diagnóstico

Sem token, o diagnóstico informa "não verificada": não há o que checar. Com token, ele só
prova que a credencial é aceita pelo GitHub; não prova acesso ao repo, o que só a busca
confirma.
