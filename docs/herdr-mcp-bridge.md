# Herdr MCP bridge

This repository provides a small stdio MCP server that you register in your user-level Codex config (`~/.codex/config.toml`). It uses Python's standard library, Git for read-only worktree checks, and the installed `herdr` CLI. User-level registration keeps machine-specific paths out of version control.

The bridge exposes three no-argument, read-only tools and two narrowly scoped teardown tools:

- `herdr_server_status` — server status and version fields.
- `herdr_workspace_list` — workspace IDs, labels, and focused state.
- `herdr_agent_list` — agent name, lifecycle status, and pane/workspace/tab IDs.
- `herdr_worktree_remove(workspace_id)` — removes one clean Herdr-linked Git worktree without force.
- `herdr_workspace_close(workspace_id)` — closes one eligible plain-checkout workspace with verified caller and primary-checkout ownership, using Herdr 0.9.0+'s guarded single-ID close.

The teardown input schema requires exactly one string `workspace_id` and rejects extra properties. The bridge invokes fixed `herdr` argument arrays, sets `HERDR_ENV=1`, and uses an eight-second timeout. It does not accept arbitrary commands, arguments, raw socket requests, force options, arbitrary paths, or pane controls. It does not change sandbox permissions. Treat the local MCP tool surface as a separate capability surface from direct shell commands.

The read-only list tools return an object with an `items` array in both MCP `structuredContent` and JSON text content; the status tool returns its filtered fields as an object. Successful teardown results identify the requested workspace and report whether removal/closure occurred or the target was already absent.

## Teardown safety boundary

Before either mutation, the bridge requires a syntactically valid `HERDR_WORKSPACE_ID` that appears exactly once in the current Herdr workspace inventory. Missing, stale, or ambiguous caller identity fails before agent/worktree inspection or mutation. It then reads the Herdr workspace and agent inventories and refuses a focused/current target or a target with an agent that is `working`, `blocked`, or `unknown` (missing or unrecognized agent status also fails closed). Worktree removal requires exactly one Herdr record linking the requested workspace to a linked checkout. Git must confirm the returned absolute path and branch, the branch cannot be `dev` or `main`, and the checkout must have no tracked changes, untracked files, or ignored files. The bridge omits `--force` from the fixed `herdr worktree remove --workspace <ID>` invocation.

Workspace close refuses the caller's workspace, a focused target, a target with an unsettled agent, a linked-worktree workspace, and a target that owns a linked checkout. The target must have valid plain-checkout provenance, and the primary checkout owner must be unambiguous. A secondary plain workspace may share that checkout; after closing its exact workspace ID, the bridge verifies that the primary owner and checkout record remain. For every present target, the bridge requires a running Herdr server version of 0.9.0 or newer; older or unrecognized versions fail closed before worktree inspection or mutation. Newer Herdr versions require explicit group intent before closing a primary workspace and its linked workspaces. The bridge always invokes exactly `herdr workspace close <ID>` and never passes group intent. If Herdr returns `workspace_group_close_required`, the bridge reports that refusal without retrying. A linked row explicitly owned by the target blocks close locally. For rows without owner IDs, a unique workspace checkout-path match establishes ownership and blocks close if it identifies the target; duplicate path matches fail closed. An unmapped ownerless row blocks closing its primary workspace, but is tolerated for a secondary target; post-close readback verifies that peer workspaces, the primary owner, Git worktree listings, and checkout statuses remain unchanged. A missing target is returned as an explicit `already_absent` no-op.

If a CLI call fails, times out, or readback does not prove the postcondition, the tool returns an MCP error. Do not repeat the mutation through a shell, force-remove a checkout, or switch to another workspace. Preserve state and report the IDs, observed status, and error. A teardown MCP tool being unavailable or refusing an operation is not authorization to bypass the MCP boundary.

## Setup and use

Install Herdr and Python 3. Add an MCP entry to `~/.codex/config.toml`, replacing both paths with the absolute path to your checkout:

```toml
[mcp_servers.herdr]
command = "python3"
args = ["/absolute/path/to/Travel-Recommendation/scripts/herdr_mcp_server.py"]
cwd = "/absolute/path/to/Travel-Recommendation"
env = { HERDR_ENV = "1" }
env_vars = ["HERDR_WORKSPACE_ID"]
```

`env_vars` forwards the value of `HERDR_WORKSPACE_ID` from the Herdr-managed Codex process that launches this stdio server. It names the variable to forward; do not set a literal workspace ID in this config. Restart or reload Codex from the active caller workspace and inspect `/mcp` to confirm that `herdr` is connected. A previously launched stdio process keeps its old environment: if its workspace ID is stale, teardown fails closed even when a different workspace is focused now. The bridge does not guess caller identity from focus. Ask Codex to call the read-only status and workspace tools to inspect the local Herdr session before retrying cleanup. The MCP process explicitly sets `HERDR_ENV=1` for each Herdr CLI call. User-level settings apply to your Codex sessions across projects, so keep the script and working-directory paths pointed at a checkout that remains available.

## Troubleshooting

- **Herdr CLI not found:** make sure `herdr` is installed and available on the MCP process's `PATH`.
- **Herdr server unavailable:** start or attach to a Herdr session, then retry.
- **Stale caller identity:** check that `env_vars = ["HERDR_WORKSPACE_ID"]` is present, then reload the registered MCP server from the intended caller workspace. Confirm its workspace is present in `herdr_workspace_list`; do not replace the forwarded value with a fixed ID.
- **Workspace close refused:** confirm the running Herdr server reports version 0.9.0 or newer. The bridge sends one workspace ID and never requests a group close. If Herdr reports `workspace_group_close_required`, preserve all workspaces and linked worktrees; do not retry with group intent. A linked checkout explicitly owned by the target also blocks close locally.
- **`EPERM` / `Operation not permitted`:** a direct Codex shell call failing to access Herdr's socket does not establish whether the registered local MCP bridge can access it. Test direct shell commands and each MCP tool separately from a fresh Codex session. If MCP calls also fail, diagnose the MCP execution path from its returned error, and confirm `HERDR_ENV=1` and that the Herdr server is available. Do not infer that MCP registration changed or bypassed the direct shell sandbox policy.
- **Timeout:** check that the local Herdr server is responsive and retry; each CLI call is bounded to eight seconds.

The bridge reads the running server version from `herdr status server --json` before closing any present workspace. It invokes only `herdr workspace close <ID>`; it never supplies a group-close option. Worktree removal uses the fixed `herdr worktree remove --workspace <ID>` command and never supplies `--force`. Socket access must be checked separately through the direct shell and local MCP paths. A direct shell `EPERM` does not establish internal sandbox details or mean MCP registration changed the direct shell's sandbox settings.

## Regression tests

Run `python3 -m unittest tests.test_herdr_mcp_server` from the repository root. The suite includes an isolated subprocess-level MCP regression test with a temporary Git repository and fake Herdr 0.9.3 CLI. It verifies the bridge sends a single-ID close, preserves Herdr's primary-group refusal, and does not mutate the caller or target. It does not connect to or mutate a user's Herdr session.
