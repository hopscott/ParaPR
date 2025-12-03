FROM python:3.11-slim

# Install tmux for session management
RUN apt-get update && \
    apt-get install -y tmux curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install poetry for dependency management using official installer
RUN curl -sSL https://install.python-poetry.org | python3 - && \
    ln -s /root/.local/bin/poetry /usr/local/bin/poetry

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Install dependencies (no dev dependencies, no root package as it's package-mode: false)
RUN poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --no-root

# Copy application code
COPY server.py .
COPY scripts/spawn-sessions.sh ./

# Make scripts executable
RUN chmod +x spawn-sessions.sh

# Expose port
EXPOSE 8765

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8765/sessions || exit 1

# Run the server
CMD ["python", "server.py"]

