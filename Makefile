.PHONY: run re stop install help

run: ## Start ParaPR server with hot reload
	@echo "🚀 Starting ParaPR server..."
	@poetry run uvicorn server:app --host 0.0.0.0 --port 8765 --reload

re: stop run ## Restart server

stop: ## Stop ParaPR server
	@echo "⏹️  Stopping ParaPR server..."
	@pkill -f "uvicorn server:app" || echo "No server running"

install: ## Install dependencies
	@echo "📦 Installing dependencies..."
	@poetry install

help: ## Show this help
	@echo "╔════════════════════════════════════════╗"
	@echo "║  ParaPR - Parallel PR Orchestrator    ║"
	@echo "╚════════════════════════════════════════╝"
	@echo ""
	@echo "Commands:"
	@echo "  make run      - Start server with hot reload"
	@echo "  make re       - Restart server"
	@echo "  make stop     - Stop server"
	@echo "  make install  - Install dependencies"
	@echo ""
	@echo "Dashboard: http://localhost:8765"

.DEFAULT_GOAL := help
