#!/bin/bash
# spawn-sessions.sh - Create tmux sessions for each worktree
#
# Usage: ./spawn-sessions.sh [ticket...]
#   If no tickets specified, spawns sessions for all worktrees

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-http://localhost:8765}"

# Note: direnv allow removed - was causing hangs

# Get tickets from args or find all worktrees
if [ $# -gt 0 ]; then
    TICKETS=("$@")
else
    TICKETS=($(ls -1 "${REPO_ROOT}/worktrees" 2>/dev/null || echo ""))
fi

if [ ${#TICKETS[@]} -eq 0 ]; then
    echo "No worktrees found in ${REPO_ROOT}/worktrees"
    exit 1
fi

echo "ParaPR Session Spawner"
echo "======================"
echo "Found ${#TICKETS[@]} worktrees: ${TICKETS[*]}"
echo "Orchestrator: ${ORCHESTRATOR_URL}"
echo ""

# Check if orchestrator is running (with 2s timeout)
if ! curl -s --connect-timeout 2 --max-time 2 "${ORCHESTRATOR_URL}/sessions" > /dev/null 2>&1; then
    echo "Warning: Orchestrator not responding at ${ORCHESTRATOR_URL}"
    echo "Start it with: cd ${SCRIPT_DIR} && python server.py"
    echo ""
fi

for ticket in "${TICKETS[@]}"; do
    WORKTREE_PATH="${REPO_ROOT}/worktrees/${ticket}/pipeline"

    if [ ! -d "${WORKTREE_PATH}" ]; then
        echo "Skipping ${ticket}: pipeline directory not found"
        continue
    fi

    # Check if session already exists
    if tmux has-session -t "${ticket}" 2>/dev/null; then
        echo "[${ticket}] Session already exists, skipping"
        continue
    fi

    echo "[${ticket}] Creating session..."

    # Run direnv allow in the worktree (in background to avoid hangs)
    (cd "${WORKTREE_PATH}" && direnv allow . 2>/dev/null) &
    wait $! 2>/dev/null || true

    # Create tmux session in the pipeline directory
    tmux new-session -d -s "${ticket}" -c "${WORKTREE_PATH}"

    # Set environment variable for the ticket ID
    tmux set-environment -t "${ticket}" TICKET_ID "${ticket}"
    tmux set-environment -t "${ticket}" ORCHESTRATOR_URL "${ORCHESTRATOR_URL}"

    # Update orchestrator (with timeout)
    curl -s --connect-timeout 2 --max-time 2 -X POST "${ORCHESTRATOR_URL}/session/${ticket}/state?state=starting" > /dev/null 2>&1 || true

    # Start Claude Code with the ticket context
    tmux send-keys -t "${ticket}" "claude" Enter

    echo "  Started: tmux attach -t ${ticket}"
done

echo ""
echo "All sessions started."
echo ""
echo "Commands:"
echo "  tmux attach -t <ticket>  - Connect to session"
echo "  tmux list-sessions       - List all sessions"
echo ""
echo "Dashboard: ${ORCHESTRATOR_URL}/sessions"
