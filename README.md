# Freejira QA

[![CI](https://github.com/a1231231123bc/freejira-qa/actions/workflows/ci.yml/badge.svg)](https://github.com/a1231231123bc/freejira-qa/actions/workflows/ci.yml) · [MIT](LICENSE) · [Русская инструкция](README.ru.md)

An optional, always-on QA worker for [Freejira](https://github.com/a1231231123bc/freejira). When a task enters **review**, it finds the associated GitHub pull request, runs configured checks in a detached worktree, asks Ollama to compare the diff with the task, and posts a report.

**Early release.** A report is evidence for a reviewer, not proof of correctness. Task columns stay unchanged by default. The worker neither merges PRs nor deploys applications.

## How it works

1. Poll configured projects every 30 seconds while idle; process tasks sequentially.
2. Find a PR from a task comment URL, or the task key in its title/branch.
3. Read the diff and CI results; run trusted repository checks at the PR commit.
4. Ask an Ollama model for a structured assessment of the acceptance criteria.
5. Recheck task revision and PR head before publishing a comment.

State survives restarts. A task revision, PR commit or CI change triggers another check. Backoff handles temporary failures. Publication markers recover interrupted writes without duplicating the same report. A process lock prevents two workers sharing a data directory. There is no distributed lock: run only one worker per workspace.

## Requirements

- macOS or Linux, Python 3.10+, Git and authenticated GitHub CLI (`gh`).
- Ollama with an installed model that supports structured JSON output. The example uses `qwen3.6:27b`; choose a model that fits your hardware.
- Freejira MCP access and Node.js 24+ for its stdio bridge.
- A dedicated clone and each project's test dependencies (npm/pnpm, databases, browsers, etc.). The worker does not provision application infrastructure.

There are no Python runtime packages. Windows is not supported (POSIX process groups and file locks are used). Ollama is accessed directly on loopback by default. Tasks and diffs go to the configured model endpoint; keep it local if they must remain on the worker.

## Install

```sh
git clone https://github.com/a1231231123bc/freejira-qa.git
cd freejira-qa
python3 -m venv .venv
.venv/bin/python -m pip install .
mkdir -p ~/.config/freejira-qa
chmod 700 ~/.config/freejira-qa
cp config.example.json ~/.config/freejira-qa/config.json
chmod 600 ~/.config/freejira-qa/config.json
```

Edit that private configuration: set your project key/UUID, repository path, `owner/repo`, test commands, model and MCP command. Use absolute paths in service commands. Authenticate `gh` as the service user, clone repositories using a matching GitHub identity, and pull the chosen Ollama model. Avoid production credentials on the worker.

**Repository code execution is disabled by default.** Set a project's `trusted: true` only for repositories and contributors you trust. Fork PRs are still blocked unless `allow_forks: true`. Test and install scripts execute with the worker user's privileges; a git worktree is not a sandbox. Use a dedicated machine/account for trusted team repositories and isolated disposable workers for untrusted contributions. See [security boundaries](docs/security-boundaries.md).

### Connect Freejira

**Sites edition:** follow [pairing instructions](docs/mcp.md). The included `mcp/connector.mjs` uses a protected credentials file. Set its absolute path in `mcp.command`.

**Self-hosted edition:** set `mcp.command` to the existing Freejira stdio bridge:

```json
{
  "mcp": {
    "command": ["/absolute/path/to/node", "--import", "/absolute/path/to/freejira/node_modules/tsx/dist/loader.mjs", "/absolute/path/to/freejira/server/stdio.ts"],
    "env": {"FREEJIRA_URL": "http://localhost:4173", "FREEJIRA_TOKEN": "YOUR_PRIVATE_TOKEN"}
  }
}
```

This is a fragment of the private config, not a replacement for the entire file. Use a token that can read tasks and add comments. The service user must be able to access both the MCP bridge and the network endpoint. No inbound worker port is needed.

### Inspect, dry-run, then start

```sh
.venv/bin/freejira-qa-service --inspect
.venv/bin/freejira-qa --task DEMO-1
.venv/bin/freejira-qa --task DEMO-1 --apply
.venv/bin/freejira-qa-service
```

`--inspect` reads connectivity and counts review tasks; it does not execute checks or publish. A normal one-shot run executes configured checks and saves a local report, but only `--apply` writes to Freejira. The service publishes automatically. Stop foreground mode with Ctrl+C. `--config /path/config.json` or `FREEJIRA_QA_CONFIG` selects another configuration.

For unattended startup and migration to a separate Mac or Linux machine, see [service setup](docs/services.md). That machine needs its own credentials, repository clones, dependencies, Ollama and internet. Your laptop can then be off. After a Mac reboot, a LaunchAgent starts when its user logs in.

## Results and storage

`pass` requires successful local checks, confirmed CI success, covered criteria and no unresolved model concerns. Missing/pending CI, no local checks, truncated context or uncertainty cannot produce a pass. Failed checks are reported without inventing their root cause. Configure `columns` only if you explicitly want status transitions; all three outcomes default to `null`.

Private state, rotating logs and reports: `~/.local/state/freejira-qa`. Temporary checkouts: `~/.cache/freejira-qa/worktrees`. Both locations are configurable. Reports may contain source code and test output; keep them private. Back up configuration and state, keep restrictive permissions, and stop the worker before moving them.

Polling does not capture every rapid transition: a task that enters and leaves review between polls may not be processed. Native browser QA, deployment verification and production database checks require explicit project steps; they are not automatic. Model quality and available memory affect runtime and results.

## Development

```sh
python3 -m unittest discover -p 'test_*.py' -v
python3 -m pip install .
freejira-qa --help
freejira-qa-service --help
```

Tests use fake MCP processes and synthetic tasks; they need neither credentials nor Ollama. CI runs on Linux and macOS with Python 3.10 and 3.13. [Contributions](CONTRIBUTING.md) and [private security reports](SECURITY.md) are welcome. Original project code is [MIT licensed](LICENSE); model weights are not included.
