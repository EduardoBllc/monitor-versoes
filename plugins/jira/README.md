# monitor-versoes-jira

Fonte de tarefas do [monitor-versoes](../../README.md) para o **Jira Cloud**. Só o Jira
Cloud é suportado: **o Jira Data Center/Server não é suportado**.

Busca as issues do projeto cuja `fixVersion` é a versão consultada, de todos os tipos.

## Instalação

```bash
uv tool install git+https://github.com/EduardoBllc/monitor-versoes \
  --with "monitor-versoes-jira @ git+https://github.com/EduardoBllc/monitor-versoes#subdirectory=plugins/jira"
```

Sobre fixar tag e atualizar, veja "Instalação" no [README principal](../../README.md).

## Configuração

| Onde | Chave | Obrigatória | Significado |
| --- | --- | --- | --- |
| `[tarefas]` | `fonte = "jira"` | sim | escolhe o plugin |
| `[tarefas]` | `url` | sim | site do Jira Cloud, ex.: `https://empresa.atlassian.net` |
| `[tarefas]` | `projeto` | sim | chave do projeto Jira, ex.: `PROJ` |
| `[ambiente]` | `JIRA_EMAIL` | sim | e-mail da conta Atlassian |
| `[ambiente]` | `JIRA_TOKEN` | sim | API token da conta |

`url` e `projeto` também valem em `[repos.<nome>.tarefas]`, para repos em projetos Jira
diferentes. O formato do config está no [README principal](../../README.md).

```toml
[tarefas]
fonte = "jira"
url = "https://empresa.atlassian.net"
projeto = "PROJ"

[ambiente]
JIRA_EMAIL = "voce@empresa.com"
JIRA_TOKEN = "..."
```

### API token

Em [id.atlassian.com](https://id.atlassian.com) vá em Segurança, API tokens, e crie um token.
Use-o em `JIRA_TOKEN`, com o e-mail da mesma conta em `JIRA_EMAIL`.

## ID e referência

O ID da tarefa é só o número: a issue `PROJ-123` vira `123`. O plugin propõe a referência
`PROJ-{id}` (alfabeto `0-9`), então um commit `PROJ-123 corrige x` é atribuído a `123`.

A lista manual (`--task-source manual`) não herda essa referência: nela cada linha leva só
o número, e o repo define `[referencia] padrao = "PROJ-{id}"`.

## Erros

Chave que falta, credencial recusada (401/403) e versão ou projeto inexistente na consulta
(400) são erros de entrada, que citam o que corrigir. Falha de rede ou outro status indica
o Jira indisponível. Versão sem issues devolve lista vazia.
