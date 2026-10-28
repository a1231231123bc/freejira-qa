"""Configuration is loaded explicitly; importing modules never reads private files."""
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID


def defaults():
    return {
        "data_dir": "~/.local/state/freejira-qa",
        "work_dir": "~/.cache/freejira-qa/worktrees",
        "ollama_url": "http://127.0.0.1:11434",
        "model": "qwen3.6:27b", "num_ctx": 32768, "max_diff_chars": 40000,
        "columns": {"pass": None, "fail": None, "unsure": None},
        "poll_seconds": 30, "retry_seconds": 120, "keep_worktree": False,
        "projects": {}, "mcp": {},
    }


def validate(config):
    command = config.get("mcp", {}).get("command")
    if not isinstance(command, list) or not command or not all(isinstance(s, str) and s for s in command):
        raise ValueError("mcp.command must be a non-empty array of strings")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in config["mcp"].get("env", {}).items()):
        raise ValueError("mcp.env values must be strings")
    if urlparse(config["ollama_url"]).scheme not in {"http", "https"}:
        raise ValueError("ollama_url must be an HTTP(S) URL")
    for key in ("poll_seconds", "retry_seconds", "num_ctx", "max_diff_chars"):
        if not isinstance(config[key], int) or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    for outcome, status in config["columns"].items():
        if outcome not in {"pass", "fail", "unsure"} or status not in {None, "backlog", "todo", "doing", "review", "done"}:
            raise ValueError("Invalid columns mapping")
    if not config["projects"]:
        raise ValueError("Configure at least one project")
    for key, project in config["projects"].items():
        if not re.fullmatch(r"[A-Z][A-Z0-9]{1,7}", key):
            raise ValueError("Invalid project key")
        for field in ("name", "freejira_project_id", "repo_path", "github_repo", "about"):
            if not isinstance(project.get(field), str) or not project[field]:
                raise ValueError(f"{key}.{field} is required")
        UUID(project["freejira_project_id"])
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", project["github_repo"]):
            raise ValueError(f"{key}.github_repo must be owner/repository")
        for flag in ("trusted", "allow_forks"):
            if not isinstance(project.get(flag, False), bool):
                raise ValueError(f"{key}.{flag} must be a boolean")
        if not isinstance(project.get("steps"), list):
            raise ValueError(f"{key}.steps must be a list")
        for step in project["steps"]:
            if not isinstance(step.get("name"), str) or not isinstance(step.get("run"), str):
                raise ValueError(f"{key}: each step needs name and run")
            if not isinstance(step.get("timeout", 900), int) or step.get("timeout", 900) < 1:
                raise ValueError(f"{key}: step timeout must be positive")
    tunnel = config.get("ssh_tunnel")
    if tunnel and not all(isinstance(tunnel.get(k), str) and tunnel[k] for k in ("host", "forward")):
        raise ValueError("ssh_tunnel requires host and forward")
    return config


def load_config(path=None):
    path = Path(path or os.environ.get("FREEJIRA_QA_CONFIG", "~/.config/freejira-qa/config.json")).expanduser()
    try:
        config = defaults()
        config.update(json.loads(path.read_text()))
        return validate(config)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise SystemExit(f"Cannot load QA configuration {path}: {error}. See config.example.json.") from None
