# monitor-versoes

Ferramenta CLI-first para montar e auditar branches de versão de release. Responde a uma
pergunta só: _"esta versão está com **todos** os commits que deveria?"_.

A dificuldade é que versões são montadas por cherry-pick, e cherry-pick troca o hash —
comparar hashes não responde nada. O `monitor-versoes` cruza três fontes:

| Fonte | Representa |
| --- | --- |
| **rastreador de tasks** (plugin da config, ou lista manual) | o que _deveria_ estar na versão |
| **estado** (SQLite) | o que a ferramenta _declarou_ ter colocado |
| **git** (trailer do `cherry-pick -x`) | o que está _de fato_ aplicado |

A versão só fica verde quando as três concordam. O porquê de cada decisão está em
[docs/decisoes/](docs/decisoes/README.md).

## Premissas

A ferramenta assume um fluxo de release específico — se o seu for diferente, ela não serve
sem adaptação:

- **Uma versão é uma branch;** ao ser liberada, recebe uma tag criada pelo processo de
  release (a ferramenta só lê). O padrão é a branch e a tag com o número puro (`1.2.0`) e a
  principal `main`; os três nomes se trocam pela config.
- **Esquema de versão:** o padrão é o `semver` (`X.Y.0` sai da principal, `X.Y.Z` da
  `X.Y.(Z-1)` se existir, senão da `X.Y.0`); outro esquema se escolhe pela config.
- **Atribuição:** o padrão é a `exata` (o alvo de `V` são as tarefas marcadas em `V`); a
  `composta` puxa também as abertas menores e as liberadas após o corte.
- **Commits citam a task** na mensagem pelo padrão de referência (por exemplo `ch<num>`).
- **Build está fora:** a ferramenta monta e verifica, não constrói.

## Pré-requisitos

| Ferramenta | Para quê | Instalação |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | dependências e Python 3.14 (o `uv` baixa o Python se faltar) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| git | os repositórios auditados | Debian/Ubuntu: `sudo apt install git`; macOS: `xcode-select --install` |

## Instalação

Em um diretório de trabalho qualquer (não precisa clonar o repositório):

```bash
uv tool install git+https://github.com/EduardoBllc/monitor-versoes
```

O primeiro uso cria o estado e as tabelas: não há banco a subir nem migração a rodar (veja
"Estado").

Com a sugestão de resolução por IA (provedor `anthropic`, veja "Sugestão de resolução por IA"):
`uv tool install 'monitor-versoes[anthropic] @ git+https://github.com/EduardoBllc/monitor-versoes'`.

Com plugins: `uv tool install git+https://github.com/EduardoBllc/monitor-versoes --with <plugin>`.

Para atualizar, `uv tool upgrade monitor-versoes`: busca o último commit da `main` e mantém os
plugins do `--with`. A versão do pacote não muda a cada commit; se o comportamento novo não
aparecer, force com `uv tool upgrade --reinstall monitor-versoes`. Se o `monitor-versoes serve`
estiver rodando, reinicie-o.

Versões antigas instalavam o executável como `motor`; hoje ele é só `monitor-versoes`. Se você
tem inscrições agendadas, rode `monitor-versoes inscricao agendar` de novo depois de atualizar: o
timer do systemd e o LaunchAgent guardam o caminho absoluto do executável antigo, que deixa de
existir. Não há migração automática.

Quem quer contribuir com o código clona o repositório; veja o [CONTRIBUTING.md](CONTRIBUTING.md).

### Configurar o ambiente

Banco e as credenciais das fontes de tarefas e de PR ficam na tabela `[ambiente]` do
`config.toml` central (`~/.config/monitor-versoes/config.toml`, ou
`$XDG_CONFIG_HOME/monitor-versoes/config.toml`), no topo do arquivo. Cada chave é o nome de uma
variável de ambiente, e o motor a exporta no início de todo comando:

