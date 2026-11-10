# Um VIRTUAL_ENV de outro projeto vazado no shell faz o uv usar o interpretador
# errado (ver "Armadilhas do ambiente" no CONTRIBUTING.md). Sem ele, `uv run`
# usa o .venv do projeto.
unexport VIRTUAL_ENV

# `python -m`, como o pre-commit e o CI sempre rodaram: a raiz entra no sys.path.
DEV := uv run --extra dev python -m

.PHONY: install db migrate setup db-dev migrate-dev migracao check fmt fmt-check lint typecheck test web-check web-dist

# --- Usuário: produção (.env, porta 5433) ---

install:
	uv sync
	cp -n motor/modelos/env.example .env

# Postgres opt-in (DATABASE_BACKEND=postgres): o padrao do motor e SQLite, sem Docker.
db:
	docker compose -f motor/modelos/compose.yml --project-directory . up -d --wait

# Exige DATABASE_BACKEND=postgres no .env; no SQLite o primeiro uso migra sozinho.
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
check: fmt-check lint typecheck test web-check web-dist

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

# --- Front (web/): o build vive versionado em motor/daemon/static ---

web-check:
	cd web && npm ci && npm run typecheck && npm run lint && npm test

# Regera OpenAPI, tipos e build num diretório temporário (ignorado pelo git) e
# compara com a árvore: passa logo após um rebuild e acusa build defasado num
# checkout limpo.
WEB_TMP := web/node_modules/.dist

web-dist:
	cd web && npm ci
	mkdir -p $(WEB_TMP)
	uv run python -m motor.daemon.openapi > $(WEB_TMP)/openapi.json
	web/node_modules/.bin/openapi-typescript $(WEB_TMP)/openapi.json -o $(WEB_TMP)/esquema.ts
	web/node_modules/.bin/vite build web --outDir $(abspath $(WEB_TMP))/static --emptyOutDir
	diff -u web/openapi.json $(WEB_TMP)/openapi.json
	diff -u web/src/api/esquema.ts $(WEB_TMP)/esquema.ts
	diff -r motor/daemon/static $(WEB_TMP)/static
