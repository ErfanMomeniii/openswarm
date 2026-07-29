"""Starter team.yaml templates used by `openswarm init`."""

from __future__ import annotations

HIERARCHICAL = """\
# OpenSwarm team — a smart lead delegates bulk work to a cheap worker.
# Docs: https://github.com/erfamm/openswarm
team:
  name: "{name}"
  goal: "Build and maintain this project"
  workflow: hierarchical
  lead: "senior"
  max_rounds: 10

agents:
  - name: "senior"
    role: senior
    model: claude-sonnet-4-20250514
    host: https://api.anthropic.com
    api_key: ${{ANTHROPIC_API_KEY}}
    max_tokens: 4096
    temperature: 0.7
    rules:
      - "Break the task into subtasks and delegate them to junior"
      - "Review junior's output before marking the task done"
      - "Handle architecture and design decisions yourself"
      - "If the task is outside this team's scope, say so plainly"

  - name: "junior"
    role: junior
    model: deepseek-chat
    host: https://api.deepseek.com/v1
    api_key: ${{DEEPSEEK_API_KEY}}
    max_tokens: 2048
    temperature: 0.3
    rules:
      - "Execute the task assigned by senior"
      - "Ask senior when requirements are unclear"
      - "Write tests for all code you produce"
"""

PIPELINE = """\
# OpenSwarm team — output flows through each agent in order.
# Docs: https://github.com/erfamm/openswarm
team:
  name: "{name}"
  goal: "Draft, edit, and polish written output"
  workflow: pipeline

agents:
  - name: "writer"
    role: writer
    model: deepseek-chat
    host: https://api.deepseek.com/v1
    api_key: ${{DEEPSEEK_API_KEY}}
    max_tokens: 2048
    temperature: 0.8
    rules:
      - "Produce a complete first draft"

  - name: "editor"
    role: editor
    model: deepseek-chat
    host: https://api.deepseek.com/v1
    api_key: ${{DEEPSEEK_API_KEY}}
    max_tokens: 2048
    temperature: 0.4
    rules:
      - "Tighten structure and fix errors, keep the author's intent"

  - name: "reviewer"
    role: reviewer
    model: claude-sonnet-4-20250514
    host: https://api.anthropic.com
    api_key: ${{ANTHROPIC_API_KEY}}
    max_tokens: 4096
    temperature: 0.3
    rules:
      - "Final pass — approve or state exactly what still needs fixing"
"""

COLLABORATIVE = """\
# OpenSwarm team — all agents discuss, first agent moderates and synthesizes.
# Docs: https://github.com/erfamm/openswarm
team:
  name: "{name}"
  goal: "Review proposals and reach a decision"
  workflow: collaborative
  max_rounds: 5

agents:
  - name: "moderator"
    role: architect
    model: claude-sonnet-4-20250514
    host: https://api.anthropic.com
    api_key: ${{ANTHROPIC_API_KEY}}
    max_tokens: 4096
    temperature: 0.5
    rules:
      - "Keep the discussion focused and synthesize the final decision"

  - name: "backend"
    role: backend-specialist
    model: deepseek-chat
    host: https://api.deepseek.com/v1
    api_key: ${{DEEPSEEK_API_KEY}}
    max_tokens: 2048
    temperature: 0.5
    rules:
      - "Argue from data, API, and reliability concerns"

  - name: "frontend"
    role: frontend-specialist
    model: deepseek-chat
    host: https://api.deepseek.com/v1
    api_key: ${{DEEPSEEK_API_KEY}}
    max_tokens: 2048
    temperature: 0.5
    rules:
      - "Argue from UX, accessibility, and client performance concerns"
"""

LOCAL = """\
# OpenSwarm team running fully local models via Ollama.
# Start Ollama first:  ollama serve && ollama pull qwen2.5-coder
team:
  name: "{name}"
  goal: "Build and maintain this project with local models"
  workflow: hierarchical
  lead: "lead"
  max_rounds: 10

agents:
  - name: "lead"
    role: senior
    model: ollama/qwen2.5-coder:14b
    host: ${{OLLAMA_HOST:-http://localhost:11434}}
    api_key: "not-needed"
    max_tokens: 4096
    temperature: 0.7
    rules:
      - "Break the task into subtasks and delegate them to worker"
      - "Review worker's output before marking the task done"

  - name: "worker"
    role: junior
    model: ollama/qwen2.5-coder:7b
    host: ${{OLLAMA_HOST:-http://localhost:11434}}
    api_key: "not-needed"
    max_tokens: 2048
    temperature: 0.3
    rules:
      - "Execute the task assigned by lead"
      - "Write tests for all code you produce"
"""

TEMPLATES: dict[str, str] = {
    "hierarchical": HIERARCHICAL,
    "pipeline": PIPELINE,
    "collaborative": COLLABORATIVE,
    "local": LOCAL,
}

TEMPLATE_DESCRIPTIONS: dict[str, str] = {
    "hierarchical": "Senior lead delegates to a cheap junior, then reviews (recommended)",
    "pipeline": "writer → editor → reviewer, each transforms the previous output",
    "collaborative": "Agents discuss in rounds until consensus, moderator synthesizes",
    "local": "Two Ollama models, no API keys needed",
}


def render(template: str, team_name: str) -> str:
    """Render a named template with the given team name."""
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template '{template}'. Available: {', '.join(TEMPLATES)}")
    return TEMPLATES[template].format(name=team_name)
