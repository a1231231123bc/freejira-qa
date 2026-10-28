# Pairing with the Sites edition

Use Node.js 24+. The Site owner obtains service access through the supported Sites tooling. Never include service credentials in a public issue, commit, shell argument or screenshot.

1. Run `node mcp/connector.mjs configure`. Through its hidden stdin, provide a JSON object with `siteUrl` (your HTTPS Site origin) and `siteAccessToken` (your Site service credential).
2. Run `node mcp/connector.mjs pair "QA worker"`.
3. Open the returned approval URL while signed into Freejira. Verify the connection name/code and approve task access.
4. Run `node mcp/connector.mjs finish`, then `node mcp/connector.mjs check`.
5. Set the absolute Node and adapter paths in the QA config's `mcp.command`, ending with `stdio`.

The adapter saves credentials at `~/.config/freejira/mcp.json`, directory mode 0700 and file mode 0600. `FREEJIRA_MCP_CONFIG` overrides its path. The token gives workspace task access as the approving member. Revoke it under **MCP и AI**; re-pair when it expires. Service access and the app token are both needed. No new port is opened on the worker.

For migration, pair the new worker separately or transfer an existing credential file over an authenticated encrypted channel, preserving permissions. Never transfer credentials through Git. Stop the old worker before starting the new one; the connector can remain installed for other MCP clients.

The adapter uses `/api/mcp/rpc`. The platform's `/mcp` route is for native Sites OAuth clients. See Freejira's Sites documentation for the distinction.
