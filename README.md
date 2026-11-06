# monitor-versoes

Ferramenta CLI-first para montar e auditar branches de versão de release. Responde a uma
pergunta só: _"esta versão está com **todos** os commits que deveria?"_.

A dificuldade é que versões são montadas por cherry-pick, e cherry-pick troca o hash —
comparar hashes não responde nada. O `motor` cruza três fontes:

| Fonte | Representa |
| --- | --- |
| **rastreador de tasks** (plugin da config, ou lista manual) | o que _deveria_ estar na versão |
| **estado** (SQLite ou Postgres) | o que a ferramenta _declarou_ ter colocado |
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
| [Docker](https://docs.docker.com/engine/install/) com Compose | só se for usar Postgres no estado (opcional; o padrão é SQLite) | Linux: `curl -fsSL https://get.docker.com \| sh`; macOS: [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/) |
| git | os repositórios auditados | Debian/Ubuntu: `sudo apt install git`; macOS: `xcode-select --install` |

## Instalação

Em um diretório de trabalho qualquer (não precisa clonar o repositório):

```bash
uv tool install git+https://github.com/EduardoBllc/monitor-versoes
motor init                      # escreve compose.yml e .env no diretório atual
```

O estado fica num arquivo SQLite (`~/.local/share/monitor-versoes/estado.db`), criado com as
tabelas no primeiro uso: não há Docker nem migração a rodar. O `compose.yml` só serve ao Postgres
opcional (veja "Estado: SQLite (padrão) ou Postgres").

Com plugins: `uv tool install git+https://github.com/EduardoBllc/monitor-versoes --with <plugin>`.

`motor init` não sobrescreve arquivo existente. Se preferir, copie os dois arquivos abaixo.

`compose.yml`:

<!-- modelo: compose.yml -->
```yaml
# Postgres do estado, opt-in: o padrao do motor e SQLite (sem Docker). Suba este
# servico so com DATABASE_BACKEND=postgres.
services:
  db:
    image: postgres:18-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${DATABASE_NAME}
      POSTGRES_USER: ${DATABASE_USER}
      POSTGRES_PASSWORD: ${DATABASE_PASSWORD}
    ports: ["${DATABASE_PORT}:5432"]
    # /var/lib/postgresql, nao /var/lib/postgresql/data: no postgres:18-alpine o
    # PGDATA e /var/lib/postgresql/18/docker, entao montar em /data criaria um
    # diretorio vazio irmao do PGDATA e os dados sumiriam na recriacao do volume.
    volumes: [pgdata:/var/lib/postgresql]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 10

volumes:
  pgdata:
```

`.env` (modelo `.env.example`):

<!-- modelo: env.example -->
```bash
# Backend do estado: sqlite (padrão, arquivo local, sem Docker) ou postgres.
DATABASE_BACKEND=sqlite
# Arquivo do SQLite (opcional; padrão ~/.local/share/monitor-versoes/estado.db)
# DATABASE_SQLITE_PATH=

# Postgres (opt-in): troque DATABASE_BACKEND para postgres. Estas partes só são
# lidas com esse backend; o compose.yml lê as mesmas variáveis (make db).
DATABASE_HOST=localhost
DATABASE_PORT=5433
DATABASE_NAME=monitor_versoes
DATABASE_USER=motor
DATABASE_PASSWORD=motor

# Bitbucket (opcional — ativa descoberta de commits por PR)
BITBUCKET_TOKEN=
BITBUCKET_EMAIL=

# Worktrees de versao mantidas em disco entre operacoes (default 3).
# Levantar uma worktree e um checkout inteiro; mantendo as ultimas usadas, o
# comando seguinte na mesma versao reusa o diretorio. 0 = descarta a cada run.
WORKTREES_MANTIDAS=3

# Raiz onde --repo <nome> e procurado
PROJECTS_DIR=
```

Quem quer contribuir com o código clona o repositório; veja o [CONTRIBUTING.md](CONTRIBUTING.md).

### Configurar o `.env`

Preencha no `.env`:

- As credenciais da fonte de tarefas, com os nomes que o plugin dela documenta. Dispensáveis
  se você só usar `--task-source manual`.
- `PROJECTS_DIR` — raiz onde `--repo <nome>` é procurado (com `PROJECTS_DIR=/home/voce/Projetos`,
  `--repo meu-repo` é `/home/voce/Projetos/meu-repo`; use path absoluto, `~` não é expandido). Sem ela, passe o path em `--repo`.
- `BITBUCKET_TOKEN`, `BITBUCKET_EMAIL` — opcionais; veja "Fontes de tasks e de commits".

Cada variável está comentada no `.env`.

### Estado: SQLite (padrão) ou Postgres

`DATABASE_BACKEND` escolhe onde o estado mora: `sqlite` (padrão, sem configuração) ou
`postgres`. O arquivo SQLite é `~/.local/share/monitor-versoes/estado.db`, ou o caminho de
`DATABASE_SQLITE_PATH`. Valor desconhecido é erro. No SQLite não há Docker nem migração a rodar:
o primeiro uso cria as tabelas.

Para usar Postgres: suba o banco (`docker compose up -d --wait`, com o `compose.yml` do
`motor init`), defina `DATABASE_BACKEND=postgres` e as cinco
`DATABASE_HOST/PORT/NAME/USER/PASSWORD` no `.env` (só são lidas nesse caso) e rode
`motor migrar` (ou deixe o primeiro comando aplicar as migrações). Se as cinco partes estiverem
preenchidas e `DATABASE_BACKEND` não, o motor usa SQLite e avisa em stderr.

Trocar de backend não leva o estado junto. Copie-o com o comando explícito, que preserva
tudo (inclusive exclusões e registros de "não houve entrega") e só funciona com destino vazio:

```bash
motor migrar-estado --de sqlite:///$HOME/.local/share/monitor-versoes/estado.db \
    --para postgresql://motor:motor@localhost:5433/monitor_versoes
```

Depois, troque `DATABASE_BACKEND` no `.env`: o comando não altera a configuração.

### Cadastrar os repositórios

Cada repositório é cadastrado uma vez, antes do primeiro comando nele:

```bash
motor repo adicionar meu-repo
```

O nome é o do diretório do repositório (o basename do path de `--repo`). O resto do que é
específico do repo vem da config abaixo.

### Configurar por projeto

Dois arquivos TOML, mesclados chave a chave com o do repo vencendo: o padrão do operador em
`~/.config/monitor-versoes/config.toml` (ou `$XDG_CONFIG_HOME/monitor-versoes/config.toml`) e
o específico do projeto em `.monitor-versoes.toml`, na raiz do repositório. Credenciais
continuam no `.env`.

```toml
[versao]
piso = "13.0.0"   # menor versão cujas tarefas são buscadas; sem ele nada é cortado
# esquema = "semver"     # esquema de versão (entry point instalado)
# atribuicao = "exata"   # política de atribuição: exata ou composta

[tarefas]
fonte = "minha-fonte"   # fonte de tarefas (entry point instalado); sem ela, só a lista manual
# sistema = 7           # demais chaves: do plugin da fonte, que as documenta

# Nomes: cada chave é opcional; sem ela vale o que o esquema declara, senão o padrão.
# [liberacao]
# tag = "v{versao}"         # tag que libera a versão; padrão: o critério do esquema ou `{versao}`
# [branches]
# versao = "release/{versao}"   # branch da versão; padrão `{versao}`
# principal = "main"            # branch principal; padrão `main`

[referencia]
# padrao = "ch{id}"   # como a tarefa aparece no commit; o tracker propõe um, a config sobrescreve
```

Os templates têm exatamente um `{versao}`. Esquema e política são lidos só quando um comando
os usa, e o `piso` é validado pelo esquema: config inválida não impede `atualizar --abort`.
O porquê: [026](docs/decisoes/026-esquema-e-atribuicao-plugaveis.md).

A fonte de tarefas é um plugin, como o esquema e a atribuição: o nome de um entry point do
grupo `monitor_versoes.tarefas` ou, só no `config.toml` central, um `modulo:Classe`. O núcleo
não traz fonte própria: sem `fonte`, a primeira busca de tarefas falha pedindo a chave (ou
`--task-source manual --lista <arquivo>`). Fora `fonte`, as chaves de `[tarefas]` são do
plugin, que as recebe como estão e as cobra na primeira busca. O plugin só é carregado
quando um comando busca tarefas ou precisa da referência: fonte inválida não impede
`atualizar --abort`, e `reconstruir-estado` roda sem fonte se houver `[referencia] padrao`.
O porquê: [027](docs/decisoes/027-fonte-de-tarefas-plugavel.md).

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
   $ motor --help
   usage: motor [-h] [--env {development,production}] comando ...
   ...
   ```

2. A instalação está íntegra — o diagnóstico checa variáveis, banco, migração, `PROJECTS_DIR`
   e credenciais, e sai com código 1 se alguma peça falhar:

   ```console
   $ motor diagnostico
   OK  Variáveis: todas preenchidas
   OK  SQLite: conexão funciona
   OK  Migração: revisão a7c3e9d1f2b4
   não configurado  PROJECTS_DIR: --repo aceita caminho absoluto
   OK  Tarefas: credenciais aceitas
   não configurado  Bitbucket: sem BITBUCKET_TOKEN
   ```

   Cada `FALHA` traz a correção na própria linha. Migração pendente se corrige com
   `motor migrar` (`motor --env development migrar` no desenvolvimento).

3. O repositório está cadastrado:

   ```console
   $ motor repo adicionar meu-repo
   repo 'meu-repo' adicionado
   ```

   `ERROR: repo 'meu-repo' ja cadastrado` também serve: o banco responde e o repo está lá.

## Uso

```bash
motor verificar 13.34.0 --repo meu-repo             # verde? tasks, faltantes
motor verificar 13.34.0 --repo meu-repo --auditar   # versão liberada, sem escrever
motor consulta  13.34.0 --repo meu-repo             # snapshot salvo, sem recalcular
motor criar     13.35.0 --repo meu-repo             # cria a branch e compõe
motor atualizar 13.35.0 --repo meu-repo             # aplica os commits faltantes
motor atualizar 13.35.0 --repo meu-repo --continue  # após resolver conflito
motor atualizar 13.35.0 --repo meu-repo --abort
motor reconstruir-estado 13.35.0 --repo meu-repo    # regenera o estado a partir do git
motor tui                                           # interface interativa
motor serve                                         # interface web local (ver Interface web)
motor inscricao adicionar 13.35.0 --repo meu-repo   # atualizar periodicamente (ver Inscrições)
```

Todos os comandos de versão aceitam `--repo` (path, ou nome dentro de `PROJECTS_DIR`),
`--debug`, `--sem-progresso`, `--task-source` e `--lista`. `motor <comando> -h` lista
o resto.

### Interface web

`motor serve` sobe um daemon local e abre o navegador na interface web. `--porta` muda a porta
(padrão **8765**) e o `--env` global vale como nos outros comandos. Ouve só em `127.0.0.1`.

As operações seguem rodando se a aba fechar. Um pick bloqueado por conflito se resolve na
worktree, no seu editor; depois, **Continuar**. O porquê em
[decisão 029](docs/decisoes/029-front-end-web-spa-com-dist-versionado.md).

### Fontes de tasks e de commits

- **Tasks:** a `[tarefas] fonte` da config por padrão. Sem ela, `--task-source manual --lista arquivo.txt` lê um
  id de task por linha (`#` comenta).
- **Commits:** com `BITBUCKET_TOKEN` e `BITBUCKET_EMAIL` (ou `--bitbucket-token` /
  `--bitbucket-email`), os commits de cada task vêm dos PRs do Bitbucket; o grep pela
  referência em `origin/<principal>` fica como fallback. Sem credenciais, só o grep.

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
motor inscricao adicionar 13.35.0 --repo meu-repo --intervalo 1h  # Nm ou Nh, padrão 30m
motor inscricao listar                                            # clone, intervalo, última execução
motor inscricao remover 13.35.0 --repo meu-repo
motor inscricao agendar                                           # instala o disparo a cada minuto
motor inscricao agendar --desfazer
motor inscricao rodar                                             # o que o agendador chama
```

A identidade é o caminho absoluto do clone mais a versão; reinscrever só troca o intervalo.
A inscrição guarda o diretório atual e o `--env`, que decidem qual `.env` a execução carrega.
Também dá para gerenciar na TUI (tecla `i`).

`rodar` executa as inscrições vencidas, uma por processo, e a falha de uma não impede as
outras. O desfecho da última execução aparece no `listar`:

| Desfecho | Significa |
| --- | --- |
| `aplicou` | commits aplicados e push feito |
| `nada` | nada a aplicar |
| `bloqueada` | conflito: checkpoint aberto, sem push |
| `pulada` | cherry-pick pendente na versão; nada roda até `atualizar --continue` ou `--abort` |
| `encerrada` | versão liberada; a inscrição é removida |
| `erro` | falha, com a mensagem; o processo que morre sem gravar resultado também vira `ERRO` |

`agendar` usa o `motor` do `PATH` no momento do comando (caminho absoluto) e instala, no Linux,
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
| `ERROR: banco inacessivel: connection failed: ... Suba com: docker compose up -d` | Só com `DATABASE_BACKEND=postgres`: o Postgres não está no ar. `docker compose up -d --wait`. No SQLite, confira `DATABASE_SQLITE_PATH` e as permissões do arquivo. |
| `ERROR: erro do banco: relation "repo" does not exist` | Banco no ar, mas sem migração (Postgres). `motor migrar`; no SQLite o primeiro uso migra sozinho. |
| `ERROR: repo 'meu-repo' desconhecido. Cadastre com: motor repo adicionar 'meu-repo'` | O repositório não foi cadastrado. Rode o comando sugerido. |
| `ERROR: faltando [tarefas] fonte em ...; ou use --task-source manual --lista <arquivo>` | Nenhuma fonte de tarefas na config. Defina `[tarefas] fonte` no `config.toml` central, ou use a lista manual. |
| `--repo nao encontrado: tentou 'meu-repo' e '(PROJECTS_DIR nao setada)'` | `--repo` não é um path existente e `PROJECTS_DIR` está vazia. Preencha `PROJECTS_DIR` no `.env` ou passe o path do repositório. |
| `--repo nao encontrado: tentou 'meu-repo' e '/home/voce/Projetos/meu-repo'` | O diretório não existe dentro de `PROJECTS_DIR`. Confira o nome e o valor da variável. |

## Próximos passos

- [docs/decisoes/](docs/decisoes/README.md) — o porquê de cada decisão do projeto.
- [CONTRIBUTING.md](CONTRIBUTING.md) — ambiente de desenvolvimento, verificações e fluxo de PR.
- Licença: [MIT](LICENSE).
