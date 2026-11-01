# monitor-versoes

Ferramenta CLI-first para montar e auditar branches de versão de release. Responde a uma
pergunta só: _"esta versão está com **todos** os commits que deveria?"_.

A dificuldade é que versões são montadas por cherry-pick, e cherry-pick troca o hash —
comparar hashes não responde nada. O `motor` cruza três fontes:

| Fonte | Representa |
| --- | --- |
| **rastreador de tasks** (Tickio, ou lista manual) | o que _deveria_ estar na versão |
| **estado** (Postgres) | o que a ferramenta _declarou_ ter colocado |
| **git** (trailer do `cherry-pick -x`) | o que está _de fato_ aplicado |

A versão só fica verde quando as três concordam. O porquê de cada decisão está em
[docs/decisoes/](docs/decisoes/README.md).

## Premissas

A ferramenta assume um fluxo de release específico — se o seu for diferente, ela não serve
sem adaptação:

- **Uma versão é uma branch** com o número dela; ao ser liberada, o HEAD recebe uma tag
  homônima, criada pelo processo de release (a ferramenta só lê).
- **Esquema de versão fixo:** `X.0.0` sai de `master`, `X.Y.0` da versão ajustada anterior,
  `X.Y.Z` de qualquer versão anterior.
- **Commits citam a task** na mensagem como `ch<num>`.
- **Build está fora:** a ferramenta monta e verifica, não constrói.

## Pré-requisitos

| Ferramenta | Para quê | Instalação |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | dependências e Python 3.14 (o `uv` baixa o Python se faltar) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| [Docker](https://docs.docker.com/engine/install/) com Compose | Postgres do estado | Linux: `curl -fsSL https://get.docker.com \| sh`; macOS: [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/) |
| git | os repositórios auditados | Debian/Ubuntu: `sudo apt install git`; macOS: `xcode-select --install` |

## Instalação

Em um diretório de trabalho qualquer (não precisa clonar o repositório):

```bash
uv tool install git+https://github.com/EduardoBllc/monitor-versoes
motor init                      # escreve compose.yml e .env no diretório atual
docker compose up -d --wait     # Postgres do estado (porta 5433)
motor migrar                    # cria as tabelas
```

Com plugins: `uv tool install git+https://github.com/EduardoBllc/monitor-versoes --with <plugin>`.

`motor init` não sobrescreve arquivo existente. Se preferir, copie os dois arquivos abaixo.

`compose.yml`:

<!-- modelo: compose.yml -->
```yaml
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
# Produção — o compose.yml lê estas mesmas variáveis
DATABASE_HOST=localhost
DATABASE_PORT=5433
DATABASE_NAME=monitor_versoes
DATABASE_USER=motor
DATABASE_PASSWORD=motor

# Tickio
TICKIO_BASE_URL=
TICKIO_USER=
TICKIO_PASSWORD=

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

- `TICKIO_BASE_URL`, `TICKIO_USER`, `TICKIO_PASSWORD` — de onde vêm as tasks de cada versão.
  Dispensáveis se você só usar `--task-source manual`.
- `PROJECTS_DIR` — raiz onde `--repo <nome>` é procurado (com `PROJECTS_DIR=/home/voce/Projetos`,
  `--repo meu-repo` é `/home/voce/Projetos/meu-repo`; use path absoluto, `~` não é expandido). Sem ela, passe o path em `--repo`.
- `BITBUCKET_TOKEN`, `BITBUCKET_EMAIL` — opcionais; veja "Fontes de tasks e de commits".

As variáveis `DATABASE_*` já apontam para o Postgres do `docker compose` acima. Cada variável
está comentada no `.env`.

### Cadastrar os repositórios

Cada repositório é cadastrado uma vez, antes do primeiro comando nele, com o id do sistema
correspondente no Tickio:

```bash
motor repo adicionar meu-repo --tickio-sistema-id 7
```

O nome é o do diretório do repositório (o basename do path de `--repo`).

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
   OK  Postgres: conexão funciona
   OK  Migração: revisão d4e7a9b2c1f0
   não configurado  PROJECTS_DIR: --repo aceita caminho absoluto
   OK  Tickio: autenticação aceita
   não configurado  Bitbucket: sem BITBUCKET_TOKEN
   ```

   Cada `FALHA` traz a correção na própria linha. Migração pendente se corrige com
   `motor migrar` (`motor --env development migrar` no desenvolvimento).

3. O repositório está cadastrado:

   ```console
   $ motor repo adicionar meu-repo --tickio-sistema-id 7
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
```

Todos os comandos de versão aceitam `--repo` (path, ou nome dentro de `PROJECTS_DIR`),
`--debug`, `--sem-progresso`, `--task-source` e `--lista`. `motor <comando> -h` lista
o resto.

### Fontes de tasks e de commits

- **Tasks:** Tickio por padrão. Sem ele, `--task-source manual --lista arquivo.txt` lê um
  número de task por linha (`#` comenta).
- **Commits:** com `BITBUCKET_TOKEN` e `BITBUCKET_EMAIL` (ou `--bitbucket-token` /
  `--bitbucket-email`), os commits de cada task vêm dos PRs do Bitbucket; o grep por
  `ch<num>` em `master` fica como fallback. Sem credenciais, só o grep.

### Worktrees mantidas em disco

Cada operação levanta a versão numa worktree em `<repo>-worktrees/`. `WORKTREES_MANTIDAS`
(default **3**) diz quantas ficam em disco para o próximo comando reusar em vez de refazer o
checkout; `0` descarta a cada run.

A eviction é por uso mais recente e nunca leva trabalho embora: worktree com alteração não
commitada ou cherry-pick pendente (um `atualizar` esperando `--continue`) é pulada.

## Problemas comuns

| Sintoma | Causa e saída |
| --- | --- |
| `ERROR: banco inacessivel: connection failed: ... Suba com: docker compose up -d` | O Postgres não está no ar. `docker compose up -d --wait`. |
| `ERROR: erro do banco: relation "repo" does not exist` | Banco no ar, mas sem migração. `motor migrar`. |
| `ERROR: repo 'meu-repo' desconhecido. Cadastre com: motor repo adicionar 'meu-repo' --tickio-sistema-id <id>` | O repositório não foi cadastrado. Rode o comando sugerido com o id do sistema no Tickio. |
| `ERROR: faltando no .env: TICKIO_BASE_URL, TICKIO_USER, TICKIO_PASSWORD` | Credenciais do Tickio vazias no `.env`. Preencha, ou use `--task-source manual --lista arquivo.txt`. |
| `--repo nao encontrado: tentou 'meu-repo' e '(PROJECTS_DIR nao setada)'` | `--repo` não é um path existente e `PROJECTS_DIR` está vazia. Preencha `PROJECTS_DIR` no `.env` ou passe o path do repositório. |
| `--repo nao encontrado: tentou 'meu-repo' e '/home/voce/Projetos/meu-repo'` | O diretório não existe dentro de `PROJECTS_DIR`. Confira o nome e o valor da variável. |

## Próximos passos

- [docs/decisoes/](docs/decisoes/README.md) — o porquê de cada decisão do projeto.
- [CONTRIBUTING.md](CONTRIBUTING.md) — ambiente de desenvolvimento, verificações e fluxo de PR.
- Licença: [MIT](LICENSE).
