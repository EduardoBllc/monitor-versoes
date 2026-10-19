# Contribuindo

Guia de quem mexe no código. Instalar e usar a ferramenta está no
[README.md](README.md); o porquê do sistema, em [docs/decisoes/](docs/decisoes/README.md);
como escrever código e teste, em [docs/padroes/codigo.md](docs/padroes/codigo.md) e
[docs/padroes/testes.md](docs/padroes/testes.md).

## Setup de desenvolvimento

Requisitos: Python 3.14, [uv](https://docs.astral.sh/uv/), git, Docker e `make`.

```bash
make setup         # uv sync --all-extras, cria .env.development, instala o pre-commit
make db-dev        # sobe o Postgres de desenvolvimento (porta 5434)
make migrate-dev   # alembic upgrade head contra o .env.development
```

Para rodar o CLI contra o banco de desenvolvimento, passe `--env development`:

```bash
./.venv/bin/motor --env development verificar 13.34.0 --repo meu-repo
```

## Produção é o padrão; desenvolvimento é explícito

CLI, `compose.yml` e Alembic leem `.env` — **produção**, porta 5433. O ambiente de
desenvolvimento (`.env.development`, porta **5434**) só entra quando pedido: alvos
`-dev` do Makefile e `--env development` no CLI.

A suíte de testes não usa nenhum dos dois. Os testes de integração sobem um Postgres
**efêmero** (testcontainers), migram e o derrubam no fim; a URL vem do container, nunca
do ambiente, então o `TRUNCATE` dos testes não alcança banco nenhum seu. Sem Docker,
esses testes pulam — e pulado não é verde. Detalhes em
[docs/padroes/testes.md](docs/padroes/testes.md#ambiente-e-integração).

O banco de desenvolvimento serve para usar o CLI à mão sem tocar produção.

## Verificações

```bash
make check   # ruff format --check, ruff check, mypy, pytest -rs
make fmt     # formata e aplica os fixes automáticos do ruff
```

`make check` roda os mesmos alvos, na mesma ordem, que o CI
([.github/workflows/ci.yml](.github/workflows/ci.yml)): verde aqui é verde lá. O `-rs`
do pytest lista o motivo de cada skip — confira se a integração rodou.

O `make setup` instala o [pre-commit](.pre-commit-config.yaml): ruff (format e check) e
mypy a cada commit. O pytest fica de fora do hook; rode `make check` antes de abrir o PR.

## Armadilhas do ambiente

| Sintoma | Causa e saída |
| --- | --- |
| `uv run pytest` morre na coleta com `SyntaxError: future feature annotations is not defined` | Um `VIRTUAL_ENV` de outro projeto (Python antigo) vazou para o shell e o `uv` o prefere ao `.venv`. Não é erro de código. Use `make` (ele faz `unexport VIRTUAL_ENV`), ou `unset VIRTUAL_ENV`, ou chame `./.venv/bin/python -m pytest` (idem `mypy`, `ruff`, `alembic`). Sem `.venv`: `unset VIRTUAL_ENV; uv sync --all-extras`. |
| `docker compose up -d` subiu, mas não é o banco de desenvolvimento | Sem `--env-file`, o compose lê `.env` (produção, porta 5433). Desenvolvimento é `make db-dev`, ou `docker compose --env-file .env.development up -d`. |
| `alembic upgrade head` migrou o banco errado | O `load_dotenv()` do Alembic não sobrescreve variável já presente no ambiente — e sem nada exportado lê `.env`. Use `make migrate-dev`, ou exporte antes: `set -a; . ./.env.development; set +a; ./.venv/bin/python -m alembic upgrade head`. |

## Fluxo

1. **Trabalho nasce na issue.** A spec vai no corpo da issue; o plano, em comentário
   nela.
2. **Branch e PR.** A `main` é protegida: toda mudança entra por PR, e o merge exige os
   checks `ruff format`, `ruff check`, `mypy` e `pytest` verdes — para todos, dono
   incluído.
3. **O PR descreve o que foi feito** — e o desvio do plano, quando houver — e fecha a
   issue com `Closes #N`. O [template](.github/pull_request_template.md) traz o
   checklist.
