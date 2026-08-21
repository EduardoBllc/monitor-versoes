# monitor-versoes

Monta e audita as branches de versão de release dos repos do VendaBem, cruzando o que o
Tickio marcou, o que o estado declarou e o que está de fato aplicado no git.

Desenho e as decisões por trás dele: [docs/design.md](docs/design.md).
Armadilhas deste ambiente de desenvolvimento: [.claude/CLAUDE.md](.claude/CLAUDE.md).

## Os dois ambientes, e o pé errado que dá para sair

O CLI usa **desenvolvimento por padrão**; produção é explícita. O `compose.yml` e o Alembic
fazem o **contrário**: ambos leem `.env`, ou seja, produção por padrão. Sair do pé errado é o
erro fácil aqui — o container sobe em produção e o CLI vai falar com um banco que não existe.

| | CLI | `docker compose` / Alembic |
| --- | --- | --- |
| padrão | desenvolvimento (`.env.development`, porta 5434) | **produção** (`.env`, porta 5433) |
| o outro | `--env production` | `--env-file .env.development` / sourcing (abaixo) |

## Setup

```bash
uv sync --all-extras
cp .env.example .env
cp .env.development.example .env.development
```

Banco de **desenvolvimento** — é o que o CLI e a suíte usam por padrão:

```bash
docker compose --env-file .env.development up -d
set -a; . ./.env.development; set +a; ./.venv/bin/python -m alembic upgrade head
```

O `set -a` é o que redireciona o Alembic: o `load_dotenv()` dele não sobrescreve variável já
presente no ambiente, então as do `.env.development` ganham.

Banco de **produção**:

```bash
docker compose up -d
./.venv/bin/python -m alembic upgrade head
```

Cadastre cada repo antes do primeiro comando nele, em cada ambiente:

```bash
uv run motor repo adicionar vendabemweb --tickio-sistema-id 7
uv run motor --env production repo adicionar vendabemweb --tickio-sistema-id 7
```

## Comandos

Todos aceitam `--repo` (path do repo, ou nome dentro de `PROJECTS_DIR`), `--debug`,
`--sem-progresso`, `--task-source tickio|manual` e `--lista`.

```bash
uv run motor verificar 13.34.0 --repo vendabemweb    # status: verde, tasks, faltantes
uv run motor verificar 13.34.0 --repo vendabemweb --auditar   # versão liberada, sem escrever
uv run motor consulta  13.34.0 --repo vendabemweb    # snapshot salvo, sem recalcular
uv run motor criar     13.35.0 --repo vendabemweb    # cria a branch e compõe
uv run motor atualizar 13.35.0 --repo vendabemweb    # aplica os commits faltantes
uv run motor atualizar 13.35.0 --repo vendabemweb --continue   # após resolver conflito
uv run motor atualizar 13.35.0 --repo vendabemweb --abort
uv run motor reconstruir-estado 13.35.0 --repo vendabemweb     # recuperação
uv run motor tui                                     # interface interativa
```

`uv run motor <comando> -h` lista as flags daquele comando. Em produção, `--env production` vem
antes do comando: `uv run motor --env production verificar …`.

A descoberta de commits por PR do Bitbucket é opcional: com `BITBUCKET_TOKEN` e
`BITBUCKET_EMAIL` no ambiente (ou `--bitbucket-token`/`--bitbucket-email`), ela entra como
fonte primária e o grep em `master` fica como fallback.

## Testes

```bash
./.venv/bin/python -m pytest
```

Roda sem git, sem rede e sem banco. Os testes marcados `integracao` exigem o Postgres de
desenvolvimento de pé — sem ele, pulam. Eles dão `TRUNCATE` nas tabelas, e a fixture **recusa
rodar** contra qualquer banco que não seja exatamente o do `.env.development`.
