#!/usr/bin/env python3
"""ParaPR - Parallel PR Orchestrator with AI-powered session management."""

import asyncio
import json
import os
import re
import subprocess
import time
from datetime import datetime
from enum import Enum
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from openai import AsyncAzureOpenAI
from pydantic import BaseModel
import uvicorn


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize on server start."""
    init_llm_client()
    # Discover existing tmux sessions (any worktree directory name)
    result = subprocess.run(["tmux", "list-sessions", "-F", "#{session_name}"], capture_output=True, text=True)
    if result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            ticket = line.strip()
            if ticket and ticket not in sessions:
                sessions[ticket] = SessionStatus(ticket=ticket)
                output_buffers[ticket] = []
    yield


app = FastAPI(title="ParaPR - Parallel PR Orchestrator", lifespan=lifespan)

# Get repo root (two levels up from scripts/ParaPR)
REPO_ROOT = Path(__file__).parent.parent.parent
WORKTREES_DIR = REPO_ROOT / "worktrees"


class SessionState(str, Enum):
    STARTING = "starting"
    SPECIFY = "specify"
    CLARIFY_NEEDED = "clarify_needed"
    PLANNING = "planning"
    PLAN_REVIEW = "plan_review"
    TASKING = "tasking"
    IMPLEMENTING = "implementing"
    DONE = "done"
    ERROR = "error"


class ClaudeMode(str, Enum):
    PLANNING = "planning"
    AUTO_ACCEPT = "auto_accept"


class SessionStatus(BaseModel):
    ticket: str
    state: SessionState = SessionState.STARTING
    message: str | None = None
    updated_at: datetime = datetime.now()
    linear_pulled: bool = False
    specify_done: bool = False
    clarify_done: bool = False
    plan_done: bool = False
    tasks_done: bool = False
    implement_done: bool = False
    auto_accept: bool = False
    needs_attention: bool = False
    linear_title: str = ""
    linear_description: str = ""
    in_grid: bool = False  # Whether session is shown in grid view
    claude_mode: ClaudeMode = ClaudeMode.PLANNING  # Current Claude Code mode


class SafetyCheckResponse(BaseModel):
    needs_clarification: bool
    safe_to_continue: bool
    reason: str


class SendInput(BaseModel):
    text: str


# In-memory session storage
sessions: dict[str, SessionStatus] = {}

# WebSocket connections per session
ws_connections: dict[str, list[WebSocket]] = {}

# Output buffer per session (last N lines)
output_buffers: dict[str, list[str]] = {}
MAX_BUFFER_LINES = 200

# Azure OpenAI client for safety checks (uses GPT-4o)
llm_client: AsyncAzureOpenAI | None = None

SAFETY_CHECK_PROMPT = """You are a safety monitor for Claude Code sessions running in parallel.
Your job is to determine if a permission prompt can be auto-accepted or needs human attention.

## NEEDS_CLARIFICATION = True (REQUIRES HUMAN)
- Design decisions or architectural choices ("which approach", "how should we")
- Multiple implementation options presented for selection
- Requirements clarification needed
- Questions about business logic or domain knowledge
- "Type here to tell Claude" option is shown
- Any open-ended question requiring human judgment

## NEEDS_CLARIFICATION = False (CAN AUTO-ACCEPT)
- Simple Yes/No permission to run a command
- Permission to read files (cat, head, tail, read)
- Permission to search code (grep, glob, find)
- Permission to run linearis/linear commands
- Permission to run tests, linters, type checks
- Permission to create/edit source code files
- Permission to run git status, diff, log, branch

## SAFE_TO_CONTINUE = False (DANGEROUS - BLOCK)
- DELETE operations: rm, rm -rf, unlink, rmdir
- Database drops: DROP TABLE, DROP DATABASE, TRUNCATE
- Git force operations: push --force, push -f, reset --hard
- Production/secrets: .env files, credentials, API keys
- System files: /etc, /usr, ~/.ssh, ~/.config

## SAFE_TO_CONTINUE = True (SAFE)
- All read operations
- All search operations
- Creating new files
- Editing existing code
- Running tests
- Normal git operations (commit, push, pull, branch)
- Package install (npm install, pip install)

