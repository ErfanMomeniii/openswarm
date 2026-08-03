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
