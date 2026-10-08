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
[docs/design.md](docs/design.md).

## Premissas

A ferramenta assume um fluxo de release específico — se o seu for diferente, ela não serve
sem adaptação:

- **Uma versão é uma branch** com o número dela; ao ser liberada, o HEAD recebe uma tag
  homônima, criada pelo processo de release (a ferramenta só lê).
- **Esquema de versão fixo:** `X.0.0` sai de `master`, `X.Y.0` da versão ajustada anterior,
  `X.Y.Z` de qualquer versão anterior.
- **Commits citam a task** na mensagem como `ch<num>`.
- **Build está fora:** a ferramenta monta e verifica, não constrói.

## Requisitos

- Python 3.14 e [uv](https://docs.astral.sh/uv/)
- git
- Docker (para o Postgres do estado)

## Instalação

```bash
uv sync --all-extras
cp .env.example .env
docker compose up -d
uv run alembic upgrade head
```

Preencha o `.env`: credenciais do Tickio, `PROJECTS_DIR` (raiz onde `--repo <nome>` é
procurado) e, opcionalmente, as do Bitbucket. Cada variável está comentada em
[.env.example](.env.example).

Cadastre cada repositório antes do primeiro comando nele:

```bash
uv run motor repo adicionar meu-repo --tickio-sistema-id 7
```

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

## Desenvolvimento

Tudo é **produção por padrão**: CLI, `compose.yml` e Alembic leem `.env`. O ambiente de
desenvolvimento (`.env.development`, porta 5434) é sempre explícito:

```bash
cp .env.development.example .env.development
docker compose --env-file .env.development up -d
set -a; . ./.env.development; set +a; uv run alembic upgrade head
uv run motor --env development verificar 13.34.0 --repo meu-repo
```

O `set -a` é o que redireciona o Alembic: o `load_dotenv()` dele não sobrescreve variável já
presente no ambiente.

### Testes e tipos

```bash
uv run pytest
uv run mypy
```

Os dois são o portão — não há CI. A suíte roda sem git, sem rede e sem banco de pé: os testes
marcados `integracao` sobem um Postgres efêmero via testcontainers, migram e o derrubam no
fim (~9s; sem Docker, pulam). A URL vem do container, nunca do ambiente, então o `TRUNCATE`
dos testes não alcança o banco do `.env`.

Armadilhas conhecidas do ambiente: [.claude/CLAUDE.md](.claude/CLAUDE.md).

## Licença

[MIT](LICENSE)