Return JSON: {"needs_clarification": bool, "safe_to_continue": bool, "reason": "brief explanation"}"""


def init_llm_client():
    """Initialize Azure OpenAI client if credentials available."""
    global llm_client
    api_base = os.getenv("AZ_OPENAI_API_BASE")
    api_key = os.getenv("AZ_OPENAI_API_KEY")
    api_version = os.getenv("RMTQ_BETA_CMD_AZ_OPENAI_API_VERSION", "2024-02-15-preview")
    if api_base and api_key:
        llm_client = AsyncAzureOpenAI(
            azure_endpoint=api_base,
            api_key=api_key,
            api_version=api_version
        )
        print(f"[ParaPR] LLM client initialized with Azure OpenAI: {api_base}")


def get_worktrees() -> dict[str, dict]:
    """Discover worktrees and their status."""
    worktrees = {}
    if not WORKTREES_DIR.exists():
        return worktrees

    for path in WORKTREES_DIR.iterdir():
        if path.is_dir():
            ticket = path.name
            # Check if tmux session exists
            result = subprocess.run(
                ["tmux", "has-session", "-t", ticket],
                capture_output=True
            )
            has_session = result.returncode == 0
            worktrees[ticket] = {
                "path": str(path),
                "active": has_session,
                "in_sessions": ticket in sessions
            }
    return worktrees


def start_session(tickets: list[str]) -> dict:
    """Start Claude Code sessions using spawn-sessions.sh."""
    script_path = Path(__file__).parent / "spawn-sessions.sh"

    if not script_path.exists():
        return {"ok": False, "error": "spawn-sessions.sh not found"}

    # Call the shell script with the ticket arguments
    result = subprocess.run(
        [str(script_path)] + tickets,
        capture_output=True,
        text=True,
        cwd=str(script_path.parent)
    )

    # Initialize session state for each ticket
    for ticket in tickets:
        if ticket not in sessions:
            sessions[ticket] = SessionStatus(ticket=ticket)
            output_buffers[ticket] = []

    return {
        "ok": result.returncode == 0,
        "tickets": tickets,
        "output": result.stdout,
        "error": result.stderr if result.returncode != 0 else None
    }


async def check_safety(ticket: str, output: str) -> SafetyCheckResponse:
    """Use GPT-5.1 to analyze if output needs attention."""
    if not llm_client:
        # Fallback to simple pattern matching
        needs_clarification = "?" in output or "would you like" in output.lower()
        dangerous = any(p in output.lower() for p in ["delete", "rm -rf", "force push", "drop table"])
        return SafetyCheckResponse(
            needs_clarification=needs_clarification,
            safe_to_continue=not dangerous,
            reason="Pattern match (no LLM configured)"
        )

    try:
        context = "\n".join(output_buffers.get(ticket, [])[-50:])
        response = await llm_client.chat.completions.create(
            model="gpt-4o",  # GPT-4o via Azure OpenAI
            messages=[
                {"role": "system", "content": SAFETY_CHECK_PROMPT},
                {"role": "user", "content": f"Session: {ticket}\nContext:\n{context}\n\nLatest output:\n{output}"}
            ],
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content or "{}")
        print(f"[ParaPR] Safety check for {ticket}: {result}")
        return SafetyCheckResponse(**result)
    except Exception as e:
        print(f"[ParaPR] Safety check error: {e}")
        # Fallback to pattern matching on error
        needs_clarification = "?" in output or "would you like" in output.lower()
        return SafetyCheckResponse(
            needs_clarification=needs_clarification,
            safe_to_continue=True,
            reason=f"Safety check failed: {e}"
        )


# Regex patterns for permission prompts (auto-acceptable)
PERMISSION_PATTERNS = [
    r"Do you want to proceed\?",
    r"❯\s*1\.\s*Yes",
    r"Yes, and don't ask again",
    r"Allow this action\?",
    r"Proceed with this",
    r"\[Y/n\]",
    r"\(y/N\)",
    r"Press Enter to continue",
]

# Patterns that indicate human decision is needed
HUMAN_NEEDED_PATTERNS = [
    r"Type here to tell Claude",
    r"3\.\s*Type here",  # Option 3 in Claude prompts
    r"which (?:approach|option|method|one)",
    r"(?:choose|select|pick) (?:one|between|from)",
    r"What should",
    r"How would you like",
    r"Do you want me to",
    r"Should I",
    r"multiple (?:options|approaches|ways)",
]


def is_permission_prompt(output: str) -> bool:
    """Detect if Claude is showing a Yes/No permission prompt."""
    return any(re.search(p, output) for p in PERMISSION_PATTERNS)


def needs_human_decision(output: str) -> bool:
    """Detect if human input is actually needed (not just permission)."""
    return any(re.search(p, output, re.IGNORECASE) for p in HUMAN_NEEDED_PATTERNS)


async def auto_accept_if_safe(ticket: str, output: str) -> bool:
    """Auto-accept permission prompts if session has auto_accept enabled and it's safe.

    Flow:
    1. Check if auto_accept is enabled for this session
    2. Check if this looks like a permission prompt (Yes/No question)
    3. Check if human decision is actually needed (clarification, design choices)
    4. Call Azure OpenAI to verify safety (no destructive operations)
    5. If safe, send "1" to select "Yes" option
    """
    if ticket not in sessions or not sessions[ticket].auto_accept:
        return False

    if not is_permission_prompt(output):
        return False

    # If human decision patterns detected, don't auto-accept
    if needs_human_decision(output):
        print(f"[ParaPR] {ticket}: Human decision needed, not auto-accepting")
        return False

    # Check if it's safe to auto-accept via Azure OpenAI
    safety = await check_safety(ticket, output)
    if safety.safe_to_continue and not safety.needs_clarification:
        # Send "1" to select the first option (Yes)
        try:
            subprocess.run(["tmux", "send-keys", "-t", ticket, "C-u"], check=True, timeout=5)
            time.sleep(0.1)
            subprocess.run(["tmux", "send-keys", "-t", ticket, "-l", "1"], check=True, timeout=5)
            subprocess.run(["tmux", "send-keys", "-t", ticket, "Enter"], check=True, timeout=5)
            print(f"[ParaPR] {ticket}: Auto-accepted (safe operation)")
            return True
        except Exception as e:
            print(f"[ParaPR] {ticket}: Auto-accept failed: {e}")
    else:
        print(f"[ParaPR] {ticket}: Not auto-accepting: {safety.reason}")
    return False


async def stream_output(ticket: str, websocket: WebSocket):
    """Stream tmux output to WebSocket."""
    last_output = ""
    while True:
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", ticket, "-p", "-S", "-100"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                break

            current_output = result.stdout
            if current_output != last_output:
                # Find new lines
                new_content = current_output[len(last_output):] if current_output.startswith(last_output) else current_output
                if new_content.strip():
                    # Update buffer
                    if ticket not in output_buffers:
                        output_buffers[ticket] = []
                    output_buffers[ticket].extend(new_content.split("\n"))
                    output_buffers[ticket] = output_buffers[ticket][-MAX_BUFFER_LINES:]

                    # Check for permission prompts and auto-accept if enabled
                    auto_accepted = await auto_accept_if_safe(ticket, current_output)

                    # Check if needs attention (only if not auto-accepted)
                    if not auto_accepted:
                        safety = await check_safety(ticket, new_content)
                        if ticket in sessions:
                            sessions[ticket].needs_attention = safety.needs_clarification
                    else:
                        if ticket in sessions:
                            sessions[ticket].needs_attention = False

                    # Send to WebSocket
                    await websocket.send_json({
                        "type": "output",
                        "ticket": ticket,
                        "content": new_content,
                        "needs_attention": sessions.get(ticket, SessionStatus(ticket=ticket)).needs_attention,
                        "auto_accepted": auto_accepted
                    })
                last_output = current_output
            await asyncio.sleep(0.3)
        except WebSocketDisconnect:
            break
        except Exception:
            await asyncio.sleep(1)


# Dashboard HTML
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>ParaPR</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', monospace; background: #0d1117; color: #c9d1d9; display: flex; height: 100vh; overflow: hidden; }

        /* Sidebar */
        .sidebar { width: 220px; min-width: 220px; background: #161b22; border-right: 1px solid #30363d; display: flex; flex-direction: column; }
        .sidebar-header { padding: 16px; border-bottom: 1px solid #30363d; display: flex; justify-content: space-between; align-items: center; }
        .sidebar-header h1 { font-size: 1.2em; color: #58a6ff; }
        .sidebar-section { padding: 8px 0; }
        .sidebar-section-title { padding: 8px 16px; font-size: 0.75em; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; }
        .sidebar-item { padding: 8px 16px; cursor: pointer; display: flex; align-items: center; gap: 8px; border-left: 3px solid transparent; transition: background 0.15s; }
        .sidebar-item:hover { background: #21262d; }
        .sidebar-item.active { background: #21262d; border-left-color: #58a6ff; }
        .sidebar-item.needs-attention { border-left-color: #f85149; }
        .sidebar-item .dot { width: 8px; height: 8px; border-radius: 50%; background: #3fb950; }
        .sidebar-item .dot.attention { background: #f85149; animation: pulse 1.5s infinite; }
        .sidebar-item .dot.inactive { background: #484f58; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .available-item { color: #8b949e; }
        .available-item:hover { color: #c9d1d9; }

        /* Main panel */
        .main { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 600px; }
        .main-header { padding: 16px; border-bottom: 1px solid #30363d; display: flex; justify-content: space-between; align-items: center; }
        .main-header h2 { font-size: 1em; }
        .main-content { flex: 1; overflow: auto; padding: 16px; }

        /* Session grid */
        .session-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(500px, 1fr)); gap: 16px; height: 100%; }
        .session-panel { background: #161b22; border: 1px solid #30363d; border-radius: 8px; display: flex; flex-direction: column; overflow: hidden; }
        .session-panel.attention { border-color: #f85149; }
        .session-panel-header { padding: 12px 16px; border-bottom: 1px solid #30363d; display: flex; justify-content: space-between; align-items: center; }
        .session-panel-title { font-weight: bold; color: #58a6ff; }
        .session-panel-close { background: none; border: none; color: #8b949e; cursor: pointer; font-size: 1.2em; }
        .session-panel-close:hover { color: #f85149; }
        .session-panel-workflow { display: flex; gap: 4px; padding: 8px 16px; border-bottom: 1px solid #30363d; }
        .session-panel-workflow .step { padding: 4px 8px; font-size: 0.75em; border-radius: 4px; background: #21262d; color: #8b949e; cursor: pointer; }
        .session-panel-workflow .step.done { background: #238636; color: #fff; }
        .session-panel-workflow .step.active { background: #1f6feb; color: #fff; }
        .session-panel-output { flex: 1; background: #0d1117; padding: 12px; font-family: monospace; font-size: 0.85em; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
        .session-panel-input { padding: 12px; border-top: 1px solid #30363d; display: flex; gap: 8px; flex-wrap: wrap; }
        .session-panel-input input { flex: 1; min-width: 200px; padding: 8px 12px; border: 1px solid #30363d; border-radius: 4px; background: #0d1117; color: #c9d1d9; font-family: monospace; }
        .session-panel-input button { padding: 8px 12px; border: none; border-radius: 4px; cursor: pointer; background: #21262d; color: #c9d1d9; }
        .session-panel-input button:hover { background: #30363d; }
        .session-panel-input button.send { background: #238636; }
        .session-panel-input button.send:hover { background: #2ea043; }
        .session-panel-input button.danger { background: #da3633; }

        /* Batch actions dropdown */
        .batch-dropdown { position: relative; display: inline-block; }
        .batch-dropdown-btn { padding: 8px 16px; background: #21262d; border: 1px solid #30363d; border-radius: 4px; color: #c9d1d9; cursor: pointer; }
        .batch-dropdown-content { display: none; position: absolute; right: 0; background: #161b22; border: 1px solid #30363d; border-radius: 4px; min-width: 150px; z-index: 100; }
        .batch-dropdown:hover .batch-dropdown-content { display: block; }
        .batch-dropdown-content button { display: block; width: 100%; padding: 8px 16px; border: none; background: none; color: #c9d1d9; text-align: left; cursor: pointer; }
        .batch-dropdown-content button:hover { background: #21262d; }

        /* Empty state */
        .empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: #484f58; text-align: center; }
        .empty-state p { margin: 8px 0; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-header">
            <h1>ParaPR</h1>
            <button onclick="refreshWorktrees()" style="background:none;border:none;color:#8b949e;cursor:pointer;">↻</button>
        </div>
        <div class="sidebar-section" style="padding:8px 16px;display:flex;gap:8px;">
            <button onclick="startAll()" style="flex:1;padding:8px;background:#238636;border:none;border-radius:4px;color:#fff;cursor:pointer;font-weight:bold;">▶ Start All</button>
            <button onclick="killAll()" style="flex:1;padding:8px;background:#da3633;border:none;border-radius:4px;color:#fff;cursor:pointer;font-weight:bold;">⏹ Kill All</button>
        </div>
        <div class="sidebar-section">
            <div class="sidebar-section-title">Active Sessions</div>
            <div id="active-sessions"></div>
        </div>
        <div class="sidebar-section">
            <div class="sidebar-section-title">Available Worktrees</div>
            <div id="available-worktrees"></div>
        </div>
    </div>
    <div class="main">
        <div class="main-header">
            <h2 id="main-title">Sessions</h2>
            <div class="batch-dropdown">
                <button class="batch-dropdown-btn">Batch Actions ▾</button>
                <div class="batch-dropdown-content">
                    <button onclick="batchAction('/linear')">All: Pull Linear</button>
                    <button onclick="batchAction('/specify')">All: /specify</button>
                    <button onclick="batchAction('/clarify')">All: /clarify</button>
                    <button onclick="batchAction('/plan')">All: /plan</button>
                    <button onclick="batchAction('/tasks')">All: /tasks</button>
                    <button onclick="batchAction('/implement')">All: /implement</button>
                </div>
            </div>
        </div>
        <div class="main-content" id="main-content">
            <div class="session-grid" id="session-grid"></div>
        </div>
    </div>

    <script>
        let sessions = {};
        let worktrees = {};
        let gridSessions = new Set();
        let wsConnections = {};
        let sessionOutputs = {};

        async function fetchSessions() {
            const res = await fetch('/sessions');
            sessions = await res.json();
            renderSidebar();
            renderGrid();
        }

        async function fetchWorktrees() {
            const res = await fetch('/worktrees');
            worktrees = await res.json();
            renderSidebar();
        }

        function renderSidebar() {
            // Active sessions
            const activeEl = document.getElementById('active-sessions');
            let activeHtml = '';
            for (const [ticket, info] of Object.entries(sessions).sort()) {
                const attention = info.needs_attention ? 'needs-attention' : '';
                const dotClass = info.needs_attention ? 'attention' : '';
                const inGrid = gridSessions.has(ticket) ? 'active' : '';
                activeHtml += `
                    <div class="sidebar-item ${attention} ${inGrid}" onclick="togglePanel('${ticket}')">
                        <span class="dot ${dotClass}"></span>
                        <span style="flex:1;">${ticket.toUpperCase()}</span>
                        ${info.needs_attention ? '<span>⚠️</span>' : ''}
                    </div>`;
            }
            activeEl.innerHTML = activeHtml || '<div style="padding:8px 16px;color:#484f58;font-size:0.85em;">No active sessions</div>';

            // Available worktrees
            const availEl = document.getElementById('available-worktrees');
            let availHtml = '';
            for (const [ticket, info] of Object.entries(worktrees).sort()) {
                if (!info.active) {
                    availHtml += `
                        <div class="sidebar-item available-item" onclick="startSession('${ticket}')">
                            <span class="dot inactive"></span>
                            ${ticket}
                        </div>`;
                }
            }
            availEl.innerHTML = availHtml || '<div style="padding:8px 16px;color:#484f58;font-size:0.85em;">No available worktrees</div>';
        }

        function renderGrid() {
            const grid = document.getElementById('session-grid');
            document.getElementById('main-title').textContent = `Sessions (${gridSessions.size} open)`;

            if (gridSessions.size === 0) {
                grid.innerHTML = '<div class="empty-state"><p>No panels open</p><p style="font-size:0.85em;">Click a session in the sidebar to open it</p></div>';
                return;
            }

            let html = '';
            for (const ticket of gridSessions) {
                const info = sessions[ticket] || {};
                const attention = info.needs_attention ? 'attention' : '';
                const output = (sessionOutputs[ticket] || []).join('\\n');
                const steps = [
                    {key: 'linear_pulled', label: 'Linear'},
                    {key: 'specify_done', label: 'Spec'},
                    {key: 'clarify_done', label: 'Clarify'},
                    {key: 'plan_done', label: 'Plan'},
                    {key: 'tasks_done', label: 'Tasks'},
                    {key: 'implement_done', label: 'Impl'}
                ];
                const stepsHtml = steps.map(s => {
                    const cls = info[s.key] ? 'done' : '';
                    return `<div class="step ${cls}" onclick="runStep('${ticket}', '${s.key}')">${s.label}</div>`;
                }).join('');

                const isAutoAccept = info.claude_mode === 'auto_accept' || info.auto_accept;
                html += `
                    <div class="session-panel ${attention}" id="panel-${ticket}">
                        <div class="session-panel-header">
                            <span class="session-panel-title">${ticket.toUpperCase()}: ${escapeHtml(info.linear_title || info.state || 'Starting...')}</span>
                            <div style="display:flex;gap:8px;align-items:center;">
                                <button class="${isAutoAccept ? '' : 'active'}" onclick="setMode('${ticket}','planning')" style="padding:4px 8px;border-radius:4px;border:1px solid #30363d;background:${isAutoAccept ? '#21262d' : '#238636'};color:#fff;cursor:pointer;font-size:0.75em;">Planning</button>
                                <button class="${isAutoAccept ? 'active' : ''}" onclick="setMode('${ticket}','auto_accept')" style="padding:4px 8px;border-radius:4px;border:1px solid #30363d;background:${isAutoAccept ? '#238636' : '#21262d'};color:#fff;cursor:pointer;font-size:0.75em;">Auto</button>
                                <button class="session-panel-close" onclick="togglePanel('${ticket}')">×</button>
                            </div>
                        </div>
                        <div class="session-panel-workflow">${stepsHtml}</div>
                        <div class="session-panel-output" id="output-${ticket}">${escapeHtml(output)}</div>
                        <div class="session-panel-input">
                            <input type="text" id="input-${ticket}" placeholder="Send to Claude..." onkeypress="if(event.key==='Enter')sendInput('${ticket}')">
                            <button class="send" onclick="sendInput('${ticket}')">Send</button>
                            <button onclick="sendQuick('${ticket}', 'yes')">yes</button>
                            <button onclick="sendQuick('${ticket}', 'no')">no</button>
                            <button onclick="sendQuick('${ticket}', 'continue')">continue</button>
                            <button class="danger" onclick="interrupt('${ticket}')">^C</button>
                        </div>
                    </div>`;
            }
            grid.innerHTML = html;
        }

        function togglePanel(ticket) {
            if (gridSessions.has(ticket)) {
                // Close panel
                gridSessions.delete(ticket);
                if (wsConnections[ticket]) {
                    wsConnections[ticket].close();
                    delete wsConnections[ticket];
                }
            } else {
                // Open panel
                gridSessions.add(ticket);
                connectWS(ticket);
            }
            renderSidebar();
            renderGrid();
        }

        function connectWS(ticket) {
            if (wsConnections[ticket]) return;
            const ws = new WebSocket(`ws://${location.host}/ws/${ticket}`);
            ws.onmessage = (e) => {
                const data = JSON.parse(e.data);
                if (data.type === 'output') {
                    if (!sessionOutputs[ticket]) sessionOutputs[ticket] = [];
                    sessionOutputs[ticket].push(...data.content.split('\\n').filter(l => l.trim()));
                    sessionOutputs[ticket] = sessionOutputs[ticket].slice(-200);

                    // Update output element
                    const el = document.getElementById(`output-${ticket}`);
                    if (el) {
                        el.textContent = sessionOutputs[ticket].join('\\n');
                        el.scrollTop = el.scrollHeight;
                    }

                    // Update attention state
                    if (sessions[ticket]) {
                        sessions[ticket].needs_attention = data.needs_attention;
                    }
                    renderSidebar();
                }
            };
            ws.onclose = () => { delete wsConnections[ticket]; };
            wsConnections[ticket] = ws;
        }

        async function startSession(ticket) {
            const res = await fetch(`/sessions/${ticket}/start`, {method: 'POST'});
            if (res.ok) {
                await fetchSessions();
                await fetchWorktrees();
                togglePanel(ticket);
            }
        }

        async function sendInput(ticket) {
            const input = document.getElementById(`input-${ticket}`);
            const text = input.value.trim();
            if (text) {
                await fetch(`/session/${ticket}/send`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({text})
                });
                input.value = '';
            }
        }

        async function sendQuick(ticket, cmd) {
            await fetch(`/session/${ticket}/send`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({text: cmd})
            });
        }

        async function interrupt(ticket) {
            await fetch(`/session/${ticket}/interrupt`, {method: 'POST'});
        }

        async function setMode(ticket, mode) {
            await fetch(`/session/${ticket}/mode?mode=${mode}`, {method: 'POST'});
            await fetchSessions();
            renderGrid();
        }

        async function runStep(ticket, step) {
            const cmds = {
                'linear_pulled': `/linear ${ticket.toUpperCase()}`,
                'specify_done': '/specify',
                'clarify_done': '/clarify',
                'plan_done': '/plan',
                'tasks_done': '/tasks',
                'implement_done': '/implement'
            };
            if (cmds[step]) {
                await sendQuick(ticket, cmds[step]);
                await fetch(`/session/${ticket}/stage?stage=${step.replace('_done','').replace('_pulled','')}&done=true`, {method: 'POST'});
            }
        }

        async function batchAction(cmd) {
            for (const ticket of Object.keys(sessions)) {
                if (cmd === '/linear') {
                    await sendQuick(ticket, `/linear ${ticket.toUpperCase()}`);
                } else {
                    await sendQuick(ticket, cmd);
                }
                await new Promise(r => setTimeout(r, 500));
            }
        }

        function refreshWorktrees() {
            fetchWorktrees();
            fetchSessions();
        }

        async function startAll() {
            const btn = event.target;
            btn.textContent = 'Starting...';
            btn.disabled = true;
            try {
                await fetch('/sessions/start-all', {method: 'POST'});
                await new Promise(r => setTimeout(r, 2000));
                await fetchSessions();
                await fetchWorktrees();
            } finally {
                btn.textContent = '▶ Start All';
                btn.disabled = false;
            }
        }

        async function killAll() {
            if (!confirm('Kill all tmux sessions?')) return;
            const btn = event.target;
            btn.textContent = 'Killing...';
            btn.disabled = true;
            try {
                await fetch('/sessions/kill-all', {method: 'POST'});
                // Clear local state
                sessions = {};
                gridSessions.clear();
                sessionOutputs = {};
                for (const ws of Object.values(wsConnections)) ws.close();
                wsConnections = {};
                await fetchSessions();
                await fetchWorktrees();
                renderGrid();
            } finally {
                btn.textContent = '⏹ Kill All';
                btn.disabled = false;
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text || '';
            return div.innerHTML;
        }

        // Initial load
        fetchSessions();
        fetchWorktrees();
        setInterval(fetchSessions, 10000);  // Refresh session states every 10s
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard."""
    return DASHBOARD_HTML


