# ParaPR Workflow System

## Overview
ParaPR now includes intelligent workflow orchestration that automates the development process while maintaining human oversight where needed.

## Workflow Stages

1. **Linear** - Auto-runs on session start to fetch ticket details
2. **Specify** - Define requirements (user must confirm to proceed)
3. **Plan** - Create implementation plan
4. **Tasks** - Break down into tasks
5. **Implement** - Execute implementation

## How It Works

### Auto-Start
- When a session starts, `/linear <TICKET>` runs automatically
- System waits for Linear ticket to load
- Session pauses with "Review Linear ticket and click Specify to continue"

### User Review Gate
- After Linear completes, user **must review** the ticket details
- User clicks the **"Specify"** step button when ready to proceed
- This is the only required manual intervention (unless clarification needed)

### Automated Execution
- Once "Specify" is clicked, the workflow runs automatically:
  - `/specify` → `/plan` → `/tasks` → `/implement`
- Each stage auto-advances to the next when complete
- System only pauses if:
  - Clarification is needed (detected by LLM)
  - A dangerous operation is detected
  - User intervention is required

### Safety & Permission Handling

#### Auto-Accept Modes
- **Planning Mode** (default): LLM checks all prompts, flags for human review
- **Auto Mode**: LLM auto-accepts safe operations

#### Startup Prompts
- "Press Enter to continue" - **Always auto-accepted**
- Claude welcome screen - **Always auto-accepted**

#### Safe Operations (Auto-accepted in Auto Mode)
- Read operations (`linearis read`, `cat`, `grep`)
- Search operations (`find`, `glob`)
- Creating/editing source code files
- Running tests, linters
- Git status, diff, log, branch
- Package installs

#### Dangerous Operations (Always blocked)
- DELETE operations (`rm`, `rm -rf`)
- Database writes (`DROP`, `TRUNCATE`, `DELETE FROM`)
- Git force operations (`push --force`, `reset --hard`)
- Modifying `.env` files or credentials

### State Management
- System tracks last checked output to avoid duplicate LLM calls
- Resets state after auto-accepting to check next prompt
- Workflow pauses automatically when clarification needed

## UI Features

### Status Indicators
- **Green dot**: Session active and running
- **Red dot + pulse**: Needs attention
- **⏸ Waiting for review**: Paused for user confirmation
- **Status message**: Shows current workflow state

### Quick Action Buttons
- **yes/no**: Quick responses to Claude
- **↵ Enter**: Send Enter key (for startup prompts)
- **continue**: Continue after review
- **^C**: Interrupt running command

### Workflow Step Buttons
- Click any step to manually trigger that stage
- Green = completed
- Clicking "Specify" after Linear = starts auto-workflow

### Mode Toggle
- **Planning**: Review all prompts (safe default)
- **Auto**: Auto-accept safe operations (faster)

## Environment Setup

### Required `.env` Variables
```bash
WORKTREES_DIR="/path/to/your/worktrees"
AZ_OPENAI_API_BASE="https://your-instance.openai.azure.com/"
AZ_OPENAI_API_KEY="your-key"
AZ_OPENAI_DEPLOYMENT_NAME="GPT_4O_GLOBAL"
LINEAR_API_KEY="your-linear-key"
```

## Usage

### Start All Sessions
1. Open dashboard: http://localhost:8765
2. Click **"▶ Start All"**
3. Sessions auto-open in grid view
4. Each session auto-runs `/linear`
5. Review ticket details
6. Click **"Specify"** button to start auto-workflow
7. System runs to completion unless clarification needed

### Manual Control
- Click any step button to run that specific stage
- Click **Planning/Auto** to toggle automation mode
- Use quick buttons for common responses
- Click **^C** to interrupt if needed

## Benefits

✅ **Parallel Development**: Run 6+ tickets simultaneously  
✅ **Minimal Intervention**: Only review at key checkpoints  
✅ **Safe by Default**: LLM reviews all potentially dangerous operations  
✅ **Fully Auditable**: All actions logged in real-time  
✅ **Flexible**: Manual override available at any time  
✅ **Efficient**: No duplicate LLM calls, smart state management

