"""Install the current venv as a per-user LaunchAgent; never copy credentials."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="~/.config/freejira-qa/config.json")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Use the systemd example on Linux")
    from qa_config import load_config
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    config_path.chmod(0o600)
    data = Path(config["data_dir"]).expanduser().resolve()
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    label = "com.freejira.qa-agent"
    plist = Path.home() / "Library/LaunchAgents" / (label + ".plist")
    if plist.exists():
        parser.error(f"Existing service at {plist}; stop it and preserve its config/state before replacing it")
    value = {
        "Label": label,
        "ProgramArguments": ["/usr/bin/caffeinate", "-i", sys.executable, "-u", "-m", "service", "--config", str(config_path)],
        "WorkingDirectory": str(data), "RunAtLoad": True, "KeepAlive": True,
        "ThrottleInterval": 30, "ProcessType": "Background",
        "EnvironmentVariables": {"PATH": os.environ["PATH"], "PYTHONUNBUFFERED": "1", "GIT_TERMINAL_PROMPT": "0"},
        "StandardOutPath": str(data / "launchd.log"), "StandardErrorPath": str(data / "launchd.log"),
    }
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(plistlib.dumps(value))
    plist.chmod(0o600)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)], check=True)
    print(f"Started {label}; state: {data}")


if __name__ == "__main__":
    main()