```toml
[ambiente]
# Arquivo do estado (opcional; padrão ~/.local/share/monitor-versoes/estado.db)
# DATABASE_SQLITE_PATH = "..."

# Credenciais do host de PR, se houver `[prs] fonte`. O plugin `bitbucket` lê estas:
# BITBUCKET_TOKEN = "..."
# BITBUCKET_EMAIL = "..."

# Chave do provedor de sugestão `anthropic` (só ele a lê; veja "Sugestão de resolução por IA"):
# ANTHROPIC_API_KEY = "..."

# Worktrees de versão mantidas em disco entre operações (padrão 3). Mantendo as últimas
# usadas, o comando seguinte na mesma versão reusa o diretório. 0 = descarta a cada run.
WORKTREES_MANTIDAS = 3

# Credenciais da fonte de tarefas, com os nomes que o plugin dela documenta. Dispensáveis
# se você só usar `--task-source manual`.
```

Valor texto é exportado como está e inteiro vira o texto do número; outro tipo é erro.
Chave presente com valor vazio também conta como definida e vence as outras fontes: deixe
comentada a chave que você define no `.env` ou no shell. A
tabela só vale no topo: `[repos.<nome>.ambiente]` é erro.

Um `.env` no diretório atual, com os mesmos nomes (`WORKTREES_MANTIDAS=3`), continua
valendo como alternativa. Para cada variável vence a primeira fonte que a define:

| Ordem | Fonte |
| --- | --- |
| 1 | `[ambiente]` do config central |
| 2 | `.env` do diretório atual (`.env.development` com `--env development`) |
| 3 | variável já exportada no shell (ou no agendador) |

O `[ambiente]` vence também o `.env.development`: com ele definido, `--env development` não
leva a outro banco.

### Estado

O estado mora num arquivo SQLite local, `~/.local/share/monitor-versoes/estado.db`, ou no
caminho de `DATABASE_SQLITE_PATH`. O primeiro uso cria o arquivo e as tabelas. Depois de
atualizar o motor, `monitor-versoes migrar` leva um estado já existente à revisão nova; o
`monitor-versoes diagnostico` avisa quando falta.

### Configurar por projeto

Um só arquivo TOML, `~/.config/monitor-versoes/config.toml` (ou
`$XDG_CONFIG_HOME/monitor-versoes/config.toml`), em duas camadas mescladas chave a chave: o
topo vale para todos os repos e cada `[repos.<nome>]` o sobrescreve. O `<nome>` é o que você
passa em `--repo`. Banco e credenciais ficam no `[ambiente]` (veja "Configurar o ambiente"). Exemplo:

```toml
[repos.meu-repo]
caminho = "~/Projetos/meu-repo"   # obrigatório: o clone; `~` é expandido
[repos.meu-repo.versao]
piso = "13.0.0"   # menor versão cujas tarefas são buscadas; só vale na seção, sem ele nada é cortado

[versao]
# esquema = "semver"     # esquema de versão (entry point instalado)
# atribuicao = "exata"   # política de atribuição: exata ou composta

[tarefas]
fonte = "minha-fonte"   # fonte de tarefas (entry point instalado); sem ela, só a lista manual
# sistema = 7           # demais chaves: do plugin da fonte, que as documenta

[prs]
# fonte = "bitbucket"   # host de PR (entry point instalado); sem ela, os commits saem só do grep

# Nomes: cada chave é opcional; sem ela vale o que o esquema declara, senão o padrão.
# [liberacao]
# tag = "v{versao}"         # tag que libera a versão; padrão: o critério do esquema ou `{versao}`
# [branches]
# versao = "release/{versao}"   # branch da versão; padrão `{versao}`
# principal = "main"            # branch principal; padrão `main`

[referencia]
# padrao = "ch{id}"   # como a tarefa aparece no commit; o tracker propõe um, a config sobrescreve
```

As chaves abaixo do topo também valem dentro de `[repos.<nome>]` (por exemplo
`[repos.meu-repo.tarefas]`), vencendo o topo. Os templates têm exatamente um `{versao}`. Esquema e política são lidos só quando um comando
os usa, e o `piso` é validado pelo esquema: config inválida não impede `atualizar --abort`.
O porquê: [026](docs/decisoes/026-esquema-e-atribuicao-plugaveis.md).

