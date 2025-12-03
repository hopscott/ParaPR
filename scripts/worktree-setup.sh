#!/bin/bash
# worktree-setup.sh - Create and configure git worktrees for development
#
# Usage: ./scripts/worktree-setup.sh <ticket-id> [base-branch] [--env local|beta]
# Examples:
#   ./scripts/worktree-setup.sh te-1899 beta           # Interactive - prompts for env
#   ./scripts/worktree-setup.sh te-1899 beta --env beta  # Non-interactive
#
# This script:
# 1. Creates a git worktree at worktrees/<ticket-id>/
# 2. Prompts for environment (local/beta) unless --env is specified
# 3. Copies appropriate .env files from main repo
# 4. Runs pnpm install at root and webapp
# 5. Runs poetry install and direnv allow for pipeline

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
TICKET_ID="${1:?Usage: $0 <ticket-id> [base-branch] [--env local|beta]}"
BASE_BRANCH="${2:-beta}"
ENV_FLAG=""
ENV_VALUE=""

# Check for --env flag
if [[ "$3" == "--env" ]]; then
    ENV_FLAG="$3"
    ENV_VALUE="${4:-beta}"
fi

# Normalize ticket ID to lowercase
TICKET_ID=$(echo "${TICKET_ID}" | tr '[:upper:]' '[:lower:]')

# Determine paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MAIN_REPO="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKTREE_DIR="${MAIN_REPO}/worktrees/${TICKET_ID}"

echo -e "${GREEN}=== Worktree Setup ===${NC}"
echo "Ticket ID:    ${TICKET_ID}"
echo "Base branch:  ${BASE_BRANCH}"
echo "Worktree dir: ${WORKTREE_DIR}"
echo ""

# Check if worktree already exists
if [ -d "${WORKTREE_DIR}" ]; then
    echo -e "${RED}Error: Worktree already exists at ${WORKTREE_DIR}${NC}"
    echo "To remove it: git worktree remove worktrees/${TICKET_ID}"
    exit 1
fi

# 1. Create worktree
echo -e "${YELLOW}Creating worktree...${NC}"
cd "${MAIN_REPO}"
git worktree add "${WORKTREE_DIR}" -b "feature/${TICKET_ID}" "${BASE_BRANCH}"
echo -e "${GREEN}Created worktree at ${WORKTREE_DIR}${NC}"

cd "${WORKTREE_DIR}"

# 2. Select environment (from --env flag or interactive prompt)
if [[ -n "${ENV_FLAG}" ]]; then
    # Non-interactive: use --env value
    case "${ENV_VALUE}" in
        local)
            ENV_TYPE="local"
            ;;
        beta|*)
            ENV_TYPE="beta"
            ;;
    esac
    echo -e "Using ${GREEN}${ENV_TYPE}${NC} environment (from --env flag)"
else
    # Interactive: prompt user
    echo ""
    echo "Select environment for .env files:"
    echo "  1) local - Uses docker-compose local DBs"
    echo "  2) beta  - Connects to beta environment"
    read -p "Choice [1/2] (default: 2): " ENV_CHOICE

    case "${ENV_CHOICE}" in
        1|local)
            ENV_TYPE="local"
            ;;
        2|beta|"")
            ENV_TYPE="beta"
            ;;
        *)
            ENV_TYPE="beta"
            ;;
    esac
    echo -e "Using ${GREEN}${ENV_TYPE}${NC} environment"
fi

# 3. Root setup (pnpm for husky)
echo ""
echo -e "${YELLOW}Setting up root (pnpm install for husky)...${NC}"
pnpm install
echo -e "${GREEN}Root setup complete${NC}"

# 4. Webapp setup
echo ""
echo -e "${YELLOW}Setting up webapp...${NC}"
cd webapp

if [ "${ENV_TYPE}" = "beta" ] && [ -f "${MAIN_REPO}/webapp/.env.beta" ]; then
    cp "${MAIN_REPO}/webapp/.env.beta" .env
    echo "  Copied .env.beta -> .env"
elif [ -f "${MAIN_REPO}/webapp/.env" ]; then
    cp "${MAIN_REPO}/webapp/.env" .env
    echo "  Copied main .env"
else
    cp .env.example .env
    echo -e "  ${YELLOW}Created .env from .env.example (needs manual config)${NC}"
fi

pnpm install
echo -e "${GREEN}Webapp setup complete${NC}"
cd ..

# 5. Pipeline setup
echo ""
echo -e "${YELLOW}Setting up pipeline...${NC}"
cd pipeline

if [ -f "${MAIN_REPO}/pipeline/.env" ]; then
    cp "${MAIN_REPO}/pipeline/.env" .env
    echo "  Copied main .env"
else
    cp .env.example .env
    echo -e "  ${YELLOW}Created .env from .env.example (needs manual config)${NC}"
fi

# Allow direnv (this will also activate the venv)
direnv allow 2>/dev/null || echo "  Note: direnv not installed or not configured"

# Install dependencies
poetry install
echo -e "${GREEN}Pipeline setup complete${NC}"
cd ..

# 6. Done
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}Worktree ready!${NC}"
echo ""
echo "To start working on pipeline:"
echo -e "  ${YELLOW}cd ${WORKTREE_DIR}/pipeline${NC}"
echo ""
echo "To start working on webapp:"
echo -e "  ${YELLOW}cd ${WORKTREE_DIR}/webapp${NC}"
echo ""
echo "To remove this worktree later:"
echo -e "  ${YELLOW}git worktree remove worktrees/${TICKET_ID}${NC}"
echo -e "${GREEN}============================================${NC}"
