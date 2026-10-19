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
| make | atalhos da instalação (opcional — veja "sem make") | Debian/Ubuntu: `sudo apt install make`; macOS: `xcode-select --install` |

É preciso clonar o repositório: as migrações do banco (`alembic/`) não vão no pacote, então
`uv tool install` não basta.

## Instalação

```bash
git clone https://github.com/EduardoBllc/monitor-versoes.git
cd monitor-versoes
make install && make db && make migrate
```

`make install` instala as dependências e cria o `.env` a partir do
[.env.example](.env.example) (sem sobrescrever um que já exista); `make db` sobe o Postgres
em Docker (porta 5433); `make migrate` cria as tabelas.

<details>
<summary>Sem make</summary>

```bash
unset VIRTUAL_ENV          # veja a ressalva em "Uso"
uv sync
cp -n .env.example .env
docker compose up -d
uv run alembic upgrade head
```

</details>

### Configurar o `.env`

Preencha no `.env`:

- `TICKIO_BASE_URL`, `TICKIO_USER`, `TICKIO_PASSWORD` — de onde vêm as tasks de cada versão.
  Dispensáveis se você só usar `--task-source manual`.
- `PROJECTS_DIR` — raiz onde `--repo <nome>` é procurado (com `PROJECTS_DIR=/home/voce/Projetos`,
  `--repo meu-repo` é `/home/voce/Projetos/meu-repo`; use path absoluto, `~` não é expandido). Sem ela, passe o path em `--repo`.
- `BITBUCKET_TOKEN`, `BITBUCKET_EMAIL` — opcionais; veja "Fontes de tasks e de commits".

As variáveis `DATABASE_*` já apontam para o Postgres do `make db`. Cada variável está
comentada no [.env.example](.env.example).

### Cadastrar os repositórios

Cada repositório é cadastrado uma vez, antes do primeiro comando nele, com o id do sistema
correspondente no Tickio:

```bash
uv run motor repo adicionar meu-repo --tickio-sistema-id 7
```

O nome é o do diretório do repositório (o basename do path de `--repo`).

## Verificar que funcionou

1. O CLI responde:

   ```console
   $ uv run motor --help
   usage: motor [-h] [--env {development,production}] comando ...
   ...
   ```

2. O banco está migrado — a linha termina em `(head)` (o hash muda conforme a versão):

   ```console
   $ uv run alembic current
   ...
   d4e7a9b2c1f0 (head)
   ```

   Saída vazia (só as linhas `INFO`) é banco no ar mas sem migração: rode `make migrate`.

3. O repositório está cadastrado:

   ```console
   $ uv run motor repo adicionar meu-repo --tickio-sistema-id 7
   repo 'meu-repo' adicionado
   ```

   `ERROR: repo 'meu-repo' ja cadastrado` também serve: o banco responde e o repo está lá.

## Uso

```bash
uv run motor verificar 13.34.0 --repo meu-repo             # verde? tasks, faltantes
uv run motor verificar 13.34.0 --repo meu-repo --auditar   # versão liberada, sem escrever
uv run motor consulta  13.34.0 --repo meu-repo             # snapshot salvo, sem recalcular
uv run motor criar     13.35.0 --repo meu-repo             # cria a branch e compõe
uv run motor atualizar 13.35.0 --repo meu-repo             # aplica os commits faltantes
uv run motor atualizar 13.35.0 --repo meu-repo --continue  # após resolver conflito
uv run motor atualizar 13.35.0 --repo meu-repo --abort
uv run motor reconstruir-estado 13.35.0 --repo meu-repo    # regenera o estado a partir do git
uv run motor tui                                           # interface interativa
```

> **Ressalva:** se o shell tiver um `VIRTUAL_ENV` ativo de outro projeto, o `uv run` pode usar
> o interpretador dele e o `motor` falha ao importar. Rode `unset VIRTUAL_ENV` (ou
> `deactivate`) antes; os alvos do `make` já fazem isso.

Todos os comandos de versão aceitam `--repo` (path, ou nome dentro de `PROJECTS_DIR`),
`--debug`, `--sem-progresso`, `--task-source` e `--lista`. `uv run motor <comando> -h` lista
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
| `ERROR: banco inacessivel: connection failed: ... Suba com: docker compose up -d` | O Postgres não está no ar. `make db` (ou `docker compose up -d`). Se acabou de subir, espere alguns segundos — o container leva um tempo até aceitar conexão. |
| `ERROR: erro do banco: relation "repo" does not exist` | Banco no ar, mas sem migração. `make migrate`. |
| `ERROR: repo 'meu-repo' desconhecido. Cadastre com: uv run motor repo adicionar 'meu-repo' --tickio-sistema-id <id>` | O repositório não foi cadastrado. Rode o comando sugerido com o id do sistema no Tickio. |
| `ERROR: faltando no .env: TICKIO_BASE_URL, TICKIO_USER, TICKIO_PASSWORD` | Credenciais do Tickio vazias no `.env`. Preencha, ou use `--task-source manual --lista arquivo.txt`. |
| `--repo nao encontrado: tentou 'meu-repo' e '(PROJECTS_DIR nao setada)'` | `--repo` não é um path existente e `PROJECTS_DIR` está vazia. Preencha `PROJECTS_DIR` no `.env` ou passe o path do repositório. |
| `--repo nao encontrado: tentou 'meu-repo' e '/home/voce/Projetos/meu-repo'` | O diretório não existe dentro de `PROJECTS_DIR`. Confira o nome e o valor da variável. |
| `uv run motor` falha na importação, com erro de sintaxe ou do Python errado | Um `VIRTUAL_ENV` de outro projeto ativo no shell. `unset VIRTUAL_ENV` (ou `deactivate`) e repita. |

## Próximos passos

- [docs/decisoes/](docs/decisoes/README.md) — o porquê de cada decisão do projeto.
- [CONTRIBUTING.md](CONTRIBUTING.md) — ambiente de desenvolvimento, verificações e fluxo de PR.
- Licença: [MIT](LICENSE).