A fonte de tarefas é um plugin, como o esquema e a atribuição: o nome de um entry point do
grupo `monitor_versoes.tarefas` ou um `modulo:Classe`. O núcleo
não traz fonte própria: sem `fonte`, a primeira busca de tarefas falha pedindo a chave (ou
`--task-source manual --lista <arquivo>`). Fora `fonte`, as chaves de `[tarefas]` são do
plugin, que as recebe como estão e as cobra na primeira busca. O plugin só é carregado
quando um comando busca tarefas ou precisa da referência: fonte inválida não impede
`atualizar --abort`, e `reconstruir-estado` roda sem fonte se houver `[referencia] padrao`.
O porquê: [027](docs/decisoes/027-fonte-de-tarefas-plugavel.md).

O host de PR também é plugin: `[prs] fonte` é um entry point do grupo `monitor_versoes.prs`
ou um `modulo:Classe`, e o pacote traz o `bitbucket`. Não há padrão: sem `fonte`, os commits
saem só do grep na branch principal. Fora `fonte`, as chaves de `[prs]` são do plugin. Como
na fonte de tarefas, o plugin e as credenciais só são cobrados na primeira busca de commits.
Trocar de host zera o que o estado guardou das PRs do repo e a próxima varredura percorre o
histórico inteiro. O porquê: [036](docs/decisoes/036-fonte-de-pr-plugavel.md).
Os repos na config: [029](docs/decisoes/029-repos-na-config-central.md).

#### Vindo de uma versão antiga

Para cada repo que já está no banco, crie `[repos.<nome>]` com o mesmo nome que ele tem lá e
mova para a seção as chaves do antigo `.monitor-versoes.toml` (o `piso` vai para
`[repos.<nome>.versao]`). Um `[versao] piso` no topo do `config.toml` também precisa ir para
as seções: no topo ele é erro de leitura e impede qualquer comando. Quem buscava commits por
PR com `BITBUCKET_TOKEN` adiciona `[prs] fonte = "bitbucket"`: o token sozinho não liga mais
nada, e as flags `--bitbucket-token`/`--bitbucket-email` saíram (use o `[ambiente]`). Confira com
`monitor-versoes diagnostico`. Inscrições antigas são descartadas com um aviso: inscreva de novo com o
nome da seção.

O `padrao` é um template com exatamente um `{id}`; o resto é literal e a caixa é ignorada.
O alfabeto do id (que caracteres ele pode ter) vem do adapter do tracker e a config não o
muda: a fonte pode propor um (por exemplo, só dígitos); sem proposta, valem letras, dígitos, `_` e `-`, com o id
começando por letra ou dígito.

- `padrao = "{id}"` puro pede id com formato distintivo (como `PAY-123`): sem prefixo, a
  primeira palavra de qualquer mensagem vira id (`Merge branch` extrairia `Merge`).
- A lista manual não propõe padrão: sem `padrao` na config, os comandos que precisam dele
  falham pedindo a chave. Com `padrao = "ch{id}"` ela usa o alfabeto padrão, e
  `ch254473-fix` extrai `254473-fix` (com uma fonte que propõe só dígitos, `254473`).

## Verificar que funcionou

1. O CLI responde:

   ```console
   $ monitor-versoes --help
   usage: monitor-versoes [-h] [--env {development,production}] comando ...
   ...
   ```

2. A instalação está íntegra — o diagnóstico checa variáveis, banco, migração, os repos
   configurados e credenciais, e sai com código 1 se alguma peça falhar:

   ```console
   $ monitor-versoes diagnostico
   OK  Variáveis: configuração do estado aceita
   OK  SQLite: conexão funciona
   OK  Migração: revisão e50b3d6e40a1
   OK  Repos: 1 repo(s) configurado(s)
   OK  Tarefas: credenciais aceitas
   não configurado  Fonte de PR: sem [prs] fonte no config.toml central
   ```

   Cada `FALHA` traz a correção na própria linha. Migração pendente se corrige com
   `monitor-versoes migrar` (`monitor-versoes --env development migrar` no desenvolvimento).

