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
openswarm run "Build user auth API" --config team.yaml
```

Senior breaks it down, delegates to Junior, reviews results, assembles final output. One command.

## Install

```bash
pip install openswarm-ai

# With MCP server support
pip install openswarm-ai[mcp]
```

## Integration

The easiest way to use OpenSwarm — add a `team.yaml` to your project and let your AI IDE delegate to your agent team automatically.

### Supported

| Tool | Integration | Status |
|------|------------|--------|
| **Claude Code** | MCP server (auto-discovery via `.mcp.json`) | Ready |
| **OpenCode** | MCP server (auto-discovery via `opencode.json`) | Ready |
| **Cursor** | MCP server (via Cursor settings) | Ready |
| **Windsurf** | MCP server (via `~/.codeium/windsurf/mcp_config.json`) | Ready |
| **GitHub Copilot** | MCP server (via VS Code `settings.json`) | Ready |

Any tool that supports MCP works with OpenSwarm — the setup is the same pattern everywhere.

### Setup (one-time)

```bash
pip install openswarm-ai[mcp]
```

Then register the MCP server with your tool:

<details>
<summary><strong>Claude Code</strong></summary>

```bash
claude mcp add openswarm -- openswarm-mcp
```
</details>

<details>
<summary><strong>OpenCode</strong></summary>

Add to your `opencode.json`:

```json
{
  "mcp": {
    "openswarm": {
      "type": "local",
      "command": ["openswarm-mcp"],
      "timeout": 300000
    }
  }
}
```
</details>

<details>
<summary><strong>Cursor</strong></summary>

Go to **Cursor Settings → MCP → Add new MCP server**:

- Name: `openswarm`
- Type: `command`
- Command: `openswarm-mcp`
</details>

<details>
<summary><strong>Windsurf</strong></summary>

Add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "openswarm": {
      "command": "openswarm-mcp",
      "args": []
    }
  }
}
```
</details>

<details>
<summary><strong>GitHub Copilot (VS Code)</strong></summary>

Add to VS Code `settings.json`:

```json
{
  "github.copilot.chat.mcp.servers": {
    "openswarm": {
      "command": "openswarm-mcp",
      "args": []
    }
  }
}
```
</details>

### Usage (per project)

Add a `team.yaml` to your project root — like `CLAUDE.md`, but for your agent team:

```yaml
# team.yaml
team:
  name: "backend-team"
  goal: "Build and maintain backend services"
  workflow: hierarchical
  lead: "senior"

agents:
  - name: "senior"
    role: senior
    model: claude-sonnet-4-20250514
    host: https://api.anthropic.com
    api_key: ${ANTHROPIC_API_KEY}
    max_tokens: 4096
    rules: ["Break down tasks", "Review output"]

  - name: "junior"
    role: junior
    model: deepseek-chat
    host: https://api.deepseek.com/v1
    api_key: ${DEEPSEEK_API_KEY}
    max_tokens: 2048
    rules: ["Execute assigned tasks", "Write tests"]
```

That's it. The MCP server auto-discovers `team.yaml` from the working directory. Claude Code and OpenCode see the tools and delegate when the task matches — no special prompting needed.

### MCP Tools

| Tool | Description |
|------|-------------|
| `openswarm_run(task, team?)` | Delegate a task to an agent team (auto-selects if one team exists) |
| `openswarm_teams()` | List available teams (local + global) |
| `openswarm_team_info(team)` | Show team details — agents, models, workflow |

The server also discovers teams from `openswarm/*.yaml` in the project and `~/.openswarm/teams/` globally.

## CLI Usage

```bash
# Run with config file
openswarm run "Build a REST API" --config team.yaml

# Run with named team (looks up ~/.openswarm/teams/<name>.yaml)
openswarm run "Fix the login bug" --team backend

# Verbose — see inter-agent messages in real-time
openswarm run "Refactor auth module" --config team.yaml -v

# List all configured teams
openswarm team-list

# Show team details
openswarm team-info backend

# Run as module
python -m openswarm run "Do the thing" --config team.yaml
```

### Interactive Mode (experimental)

Interactive REPL for chatting with your team. We're actively improving this as a separate effort.

```bash
openswarm interactive --team backend
openswarm interactive --team backend -v  # with real-time message display
```

Slash commands: `/quit`, `/team`, `/history`, `/clear`. Ctrl+C cancels current task without exiting.

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
    temperature: 0.7
    rules:
      - "Break down tasks and delegate to junior"
      - "Review output before marking done"

  - name: "junior"
    role: junior
    model: deepseek-chat
    host: https://api.deepseek.com/v1
    api_key: ${DEEPSEEK_API_KEY}
    max_tokens: 2048
    temperature: 0.3
    rules:
      - "Execute assigned tasks"
      - "Write tests for all code"
