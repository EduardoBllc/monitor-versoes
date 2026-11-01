# Um VIRTUAL_ENV de outro projeto vazado no shell faz o uv usar o interpretador
# errado (ver "Armadilhas do ambiente" no CONTRIBUTING.md). Sem ele, `uv run`
# usa o .venv do projeto.
unexport VIRTUAL_ENV

# `python -m`, como o pre-commit e o CI sempre rodaram: a raiz entra no sys.path.
DEV := uv run --extra dev python -m

.PHONY: install db migrate setup db-dev migrate-dev migracao check fmt fmt-check lint typecheck test

# --- Usuário: produção (.env, porta 5433) ---

install:
	uv sync
	uv run motor init

db:
	docker compose -f motor/modelos/compose.yml --project-directory . up -d --wait

migrate:
	uv run motor migrar

# --- Contribuidor: desenvolvimento (.env.development, porta 5434) ---

setup:
	uv sync --all-extras
	cp -n .env.development.example .env.development
	$(DEV) pre_commit install

db-dev:
	docker compose -f motor/modelos/compose.yml --project-directory . --env-file .env.development up -d --wait

migrate-dev:
	uv run motor --env development migrar

# Gera uma revisão por autogenerate contra o banco de desenvolvimento (já
# migrado). O env.py não carrega .env: set -a exporta as variáveis do arquivo.
migracao:
	@test -n "$(m)" || { echo 'uso: make migracao m="descrição"'; exit 1; }
	set -a; . ./.env.development; set +a; uv run python -c "from motor.migracoes import criar_revisao; import sys; criar_revisao(sys.argv[1])" "$(m)"

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
