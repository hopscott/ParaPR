# ParaPR - Parallel PR Orchestrator

🚀 AI-powered orchestration for managing multiple Claude Code sessions working on parallel PRs in git worktrees.

Built by [Hopscott](https://hopscott.com)

## What is ParaPR?

ParaPR is a web-based orchestration tool that manages multiple Claude Code sessions running in parallel across git worktrees. It provides a beautiful dashboard to monitor, control, and automate AI coding assistants working on multiple PRs simultaneously.

## Key Features

- 🎯 **Web Dashboard** - Beautiful UI for monitoring all Claude Code sessions with real-time streaming
- 🤖 **AI Safety Checks** - GPT-4o analyzes prompts to auto-accept safe operations
- ⚡ **Auto-Accept Mode** - Let AI handle routine permission prompts while flagging important decisions
- 📊 **Batch Operations** - Run commands across all sessions simultaneously
- 🎛️ **Session Control** - Send input, interrupt, toggle modes, and track workflow progress
- 🔄 **Workflow Tracking** - Visual progress: Linear → Spec → Plan → Implement

## Quick Start

### Docker (Recommended)

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/parapr.git
cd parapr

# 2. Start with Docker Compose
make up

# 3. Open dashboard
open http://localhost:8765
```

### Local Development

```bash
# 1. Install dependencies
poetry install

# 2. Start the server
python -m src.server

# 3. Open dashboard
open http://localhost:8765
```

## Architecture

```
┌─────────────────────────────────────────┐
│   Web Dashboard (Browser)               │
│   http://localhost:8765                 │
└─────────────────┬───────────────────────┘
                  │ WebSocket
┌─────────────────▼───────────────────────┐
│   FastAPI Server + Azure OpenAI         │
│   - Session management                  │
│   - AI safety checks (GPT-4o)          │
│   - WebSocket streaming                 │
│   - Batch operations                    │
└─────────────────┬───────────────────────┘
                  │ tmux control
    ┌─────────────┼─────────────┐
    ▼             ▼             ▼
┌────────┐   ┌────────┐   ┌────────┐
│ tmux:  │   │ tmux:  │   │ tmux:  │
│TE-1902 │   │TE-1903 │   │TE-1904 │
│ claude │   │ claude │   │ claude │
└────────┘   └────────┘   └────────┘
     │            │            │
     ▼            ▼            ▼
worktrees/  worktrees/  worktrees/
 te-1902     te-1903     te-1904
```

## Usage

### Setup Git Worktrees

First, set up your git worktrees for parallel development:

```bash
# Run the worktree setup script
./scripts/worktree-setup.sh

# This will create separate worktrees for each issue/PR
```

### Web Dashboard (Recommended)

1. Open `http://localhost:8765` in your browser
2. Click "Start All" to spawn Claude Code sessions for all worktrees
3. Click any session in the sidebar to open its panel
4. Toggle between "Planning" and "Auto" modes per session
5. Use quick actions: Send, yes, no, continue, ^C
6. Use batch actions dropdown to run commands across all sessions

### CLI Tools

```bash
# Spawn sessions for all worktrees
./scripts/spawn-sessions.sh

# Connect to a specific session
tmux attach -t te-1902

# List all sessions
tmux list-sessions

# Kill a session
tmux kill-session -t te-1902
```

## Session States

| State | Description |
|-------|-------------|
| `starting` | Session created, Claude starting |
| `specify` | Running /specify to create spec |
| `clarify_needed` | **Needs attention** - spec unclear |
| `planning` | Running /plan |
| `plan_review` | **Needs attention** - plan ready for review |
| `tasking` | Running /tasks |
| `implementing` | Running /implement |
| `done` | Work complete |
| `error` | **Needs attention** - something went wrong |

## AI Safety Checks

ParaPR uses GPT-4o (via Azure OpenAI) to analyze permission prompts and determine if they can be safely auto-accepted:

### Auto-Accepts (When in Auto Mode)
- ✅ File read operations
- ✅ Code search (grep, find)
- ✅ Running tests, linters
- ✅ Creating/editing source code
- ✅ Normal git operations
- ✅ Package installations

### Requires Human Attention
- ⚠️ Design decisions
- ⚠️ Multiple implementation options
- ⚠️ Business logic questions
- ⚠️ Clarification requests

### Blocked (Dangerous)
- 🛑 DELETE operations (rm -rf)
- 🛑 Database drops
- 🛑 Git force operations
- 🛑 Production/secrets access

## Configuration

### Environment Variables (Optional)

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Then edit `.env` with your credentials:

```bash
# Azure OpenAI (optional - falls back to pattern matching if not provided)
AZ_OPENAI_API_BASE=https://your-endpoint.openai.azure.com/
AZ_OPENAI_API_KEY=your-api-key
AZ_OPENAI_API_VERSION=2024-02-15-preview

# Linear (for ticket integration)
LINEAR_API_KEY=your-linear-api-key

# Orchestrator settings (defaults shown)
ORCHESTRATOR_URL=http://localhost:8765
WORKTREES_DIR=/path/to/your/worktrees
```

**Note:** Azure OpenAI credentials are optional. If not provided, ParaPR falls back to basic pattern matching for safety checks.

## Docker Commands

```bash
make help          # Show all available commands
make build         # Build Docker image
make up            # Start ParaPR (detached)
make down          # Stop ParaPR
make logs          # View logs (live)
make restart       # Restart server
make shell         # Open shell in container
make health        # Check server health
```

## Project Structure

```
parapr/
├── src/
│   └── server.py          # FastAPI server with AI safety checks
├── scripts/
│   ├── worktree-setup.sh  # Set up git worktrees
│   └── spawn-sessions.sh  # Create tmux sessions
├── pyproject.toml         # Poetry dependencies
├── poetry.lock            # Locked dependencies
├── Dockerfile             # Docker image definition
├── docker-compose.yml     # Docker Compose setup
├── Makefile               # Convenient commands
└── README.md              # This file
```

## Development

### Local Development

```bash
# Install dependencies
poetry install

# Run server
python -m src.server

# Run with auto-reload
uvicorn src.server:app --reload --port 8765
```

### Docker Development

```bash
# Build local image
make build

# Run in foreground
docker-compose up

# View logs
make logs
```

## API Endpoints

- `GET /` - Web dashboard UI
- `GET /sessions` - List all sessions (JSON)
- `GET /worktrees` - List available worktrees (JSON)
- `POST /sessions/{session_id}/command` - Send command to session
- `POST /sessions/{session_id}/interrupt` - Send Ctrl+C to session
- `POST /sessions/{session_id}/toggle-auto` - Toggle auto-accept mode
- `POST /batch/command` - Run command across all sessions
- `WS /ws/{session_id}` - WebSocket for real-time output streaming
- `GET /health` - Health check

## Troubleshooting

### Port 8765 already in use

```bash
# Find process using port 8765
lsof -i :8765

# Kill the process
kill -9 <PID>
```

### Tmux sessions not appearing

- Ensure worktrees directory exists and contains valid git worktrees
- Check tmux is installed: `which tmux`
- Verify sessions manually: `tmux list-sessions`

### Azure OpenAI not working

- Verify credentials in `.env` file
- Check API endpoint is accessible
- Review logs: `make logs`
- Falls back to pattern matching if Azure OpenAI unavailable

## Use Cases

- **Parallel Development** - Work on multiple features/fixes simultaneously using git worktrees
- **Linear Integration** - Automatically pull Linear tickets and coordinate work across issues
- **Team Coordination** - Monitor multiple team members' Claude sessions from one dashboard
- **Autonomous Operations** - Enable auto-accept mode for repetitive tasks while maintaining safety

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT License - see [LICENSE](LICENSE) file for details.

Copyright (c) 2024 Hopscott

## Links

- GitHub: https://github.com/yourusername/parapr
- Issues: https://github.com/yourusername/parapr/issues
- Hopscott: https://hopscott.com
