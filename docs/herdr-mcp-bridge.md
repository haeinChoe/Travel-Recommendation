# Herdr MCP bridge

This repository provides a small stdio MCP server that you register in your user-level Codex config (`~/.codex/config.toml`). It uses only Python's standard library and the installed `herdr` CLI. User-level registration keeps machine-specific paths out of version control.

The bridge exposes three no-argument, read-only tools:

- `herdr_server_status` — server status and version fields.
- `herdr_workspace_list` — workspace IDs, labels, and focused state.
- `herdr_agent_list` — agent name, lifecycle status, and pane/workspace/tab IDs.

It invokes only fixed `herdr` argument arrays, sets `HERDR_ENV=1`, uses an eight-second timeout, and filters CLI output to those fields. It does not accept arbitrary commands, arguments, raw socket requests, or pane controls. It does not change sandbox permissions. Treat the local MCP tool surface as a separate capability surface from direct shell commands; any future write or mutation tools would need separate authorization-boundary and input-validation design and review.

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
- **`EPERM` / `Operation not permitted`:** a direct Codex shell call failing to access Herdr's socket does not establish whether the registered local MCP bridge can access it. Test direct shell commands and each MCP tool separately from a fresh Codex session. If MCP calls also fail, diagnose the MCP execution path from its returned error, and confirm `HERDR_ENV=1` and that the Herdr server is available. Do not infer that MCP registration changed or bypassed the direct shell sandbox policy.
- **Timeout:** check that the local Herdr server is responsive and retry; each CLI call is bounded to eight seconds.

Current implementation environment: Herdr v0.8.2 is installed and `HERDR_ENV=1` is set. A direct `herdr status server` command from the Codex shell returned `Operation not permitted` / `EPERM`. In a fresh Codex session with the bridge registered through the user-level config, `herdr_server_status`, `herdr_workspace_list`, and `herdr_agent_list` each succeeded. This local result means socket access must be checked separately through the direct shell and local MCP paths. It does not establish internal sandbox details or mean MCP registration changed the direct shell's sandbox settings.