## Uso

```bash
monitor-versoes verificar 13.34.0 --repo meu-repo             # verde? tasks, faltantes
monitor-versoes verificar 13.34.0 --repo meu-repo --auditar   # versão liberada, sem escrever
monitor-versoes consulta  13.34.0 --repo meu-repo             # snapshot salvo, sem recalcular
monitor-versoes criar     13.35.0 --repo meu-repo             # cria a branch e compõe
monitor-versoes atualizar 13.35.0 --repo meu-repo             # aplica os commits faltantes
monitor-versoes atualizar 13.35.0 --repo meu-repo --continue  # após resolver conflito
monitor-versoes atualizar 13.35.0 --repo meu-repo --abort
monitor-versoes reconstruir-estado 13.35.0 --repo meu-repo    # regenera o estado a partir do git
monitor-versoes orfaos    13.35.0 --repo meu-repo             # commits sem referência de tarefa e o julgamento
monitor-versoes julgar-orfao 13.35.0 <hash> --repo meu-repo --chamado 123 --motivo "..."  # ou --nenhum
monitor-versoes tui                                           # interface interativa
monitor-versoes serve                                         # interface web local (ver Interface web)
monitor-versoes inscricao adicionar 13.35.0 --repo meu-repo   # atualizar periodicamente (ver Inscrições)
```

Todos os comandos de versão aceitam `--repo` (o nome de uma seção `[repos.<nome>]`),
`--debug`, `--sem-progresso`, `--task-source` e `--lista`. `monitor-versoes <comando> -h` lista
o resto.

### Interface web

`monitor-versoes serve` sobe um daemon local e abre o navegador na interface web. `--porta` muda a porta
(padrão **8765**) e o `--env` global vale como nos outros comandos. Ouve só em `127.0.0.1`.

As operações seguem rodando se a aba fechar. O porquê em
[decisão 030](docs/decisoes/030-front-end-web-spa-com-dist-versionado.md).

Um pick bloqueado por conflito se resolve de dois jeitos, inclusive misturados:

- **Resolver na web**, no painel do bloqueio: para cada arquivo, o editor mostra, como o
  Merge Editor do VS Code, theirs (o commit aplicado) e ours (o alvo) lado a lado e, embaixo,
  o resultado (que parte do que está em disco), com destaque de sintaxe e o que fica fora
  dos conflitos recolhido. Cada conflito tem "Aceitar theirs" e "Aceitar ours" no painel de
  cada lado e, no resultado, "Ambos" e, quando o bloco traz a base, "Usar base"; o
  resultado também se edita à mão, e o Ctrl+Z desfaz. A edição só vai para o disco em
  **Marcar resolvido**, que fica desabilitado enquanto restar marcador. Modify/delete se
  resolve com "Manter arquivo" ou "Apagar arquivo"; binário, rename, add/add sem texto e
  submódulo ficam para o editor local. "Reabrir" desfaz a resolução de um arquivo e volta os marcadores.
- **No seu editor**, na worktree que o painel mostra.

Quando a web resolve um arquivo (**Marcar resolvido**, **Manter arquivo** ou **Apagar
arquivo**), a tela abre o próximo não resolvido na ordem da lista, voltando ao início; um
arquivo que só se resolve no editor local abre com essa instrução. Se não sobrar nenhum
pendente, a web dispara o **Continuar** sozinha. Depois de resolver no editor local, o
**Continuar** é manual. Em qualquer front-end (CLI, TUI e web), o continuar recusa se algum
arquivo ainda não mesclado tiver marcador de conflito no disco, e aponta arquivo e linha. As
regras do conflito estão na [decisão 013](docs/decisoes/013-conflito-e-checkpoint.md).

Se a resolução não deixou alteração nenhuma no alvo, o continuar para e pede confirmação:
**Registrar vazio** (na CLI, `atualizar --continue --allow-empty`) entra com um commit vazio,
com o trailer `-x`, e o commit conta como aplicado; **Abortar** (`--abort`) o descarta.

