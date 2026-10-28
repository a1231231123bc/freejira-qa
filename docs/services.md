# Always-on service

First complete pairing, configure repository clones and run `freejira-qa-service --inspect` and a dry-run as the service user. Keep the virtual environment and repository at stable absolute paths. Do not run foreground and background workers together. Re-run `pip install .` inside the venv after updating source, while the service is stopped.

## macOS / Apple Silicon

```sh
.venv/bin/python scripts/install_macos.py --config ~/.config/freejira-qa/config.json
```

The installer uses the selected Python interpreter, captures PATH, writes a user LaunchAgent and starts it. It refuses to overwrite an existing service. Logs and status are in the configured data directory. It uses `caffeinate -i` while running; manual sleep, lid close and power loss can still stop it. A LaunchAgent starts after its user logs in, not at the FileVault pre-login screen.

```sh
launchctl print gui/$(id -u)/com.freejira.qa-agent
launchctl bootout gui/$(id -u)/com.freejira.qa-agent
# Restart an existing installation:
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.freejira.qa-agent.plist
```

To uninstall, boot out the service and remove only its plist. Leave private configuration/state in place unless you deliberately want to delete them.

## Linux / systemd user service

Copy `examples/freejira-qa.service` into `~/.config/systemd/user/`, replacing the Python and config paths. Set PATH to include your project's package manager if needed. Then:

```sh
systemctl --user daemon-reload
systemctl --user enable --now freejira-qa
systemctl --user status freejira-qa
journalctl --user -u freejira-qa
```

For a user service to survive logout, enable user lingering using your distribution's administrative procedure. Use `systemctl --user disable --now freejira-qa` before removal. Do not grant the worker root access.

## Move to another machine

1. Install runtimes, GitHub CLI, Ollama, the desired model, QA package and project toolchains on the target.
2. Authenticate GitHub there, clone each allowed repository and configure Freejira MCP.
3. Copy private configuration over SSH, then update paths and set `ollama_url` to `http://127.0.0.1:11434` when the model runs on that same machine. No SSH model tunnel is then needed.
4. Inspect connectivity and run a dry-run on the target.
5. Stop and disable automatic startup on the old host. Transfer the latest state directory privately to preserve fingerprints and pending publications. Keep a backup for rollback.
6. Start the target service and verify `service-status.json` plus the next QA run. Do not have both hosts polling with publication enabled.

For rollback, stop the new instance first, transfer its latest state back and re-enable the old service. Reports, credentials and state never belong in either public repository.

## Optional SSH model tunnel

Only if Ollama is on a third machine, set `ssh_tunnel` to `{"host":"user@model-host","forward":"127.0.0.1:11435:127.0.0.1:11434"}` and `ollama_url` to `http://127.0.0.1:11435`. Set up and verify SSH host keys first; batch mode never asks for passwords. Direct local Ollama is the default.
