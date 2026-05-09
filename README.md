# OpenSwarm

Design AI teams in YAML. Cheap models do bulk work, expensive models make decisions — you control who does what.

```yaml
agents:
  - name: "senior"
    model: claude-sonnet-4-20250514
    role: senior
    rules: ["Break down tasks", "Review junior's output"]

  - name: "junior"
    model: deepseek-chat
    role: junior
    rules: ["Execute assigned tasks", "Write tests"]
```

```bash
swarm run "Build user auth API" --config team.yaml
```

Senior breaks it down, delegates to Junior, reviews results, assembles final output. One command.

## Install

```bash
pip install openswarm

# With MCP server support
pip install openswarm[mcp]
```

## Usage

```bash
# Run with config file
swarm run "Build a REST API" --config team.yaml

# Run with named team (looks up ~/.openswarm/teams/<name>.yaml)
swarm run "Fix the login bug" --team backend

# Verbose — see all inter-agent messages
swarm run "Refactor auth module" --config team.yaml -v

# Interactive REPL — chat with your team
swarm interactive --team backend

# Interactive with real-time message display
swarm interactive --team backend -v

# Run as module
python -m openswarm run "Do the thing" --config team.yaml
```

### Interactive Mode

Start a persistent session where your team keeps context across tasks:

```bash
swarm interactive --team backend
```

Slash commands inside the REPL:

| Command | Action |
|---------|--------|
| `/quit` | Exit |
| `/team` | Show team info |
| `/history` | Show message log |
| `/clear` | Clear message history |

Ctrl+C cancels current task without exiting.

### MCP Server

Expose your teams as tools for Claude Code or other MCP clients:

```bash
# Start MCP server
python -m openswarm.mcp.server
```

Provides three tools:

| Tool | Description |
|------|-------------|
| `run_task(task, team_name)` | Run a task with a team |
| `list_teams()` | List configured teams |
| `team_info(team_name)` | Show team details |

## Team Config

```yaml
team:
  name: "backend-team"
  goal: "Build and maintain backend services"
  workflow: hierarchical
  lead: "senior"
  max_rounds: 10

agents:
  - name: "senior"
    role: senior
    model: claude-sonnet-4-20250514
    host: https://api.anthropic.com
    api_key: ${ANTHROPIC_API_KEY}
    max_tokens: 4096
    rules:
      - "Break down tasks and delegate to junior"
      - "Review output before marking done"

  - name: "junior"
    role: junior
    model: deepseek-chat
    host: https://api.deepseek.com/v1
    api_key: ${DEEPSEEK_API_KEY}
    max_tokens: 2048
    rules:
      - "Execute assigned tasks"
      - "Write tests for all code"
```

API keys use `${ENV_VAR}` syntax — never hardcoded.

## How It Works

```
User: "Build user auth API"
  ↓
Senior (Claude): decomposes task
  ├── "Write User model" → Junior (DeepSeek)
  ├── "Write endpoints"  → Junior (DeepSeek)
  └── "Design JWT strategy" → Senior handles directly
  ↓
Junior returns code → Senior reviews → approves or requests fixes
  ↓
Final result → User
```

## Workflow Types

| Type | How it works | Best for |
|------|-------------|----------|
| **hierarchical** | Lead delegates, reviews, assembles | Dev teams, review workflows |
| pipeline | Sequential: A → B → C | Content pipelines, data processing |
| collaborative | All agents discuss → consensus | Brainstorming, code review |

*Currently implemented: hierarchical. Pipeline and collaborative coming soon.*

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENSWARM_CONFIG_DIR` | `~/.openswarm` | Config directory |
| `OPENSWARM_LOG_LEVEL` | `INFO` | Log level |

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
ruff check src/ tests/ && ruff format src/ tests/
```

## Why OpenSwarm?

Running everything through one expensive model wastes money. Most tasks don't need GPT-4 or Claude Opus. OpenSwarm lets you design teams where the right model handles the right job — by your design, not automation.

## License

MIT
