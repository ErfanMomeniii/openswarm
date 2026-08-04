# OpenSwarm

[![PyPI version](https://img.shields.io/pypi/v/openswarm-ai?label=pypi)](https://pypi.org/project/openswarm-ai/)
[![CI](https://github.com/ErfanMomeniii/openswarm/actions/workflows/ci.yml/badge.svg)](https://github.com/ErfanMomeniii/openswarm/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://pypi.org/project/openswarm-ai/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://github.com/ErfanMomeniii/openswarm/blob/master/LICENSE)

**Cut your AI coding costs by ~70%.** Define agent teams in YAML — cheap models do bulk work, expensive models make decisions. Works inside Claude Code, Cursor, Copilot, and any MCP-compatible IDE.

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
pipx install "openswarm-ai[mcp]"
```

This installs everything: the `openswarm` CLI, the `openswarm-mcp` server, and all dependencies. The `[mcp]` extra adds MCP server support for IDE integration (Claude Code, Cursor, etc.).

> **Why pipx?** It installs OpenSwarm globally in an isolated environment — available from any project, no venv conflicts. [Install pipx](https://pipx.pypa.io/stable/how-to/install-pipx/) if you don't have it. Or use `brew install pipx` on macOS.

## Get Started

### 1. Scaffold a team

```bash
cd your-project
openswarm init            # writes team.yaml — pick a layout when prompted
openswarm doctor          # verifies config + API keys before you spend anything
```

`openswarm init` templates:

| Template | Layout |
|----------|--------|
| `hierarchical` | Senior lead delegates to a cheap junior, then reviews (default) |
| `pipeline` | writer → editor → reviewer, each transforms the previous output |
| `collaborative` | Agents discuss in rounds until consensus, moderator synthesizes |
| `local` | Two Ollama models — no API keys needed |

```bash
openswarm init --list-templates          # see them all
openswarm init -T local                  # non-interactive
openswarm init --global --name backend   # install to ~/.openswarm/teams/ for all projects
```

The generated `team.yaml` sits in your project root — like a `CLAUDE.md`, but for your agent team. Edit models and rules to taste.

### 2. Register with your IDE (one-time)

<details open>
<summary><strong>Claude Code</strong></summary>

```bash
claude mcp add openswarm -- openswarm-mcp
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

### 3. Use your IDE normally

That's it. Open your project, give coding tasks — your IDE automatically delegates to the team. No special commands, no prompting needed.

### Supported IDEs

| Tool | Integration | Status |
|------|------------|--------|
| **Claude Code** | MCP server (auto-discovery via `.mcp.json`) | Ready |
| **OpenCode** | MCP server (auto-discovery via `opencode.json`) | Ready |
| **Cursor** | MCP server (via Cursor settings) | Ready |
| **Windsurf** | MCP server (via `~/.codeium/windsurf/mcp_config.json`) | Ready |
| **GitHub Copilot** | MCP server (via VS Code `settings.json`) | Ready |

Any tool that supports MCP works with OpenSwarm — the setup is the same pattern everywhere.

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

**How does the IDE know to use OpenSwarm?** When `team.yaml` exists in your project, the MCP server tells your IDE to delegate all coding tasks to the team automatically. You just use your IDE normally.

**What if the task doesn't match the team?** For example, you have a frontend team but ask a backend question. The team's lead agent recognizes it's outside their scope and says so — your IDE then handles it directly. You never need to decide; just ask, and the system routes it to the right place.

### MCP Tools

| Tool | Description |
|------|-------------|
| `openswarm_run(task, team?)` | Delegate a task to an agent team (auto-selects if one team exists) |
| `openswarm_teams()` | List available teams (local + global) |
| `openswarm_team_info(team)` | Show team details — agents, models, workflow |

Config discovery: `team.yaml` / `openswarm.yaml` in project root, `openswarm/*.yaml` subdirectory, and `~/.openswarm/teams/` globally.

## CLI Usage

```bash
# Uses the project's team.yaml automatically — no flags needed
openswarm run "Build a REST API"

# Explicit config file, or a named team (project-local or global)
openswarm run "Build a REST API" --config team.yaml
openswarm run "Fix the login bug" --team backend

# Scaffold and check
openswarm init                  # create team.yaml
openswarm doctor                # validate configs, env vars, providers
openswarm doctor --check-connection   # also ping each agent's endpoint (a few tokens each)

# Inspect
openswarm team list             # all teams, local and global
openswarm team info backend     # agents, models, rules

# Run as Python module
python -m openswarm run "Do the thing"
```

### `run` flags

| Flag | Purpose |
|------|---------|
| `-c, --config PATH` | Use a specific config file |
| `-t, --team NAME` | Use a named team (project-local or `~/.openswarm/teams/`) |
| `-v, --verbose` | Show inter-agent messages as they happen |
| `-s, --stream` | Stream agent output token-by-token |
| `-q, --quiet` | Print only the result — for pipes and redirects |
| `-o, --output PATH` | Write the result to a file |
| `--max-rounds N` | Override the team's `max_rounds` for this run |

With no `-c`/`-t`, OpenSwarm uses the single discoverable team config. If several exist, it lists them and asks you to pick — it never guesses.

```bash
openswarm run "Summarize the auth flow" -q > auth-notes.md
```

### Interactive Mode (experimental)

Chat with your team in a persistent session. We're actively improving this.

```bash
openswarm interactive              # auto-discovers team.yaml
openswarm interactive -t backend -v
```

| Command | Does |
|---------|------|
| `/help` | List commands |
| `/team` | Show the current team |
| `/history` | Show message history |
| `/usage` | Token usage and cost for the whole session |
| `/save FILE` | Write the last result to a file |
| `/clear` | Clear history (messages and agent memory) |
| `/stream` | Toggle streaming |
| `/quit` | Exit (`/exit`, `/q` also work) |

Ctrl+C cancels the current task without exiting.

### Config discovery

`openswarm` and the MCP server look in the same places, in this order:

1. `team.yaml` / `team.yml` / `openswarm.yaml` / `.openswarm.yaml` in the current directory
2. `openswarm/*.yaml` in the current directory
3. `~/.openswarm/teams/*.yaml` (or `$OPENSWARM_CONFIG_DIR/teams/`)

Project-local configs win over global ones with the same name.

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

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | yes | — | Agent identifier |
| `role` | yes | — | What this agent does |
| `model` | yes | — | LLM model name |
| `host` | yes | — | API endpoint URL (OpenAI-compatible) |
| `api_key` | yes | — | API key (supports `${ENV_VAR}` syntax) |
| `max_tokens` | no | `4096` | Max tokens per response (≥ 1) |
| `temperature` | no | `0.7` | Sampling temperature (0.0–2.0) |
| `max_history` | no | `40` | Max messages kept in agent history (≥ 1) |
| `rules` | no | `[]` | Agent behavior rules |

Any string value supports `${VAR}` and `${VAR:-fallback}`:

```yaml
host: ${OLLAMA_HOST:-http://localhost:11434}
api_key: ${DEEPSEEK_API_KEY}
```

`${VAR}` with nothing set is an error with the exact `export` line you need. `${VAR:-fallback}` never fails.

**What models can I use?** Any model with an OpenAI-compatible API — Claude, GPT, DeepSeek, Mistral, Llama, local models via Ollama, or a self-hosted gateway. If [litellm](https://docs.litellm.ai/docs/providers) supports it, OpenSwarm supports it. If litellm can't infer the provider from a model name, prefix it with `openai/`.

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

- LLM calls retry twice on transient errors (rate limits, timeouts, connection issues)
- Permanent errors (bad API key, invalid model) fail immediately with a clear message
- `openswarm run` shows clean error output instead of tracebacks
- Config validation catches problems at load time: missing `lead`, unknown workflow type, duplicate agent names, invalid temperature/token values, malformed YAML — each naming the field and file
- Unset `${ENV_VAR}` references are reported together, with the `export` lines to fix them
- If a hierarchical run hits `max_rounds` without the lead finishing, the last real agent output is returned rather than discarded
- **One provider going down does not kill the run.** A failed worker is reported back to the lead, which routes around it or finishes the task itself; a failed participant is skipped in collaborative discussions; a failed pipeline stage passes the previous stage's output through. Only the lead agent failing is fatal, since nothing can drive the run without it.
- `openswarm doctor` catches all of the above before you spend a token

## Cost Comparison

Why pay for an expensive model to write boilerplate? Let the cheap model do the heavy lifting.

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

### See your actual usage

Every run prints a token-usage breakdown — per agent, per model, with totals — so you can verify the split for yourself instead of trusting the numbers above:

```
                           Token Usage
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┓
┃ Agent  ┃ Model               ┃ Prompt ┃ Completion ┃ Total ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━┩
│ senior │ claude-sonnet-4     │    777 │        152 │   929 │
│ junior │ deepseek-chat       │    442 │        163 │   605 │
├────────┼─────────────────────┼────────┼────────────┼───────┤
│ Total  │                     │   1219 │        315 │  1534 │
└────────┴─────────────────────┴────────┴────────────┴───────┘
```

A `Cost` column is added automatically when the provider returns price information. The same summary is appended to the MCP tool response, so IDEs see it too.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENSWARM_CONFIG_DIR` | `~/.openswarm` | Global config directory |
| `OPENSWARM_LOG_LEVEL` | `INFO` | Log level |

## License

MIT
