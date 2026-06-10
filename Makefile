# hl-signals — common tasks. Run `make` or `make help` for the list.

# Load .env if present so docker compose and scripts share the same config.
ifneq (,$(wildcard .env))
include .env
export
endif

.DEFAULT_GOAL := help
.PHONY: help env up down restart logs ps psql load meta triggers triggers-loop retention collect live fetch spike spike-liq fmt check hooks precommit

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")

up: env ## Start Grafana + TimescaleDB (detached)
	docker compose up -d
	@echo "Grafana:    http://localhost:$${GRAFANA_PORT:-3000}  (admin / $${GRAFANA_ADMIN_PASSWORD:-admin})"
	@echo "TimescaleDB: localhost:$${POSTGRES_PORT:-5432}  db=$${POSTGRES_DB:-hlsignals}"

down: ## Stop the stack (keeps volumes)
	docker compose down

restart: ## Restart the stack
	docker compose restart

logs: ## Tail stack logs
	docker compose logs -f

ps: ## Show stack status
	docker compose ps

psql: ## Open a psql shell on TimescaleDB
	docker compose exec timescaledb psql -U $${POSTGRES_USER:-hl} -d $${POSTGRES_DB:-hlsignals}

load: ## Load collected data/live parquet into TimescaleDB
	uv run hl-load-db

meta: ## Refresh per-coin perp metadata (max leverage) into coin_meta
	uv run hl-load-meta

triggers: ## Poll real stop/TP (trigger) orders into trigger_orders (one sweep)
	uv run hl-poll-triggers

triggers-loop: ## Keep refreshing stop/TP orders (sweep, sleep 15m, repeat)
	uv run hl-poll-triggers --loop 900

retention: ## Apply TimescaleDB retention policies (rolling buffer) to a running DB
	docker compose exec -T timescaledb psql -U $${POSTGRES_USER:-hl} -d $${POSTGRES_DB:-hlsignals} \
		-f /docker-entrypoint-initdb.d/04_retention.sql

collect: ## Run the live WS collector (writes data/live/*.parquet)
	uv run hl-collect

live: ## Stream market data straight into TimescaleDB (hands-off live; Ctrl-C to stop)
	uv run hl-collect --sink db

fetch: ## Pull the fair-value panel from the public API
	uv run hl-fetch-fairvalue

spike: ## Run the fair-value predictiveness test
	uv run hl-spike-fairvalue

spike-liq: ## Run the OI-liquidation-proxy predictiveness test (needs collected data)
	uv run hl-spike-liquidations

fmt: ## Format Python with ruff
	uv run ruff format .

check: ## Lint Python with ruff
	uv run ruff check .

hooks: ## Install the pre-commit git hook (run once per clone)
	uv run pre-commit install

precommit: ## Run all pre-commit hooks against the whole repo
	uv run pre-commit run --all-files