#### Sugestão de resolução por IA

No editor de conflito, um modelo pode propor o conteúdo de cada bloco aberto. Para ligar,
instale o extra (`monitor-versoes[anthropic]`, veja "Instalação") e configure, no topo do
`config.toml` central (não vale em `[repos.<nome>]`):

```toml
[sugestao]
provedor = "anthropic"
# modelo = "claude-opus-5-5"   # padrão
```

A chave vai no `[ambiente]` como `ANTHROPIC_API_KEY`; outras credenciais da máquina não são
usadas. Sem `[sugestao] provedor`, ou sem o extra, a interface fica como antes.

Em arquivo pendente do tipo `conteudo`, o botão **Sugerir blocos abertos** pede uma proposta
para cada bloco do resultado ainda aberto, e a lente **Sugerir** de um bloco pede só a dele.
A proposta aparece numa faixa abaixo do bloco, com o conteúdo e o "Por quê:", e não muda o
resultado até o **Aplicar**, que vale como decisão do bloco (o Ctrl+Z o desfaz).
**Descartar** some com a faixa. Nada é gravado até o **Marcar resolvido**.

| Vai ao provedor | Não vai |
| --- | --- |
| caminho do arquivo | qualquer outro arquivo do repo |
| os lados (base, ours e theirs) de cada bloco pedido | blocos não pedidos e o trecho que mesclou sem conflito |
| mensagem do commit aplicado | histórico e diff de outros commits |
| identificador da tarefa que a mensagem cita (sem tarefa, não vai) | dados da fonte de tarefas além do identificador |

O porquê em [decisão 038](docs/decisoes/038-sugestao-de-resolucao-por-ia.md).

### Editar a configuração pela interface

Na TUI, a tecla `g` abre a tela de configuração; na web, o botão **Configuração** da barra. As
duas editam o `config.toml` central (geral, por repo e `[ambiente]`), preservam os comentários
do arquivo e validam antes de gravar. Mudanças no `[ambiente]` valem sem reiniciar. Salvar não
consulta o lock do clone: edite por um lugar de cada vez. O porquê:
[033](docs/decisoes/033-config-editavel-pelas-interfaces.md).

Na web, as seções ficam numa lateral por assunto, e os campos de um plugin, na seção que o
escolhe. A barra no topo mostra o que falta (um repo com caminho, a fonte de PR e a de tarefas),
e **Continuar** leva à próxima pendência; a fonte que você não usa pode ser pulada neste
navegador. **Testar**, nas fontes e em cada repo, roda a checagem do `diagnostico` sobre o
formulário, sem gravar nada.

#### Para autores de plugin

Para a tela mostrar as chaves do seu plugin (esquema, atribuição, fonte de tarefas ou host de PR), declare
`campos_config` na classe, uma tupla de `Campo`:

```python
from motor.config import TABELA_AMBIENTE
from motor.config_edicao import Campo, Escopo, TipoCampo


class MinhaFonte:
    campos_config = (
        Campo(
            Escopo.GERAL,
            "tarefas",
            "sistema",
            TipoCampo.INTEIRO,
            "Sistema",
            descricao="Id do sistema no tracker",
            exemplo="7",
        ),
        Campo(
            Escopo.AMBIENTE,
            TABELA_AMBIENTE,
            "MINHA_FONTE_TOKEN",
            TipoCampo.TEXTO,
            "Token",
            segredo=True,
        ),
    )
```

No `[ambiente]`, `tabela` é `TABELA_AMBIENTE`; `segredo=True` esconde o valor na tela.
O atributo `campos_config` é opcional e plugin que falha ao carregar é ignorado; na TUI, a
aba Plugins só aparece quando algum plugin declara campos. Opcionais do `Campo`: `descricao`
(o tooltip da web), `padrao` (o valor sem a chave, mostrado ao lado do campo), `exemplo` (o placeholder da
web) e `backend` (o campo só aparece com aquele `DATABASE_BACKEND`).