@app.get("/worktrees")
async def list_worktrees():
    """List available worktrees."""
    return get_worktrees()


@app.get("/sessions")
async def list_sessions():
    """List all session states."""
    return {k: v.model_dump() for k, v in sessions.items()}


@app.post("/sessions/{ticket}/start")
async def create_session(ticket: str):
    """Start a new Claude Code session for a single ticket."""
    return start_session([ticket])


@app.post("/sessions/start")
async def create_sessions(tickets: list[str]):
    """Start Claude Code sessions for multiple tickets."""
    return start_session(tickets)


@app.post("/sessions/start-all")
async def start_all_sessions():
    """Start all available worktrees that don't have active sessions."""
    worktrees = get_worktrees()
    tickets_to_start = [
        ticket for ticket, info in worktrees.items()
        if not info["active"]
    ]
    if not tickets_to_start:
        return {"ok": True, "message": "No worktrees to start", "started": []}
    return start_session(tickets_to_start)


@app.post("/sessions/kill-all")
async def kill_all_sessions():
    """Kill all tracked worktree tmux sessions."""
    killed = []
    errors = []

    # Kill all sessions we're tracking (worktree-based sessions)
    worktrees = get_worktrees()
    for ticket in list(sessions.keys()) + list(worktrees.keys()):
        if ticket in killed:
            continue
        try:
            result = subprocess.run(["tmux", "has-session", "-t", ticket], capture_output=True)
            if result.returncode == 0:
                subprocess.run(["tmux", "kill-session", "-t", ticket], check=True, timeout=5)
                killed.append(ticket)
            # Clean up local state
            if ticket in sessions:
                del sessions[ticket]
            if ticket in output_buffers:
                del output_buffers[ticket]
            if ticket in ws_connections:
                del ws_connections[ticket]
        except Exception as e:
            errors.append({"ticket": ticket, "error": str(e)})

    return {"ok": len(errors) == 0, "killed": killed, "errors": errors}


