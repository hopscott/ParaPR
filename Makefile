.PHONY: run re stop install help

run: ## Start ParaPR server with hot reload
	@echo "🚀 Starting ParaPR server..."
	@poetry run uvicorn src.server:app --host 0.0.0.0 --port 8765 --reload

re: stop run ## Restart server

stop: ## Stop ParaPR server
	@echo "⏹️  Stopping ParaPR server..."
	@pkill -f "uvicorn src.server:app" || echo "No server running"

install: ## Install dependencies and setup environment
	@echo "🔧 Setting up ParaPR..."
	@echo ""
	@echo "📦 Installing dependencies..."
	@poetry install
	@echo ""
	@echo "📝 Setting up environment..."
	@if [ ! -f .env ]; then \
		cp .env.example .env 2>/dev/null || true; \
		echo "✅ Created .env from .env.example"; \
	else \
		echo "✅ .env already exists"; \
	fi
	@echo ""
	@echo "🔐 Configuring direnv..."
	@if command -v direnv >/dev/null 2>&1; then \
		direnv allow .; \
		echo "✅ direnv allowed - venv will auto-activate"; \
	else \
		echo "⚠️  direnv not installed (optional)"; \
		echo "   Install with: brew install direnv"; \
	fi
	@echo ""
	@echo "✨ Setup complete! Run 'make run' to start the server."

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