Um host de PR implementa a porta `HostPr` (`motor/ports.py`): `prs_mergeadas(desde)`, as PRs
mergeadas desde a data (`None` = histórico inteiro), e `commits_da_pr(pr_id)`, os commits da
PR sem merge commits. O resto (varredura incremental, casamento com a referência, cache e
filtro pela principal) é do núcleo. O construtor recebe só nomeados (`prs`, o `[prs]`
mesclado; `arquivos`, os arquivos lidos; `remote_url`, uma função que devolve a URL do
`origin`) e não faz I/O: credencial e URL se cobram na primeira chamada. Registre a classe no
grupo `monitor_versoes.prs`; `verificar_credenciais()` é opcional e o `diagnostico` a usa.

### Fontes de tasks e de commits

- **Tasks:** a `[tarefas] fonte` da config por padrão. Sem ela, `--task-source manual --lista arquivo.txt` lê um
  id de task por linha (`#` comenta).
- **Commits:** com `[prs] fonte`, os commits de cada task vêm das PRs mergeadas no host
  (o plugin `bitbucket` usa `BITBUCKET_TOKEN` e `BITBUCKET_EMAIL` do `[ambiente]`); o grep
  pela referência em `origin/<principal>` fica como fallback. Sem `fonte`, só o grep.

### Worktrees mantidas em disco

Cada operação levanta a versão numa worktree em `<repo>-worktrees/`. `WORKTREES_MANTIDAS`
(default **3**) diz quantas ficam em disco para o próximo comando reusar em vez de refazer o
checkout; `0` descarta a cada run.

A eviction é por uso mais recente e nunca leva trabalho embora: worktree com alteração não
commitada ou cherry-pick pendente (um `atualizar` esperando `--continue`) é pulada.

### Inscrições

Uma inscrição pede ao motor que rode `atualizar` numa versão de tempos em tempos (aplica os
faltantes e faz push). Ficam num arquivo local, `~/.local/share/monitor-versoes/inscricoes.json`;
o porquê: [028](docs/decisoes/028-inscricoes-fora-do-estado.md).

```bash
monitor-versoes inscricao adicionar 13.35.0 --repo meu-repo --intervalo 1h  # Nm ou Nh, padrão 30m
monitor-versoes inscricao listar                                            # clone, intervalo, última execução
monitor-versoes inscricao remover 13.35.0 --repo meu-repo
monitor-versoes inscricao agendar                                           # instala o disparo a cada minuto
monitor-versoes inscricao agendar --desfazer
monitor-versoes inscricao rodar                                             # o que o agendador chama
```

A identidade é o nome do repo mais a versão; reinscrever só troca o intervalo.
A execução agendada não depende de diretório: não lê `.env` e usa o `[ambiente]` do config
central ou o ambiente do agendador.
Também dá para gerenciar na TUI (tecla `i`) e na web (botão **Inscrições** da barra).

`rodar` executa as inscrições vencidas, uma por processo, e a falha de uma não impede as
outras. O desfecho da última execução aparece no `listar`:

| Desfecho | Significa |
| --- | --- |
| `aplicou` | commits aplicados e push feito |
| `nada` | nada a aplicar |
| `bloqueada` | conflito: checkpoint aberto, sem push |
| `pulada` | cherry-pick pendente na versão (nada roda até `atualizar --continue` ou `--abort`), ou repo ocupado por outra operação do motor (roda de novo na próxima vez que vencer) |
| `encerrada` | versão liberada; a inscrição é removida |
| `erro` | falha, com a mensagem; o processo que morre sem gravar resultado também vira `ERRO` |

`agendar` usa o `monitor-versoes` do `PATH` no momento do comando (caminho absoluto) e instala, no Linux,
o timer de usuário do systemd (`monitor-versoes-inscricoes.timer`) e, no macOS, um LaunchAgent
(`monitor-versoes.inscricoes.plist`). Outro sistema falha com erro de entrada. O agendador roda
sem o agente SSH nem o `PATH` da sua sessão (push por SSH via agente pode falhar e virar `erro`);
no Linux, o timer de usuário só roda fora de uma sessão com `loginctl enable-linger`; no macOS,
a notificação desktop pode falhar num Python fora de um app empacotado (a falha vai para o log).

