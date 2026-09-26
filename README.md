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
openswarm run "Build user auth API"
```

Senior breaks it down, delegates to Junior, reviews results, assembles the final output. One command.

## Install

```bash
pipx install "openswarm-ai[mcp]"
```

Installs the `openswarm` CLI and the `openswarm-mcp` server. [Get pipx](https://pipx.pypa.io/stable/how-to/install-pipx/) if you don't have it.

## Get started

```bash
cd your-project
openswarm init      # writes team.yaml — pick a layout when prompted
openswarm doctor    # checks config, keys, and providers before you spend anything
openswarm run "Add a health check endpoint"
```

`init` templates: `hierarchical` (lead + worker), `pipeline` (A → B → C), `collaborative` (discuss → consensus), and `local` (two Ollama models, no API keys). See them with `openswarm init --list-templates`.

## Use it from your IDE

```bash
claude mcp add openswarm -- openswarm-mcp     # Claude Code
```

Drop a `team.yaml` in your project and your IDE delegates coding tasks to the team automatically. If a task is outside the team's scope, the lead says so and your IDE handles it directly.

<details>
<summary>Cursor, Windsurf, Copilot, OpenCode</summary>

Any MCP client works — register `openswarm-mcp` as a command-type server.

- **Cursor** — Settings → MCP → Add new MCP server, command `openswarm-mcp`
- **Windsurf** — add to `~/.codeium/windsurf/mcp_config.json`
- **Copilot** — add to VS Code `settings.json` under `github.copilot.chat.mcp.servers`
- **OpenCode** — add to `opencode.json` under `mcp`

```json
{ "mcpServers": { "openswarm": { "command": "openswarm-mcp", "args": [] } } }
```

Tools: `openswarm_run(task, team?)`, `openswarm_teams()`, `openswarm_team_info(team)`.
</details>

## CLI

```bash
openswarm run "task"              # uses the project's team.yaml
openswarm interactive             # REPL session with the team
openswarm team list               # all teams, local and global
openswarm run "task" -q > out.md  # result only, for pipes
```

| Flag | Purpose |
|------|---------|
| `-c, --config PATH` · `-t, --team NAME` | Pick a config explicitly |
| `-v` · `-s` · `-q` · `-o FILE` | Verbose · stream · quiet · write to file |
| `--max-rounds N` · `--no-tools` | Cap rounds · stop agents touching files |

With no `-c`/`-t`, OpenSwarm uses the project's single team config; if several exist it lists them rather than guessing.

**Interactive mode** renders markdown, streams answers, and keeps history between sessions. `@file` attaches a file to your task, `!cmd` runs a shell command, and `/help` lists the rest. You can keep typing while the team works — lines are queued and run when the turn ends. When an agent needs details, its questions become a menu you pick from rather than prose you retype.

## Agents acting on your workspace

Agents can write files and run commands — **every action asks first**:

```
Write utils.py (14 lines)
  | def slugify(text: str) -> str:
  |     ...

 > Yes
   Yes, and don't ask again for write_file this session
   No, and tell the agent what to do instead
   No
```

↑/↓ and Enter, or press the number. Writes cannot leave the working directory, even if you approve them. Sessions with nobody to ask — pipes, automation, the MCP server — get no tools at all. Opt out entirely with `--no-tools`.

This is an approval gate, not a sandbox: approving `rm -rf` still runs it.

## Team config

```yaml
team:
  name: "backend-team"
  goal: "Build and maintain backend services"
  workflow: hierarchical     # or pipeline, collaborative
  lead: "senior"             # hierarchical only
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
```

| Field | Default | Notes |
|-------|---------|-------|
| `name` · `role` · `model` · `host` · `api_key` | required | `api_key` supports `${VAR}` and `${VAR:-fallback}` |
| `max_tokens` | `4096` | Reasoning models need room to think before answering |
| `temperature` | `0.7` | 0.0–2.0 |
| `max_history` | `40` | Messages kept per agent |
| `rules` | `[]` | Behaviour rules |

Any model litellm supports works — Claude, GPT, DeepSeek, Mistral, Llama, Ollama, or your own gateway. If litellm can't infer the provider from a model name, prefix it with `openai/`.

Configs are discovered from `team.yaml` / `openswarm.yaml` in the project, `openswarm/*.yaml`, then `~/.openswarm/teams/`.

## Workflows

| Type | How it works | Best for |
|------|-------------|----------|
| **hierarchical** | Lead delegates, reviews, assembles | Dev teams, review cycles |
| **pipeline** | A → B → C, each transforms the output | Content, data processing |
| **collaborative** | All discuss, moderator synthesizes | Decisions, brainstorming |

## Cost

Every run prints tokens per agent, with cost when the provider reports pricing.

| "Build user auth API" | Tokens | Cost |
|---|---|---|
| Sonnet does everything | ~28,000 | ~$0.109 |
| Sonnet decides, DeepSeek builds | ~25,000 | ~$0.034 |

The expensive model handles ~20% of tokens but makes the decisions that matter.

## Reliability

Retries transient errors, reports the rest with a hint at what to check. One provider going down doesn't kill a run — the lead routes around it. Config problems name the file and field. `openswarm doctor` catches all of it before you spend a token.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENSWARM_CONFIG_DIR` | `~/.openswarm` | Global config directory |
| `OPENSWARM_LOG_LEVEL` | `WARNING` | Log level |

Full history in [CHANGELOG.md](CHANGELOG.md).

## License

MIT