@app.get("/session/{ticket}")
async def get_session(ticket: str):
    """Get single session state."""
    if ticket in sessions:
        return sessions[ticket].model_dump()
    return {"error": "not found"}


@app.get("/session/{ticket}/output")
async def get_output(ticket: str, lines: int = 50):
    """Get recent output."""
    return {"output": "\n".join(output_buffers.get(ticket, [])[-lines:])}


@app.post("/session/{ticket}/send")
async def send_input(ticket: str, body: SendInput):
    """Send input to tmux session."""
    try:
        subprocess.run(["tmux", "send-keys", "-t", ticket, "C-u"], check=True, timeout=5)
        time.sleep(0.1)
        subprocess.run(["tmux", "send-keys", "-t", ticket, "-l", body.text], check=True, timeout=5)
        subprocess.run(["tmux", "send-keys", "-t", ticket, "Enter"], check=True, timeout=5)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/session/{ticket}/interrupt")
async def interrupt_session(ticket: str):
    """Send Ctrl+C to tmux session."""
    try:
        subprocess.run(["tmux", "send-keys", "-t", ticket, "C-c"], check=True, timeout=5)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/session/{ticket}/stage")
async def update_stage(ticket: str, stage: str, done: bool):
    """Update workflow stage."""
    if ticket not in sessions:
        sessions[ticket] = SessionStatus(ticket=ticket)

    stage_map = {
        "linear": "linear_pulled",
        "specify": "specify_done",
        "clarify": "clarify_done",
        "plan": "plan_done",
        "tasks": "tasks_done",
        "implement": "implement_done"
    }
    if stage in stage_map:
        setattr(sessions[ticket], stage_map[stage], done)
    return {"ok": True}


