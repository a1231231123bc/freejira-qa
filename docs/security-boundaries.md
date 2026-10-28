# Execution and data boundaries

This worker is designed for a small team's trusted repositories. Configured shell commands, package lifecycle hooks and tests can execute any code with the worker user's privileges. A detached worktree prevents edits to the main checkout; it does **not** isolate secrets, the network, home directory or operating system.

Execution requires `trusted: true`; cross-repository PRs additionally require `allow_forks: true`. These settings are explicit trust decisions, not an automatic code audit. Keep production credentials off the worker. Use a dedicated OS account/machine and minimal GitHub permissions. For public/untrusted PRs use disposable sandboxed infrastructure; this version does not provide that isolation.

Test subprocesses have common secret-bearing environment variables removed, but can still read files accessible to their user. Use test accounts and test databases. Child process groups are terminated after configured timeouts.

Task text, comments, diff and model output are untrusted data. The model does not choose or execute shell commands; commands come from the operator's configuration. It can still produce incorrect assessments or repeat sensitive content supplied in prompts. Reports include selected test output and are posted to the team workspace. Do not print secrets in tests. Full evidence and raw model output are stored privately on disk.

Only one worker may publish per workspace. The local lock coordinates processes sharing the same data directory, not different hosts. Stop the old instance before migrating. GitHub CI can change while a run is in progress; the worker re-reads it before publication. Freejira revision checks reject stale task edits, but comment creation and revision reads are not one atomic cross-service transaction.

Ollama is local by default; changing its URL changes where task text, diffs and check output are sent. GitHub and Freejira connections remain external network traffic. No telemetry or cloud model provider is configured by this project.
