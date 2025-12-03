.PHONY: help build up down logs shell test clean

help: ## Show this help message
	@echo "ParaPR - Parallel PR Orchestrator"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

build: ## Build Docker image
	docker-compose build

up: ## Start ParaPR server
	docker-compose up -d
	@echo ""
	@echo "ParaPR is starting..."
	@echo "Dashboard: http://localhost:8765"
	@echo ""
	@echo "View logs: make logs"

down: ## Stop ParaPR server
	docker-compose down

restart: down up ## Restart ParaPR server

logs: ## View logs (follow mode)
	docker-compose logs -f

logs-tail: ## View last 50 lines of logs
	docker-compose logs --tail=50

shell: ## Open shell in ParaPR container
	docker-compose exec parapr bash

ps: ## Show running containers
	docker-compose ps

test: ## Run tests (TODO: implement)
	@echo "Tests not yet implemented"

clean: ## Remove containers, volumes, and images
	docker-compose down -v --rmi all

# Development targets
dev: ## Run server locally (no Docker)
	poetry install
	poetry run python server.py

dev-install: ## Install dependencies locally
	poetry install

format: ## Format code with black
	poetry run black server.py

lint: ## Lint code with ruff
	poetry run ruff check server.py

# Docker development
docker-build-local: ## Build Docker image with local tag
	docker build -t parapr:local .

docker-run-local: ## Run Docker container locally (interactive)
	docker run -it --rm \
		-p 8765:8765 \
		-e AZ_OPENAI_API_BASE=${AZ_OPENAI_API_BASE} \
		-e AZ_OPENAI_API_KEY=${AZ_OPENAI_API_KEY} \
		parapr:local

health: ## Check server health
	@curl -s http://localhost:8765/sessions | jq . || echo "Server not responding"

.DEFAULT_GOAL := help