@app.post("/session/{ticket}/linear-info")
async def set_linear_info(ticket: str, title: str = "", description: str = ""):
    """Store Linear ticket info."""
    if ticket not in sessions:
        sessions[ticket] = SessionStatus(ticket=ticket)
    sessions[ticket].linear_title = title
    sessions[ticket].linear_description = description
    return {"ok": True}


@app.post("/session/{ticket}/mode")
async def set_claude_mode(ticket: str, mode: str):
    """Switch auto-accept mode (server-side only, no tmux commands).

    This controls whether the ParaPR server auto-accepts permission prompts.
    It does NOT send keystrokes to Claude - that was causing Claude to exit.

    - planning: Server flags permission prompts for human attention
    - auto_accept: Server auto-accepts safe permission prompts via Azure OpenAI
    """
    if ticket not in sessions:
        sessions[ticket] = SessionStatus(ticket=ticket)

    if mode == "auto_accept":
        sessions[ticket].claude_mode = ClaudeMode.AUTO_ACCEPT
        sessions[ticket].auto_accept = True
        print(f"[ParaPR] {ticket}: Switched to AUTO mode - will auto-accept safe operations")
    else:
        sessions[ticket].claude_mode = ClaudeMode.PLANNING
        sessions[ticket].auto_accept = False
        print(f"[ParaPR] {ticket}: Switched to PLANNING mode - will flag all prompts for human")

    return {"ok": True, "mode": mode}


@app.websocket("/ws/{ticket}")
async def websocket_endpoint(websocket: WebSocket, ticket: str):
    """WebSocket for streaming session output."""
    await websocket.accept()
    if ticket not in ws_connections:
        ws_connections[ticket] = []
    ws_connections[ticket].append(websocket)

    try:
        await stream_output(ticket, websocket)
    except WebSocketDisconnect:
        pass
    finally:
        if ticket in ws_connections and websocket in ws_connections[ticket]:
            ws_connections[ticket].remove(websocket)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8765)
