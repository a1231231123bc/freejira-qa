#!/usr/bin/env node
// Standalone stdio adapter: no packages, no local database, no inbound network port.
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
const configFile = process.env.FREEJIRA_MCP_CONFIG || path.join(os.homedir(), '.config/freejira/mcp.json');
const mode = process.argv[2] || 'stdio';
async function save(config) {
  await fs.mkdir(path.dirname(configFile), { recursive: true, mode: 0o700 });
  const tmp = `${configFile}.${process.pid}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(config, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
  await fs.rename(tmp, configFile);
}
async function readConfig() {
  let config;
  try { config = JSON.parse(await fs.readFile(configFile, 'utf8')); } catch { throw new Error('Cannot read Freejira configuration. Run setup again.'); }
  const url = new URL(config.siteUrl);
  if (url.protocol !== 'https:' && !['127.0.0.1', 'localhost'].includes(url.hostname)) throw new Error('Freejira requires HTTPS');
  if (url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new Error('Expected a Site origin, not a task URL');
  return config;
}
async function request(config, pathname, method, body, token = config.token) {
  const res = await fetch(new URL(pathname, config.siteUrl), {
    method, redirect: 'error', signal: AbortSignal.timeout(60_000),
    headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream',
      ...(config.siteAccessToken ? { 'OAI-Sites-Authorization': `Bearer ${config.siteAccessToken}` } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}), },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(res.status === 401 || res.status === 403 ? 'Freejira access denied. Check MCP и AI on the Site, then pair this computer again.' : `Freejira HTTP ${res.status}. Request not retried; re-read the task before repeating a write.`);
  if (res.status === 204) return null;
  if (!res.headers.get('content-type')?.includes('application/json')) throw new Error('Freejira returned a sign-in page or an unsupported response. Check Site service access.');
  return res.json();
}
async function hiddenInput() {
  if (process.stdin.isTTY) process.stdin.setRawMode(true);
  process.stderr.write('Ready for connection JSON on stdin (input is hidden).\n');
  return new Promise((resolve, reject) => {
    let input = '';
    const onData = chunk => { input += chunk.toString(); if (input.includes('\u0003')) reject(new Error('Cancelled')); if (input.includes('\n') || input.includes('\r')) { process.stdin.off('data', onData); if (process.stdin.isTTY) process.stdin.setRawMode(false); process.stdin.pause(); try { resolve(JSON.parse(input.trim())); } catch { reject(new Error('Invalid connection JSON')); } } };
    process.stdin.on('data', onData); process.stdin.resume();
  });
}
try {
  if (mode === 'configure') {
    const input = await hiddenInput();
    if (typeof input.siteUrl !== 'string' || typeof input.siteAccessToken !== 'string' || !input.siteAccessToken) throw new Error('Site origin and service access are required');
    const origin = new URL(input.siteUrl);
    if (origin.protocol !== 'https:' || origin.origin + '/' !== origin.href) throw new Error('Expected an HTTPS Site origin');
    const existing = await fs.readFile(configFile, 'utf8').then(JSON.parse).catch(e => { if (e.code === 'ENOENT') return {}; throw e; });
    if (existing.siteUrl && existing.siteUrl !== input.siteUrl) throw new Error('A different Freejira Site is already configured');
    await save({ ...existing, siteUrl: input.siteUrl, siteAccessToken: input.siteAccessToken });
    await readConfig();
    console.log('Protected Freejira configuration saved.');
  } else {
    let config = await readConfig();
    // First pairing becomes usable automatically once the user approves on the Site.
    if (['stdio', 'check'].includes(mode) && !config.token && config.pendingToken) {
      const status = await request(config, '/api/mcp/connect/status', 'GET', undefined, config.pendingToken);
      if (status.status !== 'connected') throw new Error('Approve the connection in Freejira, then restart Claude Code');
      const { pendingToken, pendingId, ...rest } = config;
      config = { ...rest, token: pendingToken, connectionId: status.id };
      await save(config);
    }
    if (mode === 'pair') {
      const name = process.argv[3] || `Claude Code · ${os.hostname()}`;
      const data = await request(config, '/api/mcp/connect/request', 'POST', { name, scope: 'tasks' }, null);
      await save({ ...config, pendingToken: data.token, pendingId: data.id });
      console.log(JSON.stringify({ approvalUrl: new URL(data.approval_path, config.siteUrl).href, code: data.id.slice(0, 8), expiresAt: data.pair_expires_at }));
    } else if (mode === 'finish') {
      if (!config.pendingToken) throw new Error('Run pair first');
      const result = await request(config, '/api/mcp/connect/status', 'GET', undefined, config.pendingToken);
      if (result.status !== 'connected') throw new Error('Approve the connection in Freejira first');
      const { pendingToken, pendingId, ...rest } = config;
      await save({ ...rest, token: pendingToken, connectionId: result.id });
      console.log(JSON.stringify(result));
    } else if (mode === 'check') {
      const status = await request(config, '/api/mcp/connect/status', 'GET');
      const tools = await request(config, '/api/mcp/rpc', 'POST', { jsonrpc: '2.0', id: 1, method: 'tools/list' });
      const projects = await request(config, '/api/mcp/rpc', 'POST', { jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'list_projects', arguments: {} } });
      if (projects.result?.isError || projects.error) throw new Error('Cannot read Freejira projects');
      console.log(JSON.stringify({ ...status, tools: tools.result.tools.map(t => t.name), projects: JSON.parse(projects.result.content[0].text).map(p => ({ name: p.name, key: p.key })) }));
    } else if (mode === 'stdio') {
      if (!config.token) throw new Error('Freejira is not paired yet');
      const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
      for await (const line of lines) {
        if (!line.trim()) continue;
        let input;
        try {
          if (line.length > 131072) throw new Error('MCP request too large');
          input = JSON.parse(line);
          const result = await request(config, '/api/mcp/rpc', 'POST', input);
          if (input.id !== undefined && result) process.stdout.write(JSON.stringify(result) + '\n');
        } catch (error) {
          // Never log request bodies, credentials, response bodies or headers.
          if (input?.id !== undefined) process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: input.id, error: { code: -32001, message: error instanceof Error && !/fetch failed|redirect/i.test(error.message) ? error.message : 'Freejira connection failed. No automatic retry was performed.' } }) + '\n');
          else process.stderr.write('Freejira: invalid request or connection unavailable.\n');
        }
      }
    } else throw new Error('Usage: connector.mjs [configure|pair|finish|check|stdio]');
  }
} catch (error) { process.stderr.write(`Freejira: ${error.message}\n`); process.exitCode = 1; }
