# Um VIRTUAL_ENV de outro projeto vazado no shell faz o uv usar o interpretador
# errado (ver "Armadilhas do ambiente" no CONTRIBUTING.md). Sem ele, `uv run`
# usa o .venv do projeto.
unexport VIRTUAL_ENV

# `python -m`, como o pre-commit e o CI sempre rodaram: a raiz entra no sys.path.
DEV := uv run --extra dev --extra anthropic python -m

.PHONY: install setup migracao check fmt fmt-check lint typecheck test web-check web-dist

# --- Usuário ---

install:
	uv sync

# --- Contribuidor ---

setup:
	uv sync --all-extras
	cp -n .env.development.example .env.development
	$(DEV) pre_commit install

# Gera uma revisão por autogenerate contra um SQLite temporário levado ao head.
migracao:
	@test -n "$(m)" || { echo 'uso: make migracao m="descrição"'; exit 1; }
	uv run python -c "from motor.migracoes import criar_revisao; import sys; criar_revisao(sys.argv[1])" "$(m)"

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

# -rs lista o motivo de cada skip no log.
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
