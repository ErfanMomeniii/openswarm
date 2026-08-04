# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/).

## [1.2.0]

Onboarding release — getting from install to a working team no longer requires copying YAML out of the README.

### Added
- `openswarm init` scaffolds a `team.yaml` from four templates (`hierarchical`, `pipeline`, `collaborative`, `local`). Interactive picker on a TTY, flags otherwise; `--global` installs to `~/.openswarm/teams/`.
- `openswarm doctor` validates every discovered config, reports unset environment variables with the exact `export` lines, and shows version/interpreter/MCP-extra/config-dir. `--check-connection` pings each agent's endpoint with a one-token request.
- `openswarm team list` / `openswarm team info` subcommands. The old `team-list` / `team-info` names still work.
- `run` flags: `-q/--quiet` (result only, for pipes), `-o/--output FILE`, `--max-rounds N`, and `-V/--version`.
- Progress spinner naming the agent currently working, shown when not streaming or verbose.
- `${VAR:-default}` syntax in config values, alongside the existing `${VAR}`.
- REPL: `/help`, `/usage` (session-wide tokens and cost), `/save FILE`, `/exit` and `/q` aliases, and slash-command tab completion.
- CI workflow running lint and tests on Python 3.12 and 3.13; publishing is now gated on lint, tests, and a tag/version match.

### Changed
- `run` with no `--config`/`--team` uses the project's single discoverable team config. Several configs → OpenSwarm lists them and asks; it never guesses.
- `--team` resolves project-local configs, not just `~/.openswarm/teams/`. The CLI and the MCP server now share one discovery implementation, so a team name means the same thing in both.
- Unset environment variables are reported together with `export` hints instead of failing on the first one.
- Config errors name the offending field and file: malformed YAML, missing `team:`/`agents:`, unknown workflow type, duplicate agent names, blank fields, `max_rounds < 1`.
- Listing commands load configs without secrets, so `team list` and `team info` work before any API key is exported.
- `-v` no longer enables third-party debug logging; HTTP and provider libraries stay at WARNING so inter-agent messages are readable.

### Fixed
- **One failing provider no longer aborts the whole run.** A worker whose endpoint is down is reported back to the lead, which routes around it or finishes the task itself; an unreachable participant is skipped in collaborative discussions; a failed pipeline stage passes the previous stage's output through. Only a failing lead agent is fatal. This restores the project's "one agent failing doesn't crash the entire team" principle, which the code did not actually implement.
- **`doctor --check-connection` reported working models as broken.** The probe asked for a single token, which makes reasoning models return an empty completion — some gateways turn that into a 502. The probe now leaves room for a short answer and retries once, so a single transient blip no longer fails a healthy config. Any genuine failure is still reported as a problem, with a hint at what to check; OpenSwarm does not try to guess which provider errors are harmless, because gateways return the same status for very different faults.
- **`from openswarm.llm import LLMClient` raised `ImportError`** when it was the first openswarm import, because `openswarm.core` eagerly imported `Agent`, which imports the LLM client, which imports back into `openswarm.core`. `Agent`, `Team`, and `Orchestrator` now resolve lazily. Present since 1.1.0.
- **A `null` completion crashed the run.** Providers return `content: null` for content filters, tool calls, and truncation; downstream string handling then failed. Null content is now an empty string, and a completion with no choices raises a clear error instead of an `IndexError`.
- **Pipeline workflow returned the raw JSON protocol envelope** (`{"action": "result", ...}`) as its result, and passed that envelope to the next agent instead of the content. Agents that reply in plain prose are still passed through unchanged.
- Hitting `max_rounds` in a hierarchical run no longer discards the work: the last agent deliverable is returned alongside the warning.
- Errors and cancellation messages go to stderr, so `openswarm run "..." -q > out.md` never captures them.
- litellm's "Give Feedback / Get Help" banner no longer buries the actual error message.
- Links in generated configs and the README pointed at a non-existent GitHub repository.

## [1.1.0]

### Added
- Streaming output across the LLM client, agents, workflows, and CLI (`--stream`).
- Live token-usage and cost tracking, reported per agent and per model.

## [1.0.0]

- Initial public release: hierarchical, pipeline, and collaborative workflows; YAML team configs; MCP server for IDE integration.