Notificações desktop (via `desktop-notifier`; falha ao notificar vai para o log e não muda o
desfecho):

- **aplicou commits:** quantos e de quais chamados;
- **bloqueou:** commit, arquivos em conflito e chamados culpados;
- **item vermelho novo:** tarefa ambígua, tarefa sem commits, commit sumido ou conflitante que
  não estava na execução anterior (na primeira, todos);
- **erro:** só o primeiro de uma sequência; `PULADA` no meio não o repete;
- **encerrada:** versão liberada, inscrição removida.

## Problemas comuns

| Sintoma | Causa e saída |
| --- | --- |
| Pedir a sugestão dá erro de chave | Falta `ANTHROPIC_API_KEY` no `[ambiente]`. O erro aparece ao pedir, e o `monitor-versoes diagnostico` aponta a correção. |
| O botão **Sugerir blocos abertos** não aparece e o `diagnostico` pede `monitor-versoes[anthropic]` | O provedor `anthropic` está configurado, mas o extra não está instalado. Reinstale com `uv tool install 'monitor-versoes[anthropic] @ git+https://github.com/EduardoBllc/monitor-versoes'`. |
| `ERROR: banco inacessivel: unable to open database file. Confira DATABASE_SQLITE_PATH ...` | O motor não abre o arquivo do estado. Confira o caminho de `DATABASE_SQLITE_PATH` e as permissões do arquivo e do diretório. |
| `ERROR: o suporte a Postgres no estado foi removido ...` | A configuração ainda tem `DATABASE_BACKEND=postgres` ou as cinco `DATABASE_HOST/PORT/NAME/USER/PASSWORD` ([decisão 035](docs/decisoes/035-estado-local-em-sqlite.md)). Antes de tirá-las, leve o estado para o SQLite com a última versão que tinha Postgres: `uvx --from git+https://github.com/EduardoBllc/monitor-versoes@7e95ad4abcf7ae99013a025ee434bbd28ea06616 motor migrar-estado --de postgresql://<usuario>:<senha>@<host>:<porta>/<banco> --para sqlite:///$HOME/.local/share/monitor-versoes/estado.db`. Depois, tire `DATABASE_BACKEND` e as `DATABASE_*` do `[ambiente]` (ou do `.env`). |
| `ERROR: faltando [tarefas] fonte em ...; ou use --task-source manual --lista <arquivo>` | Nenhuma fonte de tarefas na config. Defina `[tarefas] fonte` no `config.toml` central, ou use a lista manual. |
| `ERROR: .../config.toml: repo 'meu-repo' sem seção [repos.meu-repo] (existentes: ...)` | `--repo` não é o nome de uma seção. Crie `[repos.meu-repo]` no `config.toml` central ou use um nome da lista (`(nenhuma)` se o arquivo não existe). |
| `ERROR: .../config.toml: [repos.meu-repo] caminho é obrigatório` | A seção não tem `caminho`. Aponte para o clone. |
| `ERROR: .../config.toml: [repos.meu-repo] caminho '...' não é um diretório` | O `caminho` não existe. Confira o valor; `monitor-versoes diagnostico` checa todas as seções. |
| `ERROR: repo meu-repo ocupado por outra operação (pid N)` | Outro processo do motor (CLI, TUI, `monitor-versoes serve` ou inscrição) está criando, atualizando ou verificando nesse clone. Espere terminar; `consulta` e `verificar --auditar` rodam assim mesmo. O lock some com o processo, então não há arquivo para apagar. |
| `error: argument --repo: use um nome simples, sem caminho` | `--repo` recebeu um path. Passe só o nome da seção. |

## Próximos passos

- [docs/decisoes/](docs/decisoes/README.md) — o porquê de cada decisão do projeto.
- [CONTRIBUTING.md](CONTRIBUTING.md) — ambiente de desenvolvimento, verificações e fluxo de PR.
- Licença: [MIT](LICENSE).
