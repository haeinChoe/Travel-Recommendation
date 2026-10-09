# Herdr MCP bridge

This repository provides a small stdio MCP server that you register in your user-level Codex config (`~/.codex/config.toml`). It uses only Python's standard library and the installed `herdr` CLI. User-level registration keeps machine-specific paths out of version control.

The bridge exposes three no-argument, read-only tools:

- `herdr_server_status` — server status and version fields.
- `herdr_workspace_list` — workspace IDs, labels, and focused state.
- `herdr_agent_list` — agent name, lifecycle status, and pane/workspace/tab IDs.

It invokes only fixed `herdr` argument arrays, sets `HERDR_ENV=1`, uses an eight-second timeout, and filters CLI output to those fields. It does not accept arbitrary commands, arguments, raw socket requests, or pane controls. It does not change sandbox permissions.

All tools accept no arguments. The two list tools return an object with an `items` array in both MCP `structuredContent` and the JSON text content; the status tool returns its filtered fields as an object.

## Setup and use

Install Herdr and Python 3. Add an MCP entry to `~/.codex/config.toml`, replacing both paths with the absolute path to your checkout:

```toml
[mcp_servers.herdr]
command = "python3"
args = ["/absolute/path/to/Travel-Recommendation/scripts/herdr_mcp_server.py"]
cwd = "/absolute/path/to/Travel-Recommendation"
env = { HERDR_ENV = "1" }
```

Restart or reload Codex and inspect `/mcp` to confirm that `herdr` is connected. Ask Codex to call one of the three tools to inspect the local Herdr session. The MCP process inherits its environment and explicitly sets `HERDR_ENV=1` for each Herdr CLI call. User-level settings apply to your Codex sessions across projects, so keep the script and working-directory paths pointed at a checkout that remains available.

## Troubleshooting

- **Herdr CLI not found:** make sure `herdr` is installed and available on the MCP process's `PATH`.
- **Herdr server unavailable:** start or attach to a Herdr session, then retry.
- **`EPERM` / `Operation not permitted`:** the sandbox denied access to Herdr's local socket. Confirm `HERDR_ENV=1`, then run `herdr status server` and `herdr workspace list` from the same sandbox context to diagnose. If they also return `EPERM`, the MCP bridge cannot fix that policy restriction; use a runtime context whose existing policy permits the socket or ask the environment administrator to assess the policy. Do not disable the sandbox or grant broader socket access.
- **Timeout:** check that the local Herdr server is responsive and retry; each CLI call is bounded to eight seconds.

Current implementation environment: Herdr v0.8.2 is installed and `HERDR_ENV=1` is set. A direct `herdr status server` command from the Codex shell returned `Operation not permitted`. After registering the bridge in the user-level config, a fresh read-only Codex session successfully called all three tools, including server status and both lists. This confirms that the MCP route can reach Herdr in this runtime; it does not change the direct shell command's sandbox permissions.
