# Um VIRTUAL_ENV de outro projeto vazado no shell faz o uv usar o interpretador
# errado (ver .claude/AGENTS.md). Sem ele, `uv run` usa o .venv do projeto.
unexport VIRTUAL_ENV

# `python -m`, como o pre-commit e o CI sempre rodaram: a raiz entra no sys.path.
DEV := uv run --extra dev python -m

.PHONY: install db migrate setup db-dev migrate-dev check fmt fmt-check lint typecheck test

# --- Usuário: produção (.env, porta 5433) ---

install:
	uv sync
	cp -n .env.example .env

db:
	docker compose up -d

migrate:
	uv run alembic upgrade head

# --- Contribuidor: desenvolvimento (.env.development, porta 5434) ---

setup:
	uv sync --all-extras
	cp -n .env.development.example .env.development
	$(DEV) pre_commit install

db-dev:
	docker compose --env-file .env.development up -d

# set -a exporta as variáveis do arquivo: o load_dotenv() do Alembic não
# sobrescreve variável já presente, então o .env de produção não entra.
migrate-dev:
	set -a; . ./.env.development; set +a; uv run alembic upgrade head

# Mesma sequência das etapas do CI (.github/workflows/ci.yml chama estes alvos).
check: fmt-check lint typecheck test

fmt:
	$(DEV) ruff format .
	$(DEV) ruff check --fix .

fmt-check:
	$(DEV) ruff format --check .

lint:
	$(DEV) ruff check .

typecheck:
	$(DEV) mypy

# -rs lista o motivo de cada skip: integração pulada aparece no log.
test:
	$(DEV) pytest -rs