```

### Agent Config Fields

| Field | Default | Description |
|-------|---------|-------------|
| `name` | required | Agent identifier |
| `role` | required | Agent role description |
| `model` | required | LLM model name |
| `host` | required | API endpoint URL |
| `api_key` | required | API key (supports `${ENV_VAR}` syntax) |
| `max_tokens` | `4096` | Max tokens per response (≥ 1) |
| `temperature` | `0.7` | Sampling temperature (0.0–2.0) |
| `max_history` | `40` | Max messages kept in agent history (≥ 1) |
| `rules` | `[]` | Agent behavior rules |

## How It Works

```
User: "Build user auth API"
  ↓
Senior (Claude): decomposes task
  ├── "Write User model" → Junior (DeepSeek)
  ├── "Write endpoints"  → Junior (DeepSeek)
  └── "Design JWT strategy" → Senior handles directly
  ↓
Junior returns code → Senior reviews → requests fixes or approves
  ↓
Final result → User
```

## Workflow Types

| Type | How it works | Best for |
|------|-------------|----------|
| **hierarchical** | Lead delegates, reviews, requests revisions, assembles | Dev teams, review workflows |
| **pipeline** | Sequential: A → B → C — each agent transforms output | Content pipelines, data processing |
| **collaborative** | All agents discuss → consensus | Brainstorming, code review, decision-making |

### Pipeline Workflow

Sequential chain where each agent receives the previous agent's output:

```yaml
team:
  name: "content-pipeline"
  goal: "Write and polish articles"
  workflow: pipeline

agents:
  - name: "writer"
    role: writer
    # ...
  - name: "editor"
    role: editor
    # ...
  - name: "reviewer"
    role: reviewer
    # ...
```

Agents execute in config list order. No lead required.

### Collaborative Workflow

All agents see the task simultaneously and discuss in rounds. First agent in the list acts as moderator. Early exit if all agents agree. Moderator synthesizes the final answer.

```yaml
team:
  name: "review-panel"
  goal: "Review and decide on architecture"
  workflow: collaborative
  max_rounds: 5

agents:
  - name: "moderator"
    role: architect
    # ... (first agent = moderator)
  - name: "backend"
    role: backend-specialist
    # ...
  - name: "frontend"
    role: frontend-specialist
    # ...
```

Requires at least 2 agents. No `lead` field needed.

## Error Handling

- LLM calls retry once on transient errors (rate limits, timeouts, connection issues)
- Permanent errors (bad API key, invalid model) fail immediately with a clear message
- `openswarm run` shows clean error output instead of tracebacks
- Config validation catches problems at load time (missing lead agent, invalid temperature/token values)

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

## Why OpenSwarm? Cost Comparison

Running everything through one expensive model wastes money. Most coding tasks — writing boilerplate, implementing endpoints, writing tests — don't need the most capable model. OpenSwarm lets you route work to the right model.

### Example: "Build user auth API"

**Without OpenSwarm** — Claude Code does everything with Claude Sonnet:

| Step | Model | Input tokens | Output tokens | Cost |
|------|-------|-------------|---------------|------|
| Decompose task | Sonnet | ~2,000 | ~500 | $0.009 |
| Write User model | Sonnet | ~3,000 | ~1,500 | $0.019 |
| Write endpoints | Sonnet | ~4,000 | ~2,000 | $0.024 |
| Write tests | Sonnet | ~5,000 | ~2,500 | $0.030 |
| Review & fix | Sonnet | ~6,000 | ~1,500 | $0.027 |
| **Total** | | **~20,000** | **~8,000** | **~$0.109** |

*Sonnet: $3/M input, $15/M output*

**With OpenSwarm** — Senior (Sonnet) delegates bulk work to Junior (DeepSeek):

| Step | Model | Input tokens | Output tokens | Cost |
|------|-------|-------------|---------------|------|
| Decompose + delegate | Sonnet | ~2,000 | ~500 | $0.009 |
| Write User model | DeepSeek | ~3,000 | ~1,500 | $0.001 |
| Write endpoints | DeepSeek | ~4,000 | ~2,000 | $0.002 |
| Write tests | DeepSeek | ~5,000 | ~2,500 | $0.002 |
| Review & approve | Sonnet | ~4,000 | ~500 | $0.020 |
| **Total** | | **~18,000** | **~7,000** | **~$0.034** |

*DeepSeek: $0.14/M input, $0.28/M output*

**Result: ~70% cost reduction** on the same task, with the expensive model only doing what it's good at — architecture and review.

### At scale

| Scenario | Without OpenSwarm | With OpenSwarm | Savings |
|----------|------------------|----------------|---------|
| 10 features/day | ~$1.09 | ~$0.34 | 69% |
| 100 features/day | ~$10.90 | ~$3.40 | 69% |
| With Opus as lead | ~$3.00 | ~$0.85 | 72% |

The more work you can route to cheap models, the more you save. Senior handles ~20% of tokens but makes the decisions that matter.

## License

MIT
