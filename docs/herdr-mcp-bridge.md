# Herdr MCP bridge

This repository provides a small stdio MCP server that you register in your user-level Codex config (`~/.codex/config.toml`). It uses Python's standard library, Git for read-only worktree checks, and the installed `herdr` CLI. User-level registration keeps machine-specific paths out of version control.

The bridge exposes three no-argument, read-only tools and two narrowly scoped teardown tools:

- `herdr_server_status` — server status and version fields.
- `herdr_workspace_list` — workspace IDs, labels, and focused state.
- `herdr_agent_list` — agent name, lifecycle status, and pane/workspace/tab IDs.
- `herdr_worktree_remove(workspace_id)` — removes one clean Herdr-linked Git worktree without force.
- `herdr_workspace_close(workspace_id)` — closes one eligible workspace only when the caller and no other workspace share its repository.

The teardown input schema requires exactly one string `workspace_id` and rejects extra properties. The bridge invokes fixed `herdr` argument arrays, sets `HERDR_ENV=1`, and uses an eight-second timeout. It does not accept arbitrary commands, arguments, raw socket requests, force options, arbitrary paths, or pane controls. It does not change sandbox permissions. Treat the local MCP tool surface as a separate capability surface from direct shell commands.

The read-only list tools return an object with an `items` array in both MCP `structuredContent` and JSON text content; the status tool returns its filtered fields as an object. Successful teardown results identify the requested workspace and report whether removal/closure occurred or the target was already absent.

## Teardown safety boundary

Before either mutation, the bridge reads Herdr workspace and agent inventories and refuses a focused/current target or a target with an agent that is `working`, `blocked`, or `unknown` (missing or unrecognized agent status also fails closed). Worktree removal requires exactly one Herdr record linking the requested workspace to a linked checkout. Git must confirm the returned absolute path and branch, the branch cannot be `dev` or `main`, and the checkout must have no tracked changes, untracked files, or ignored files. The bridge omits `--force` from the fixed `herdr worktree remove --workspace <ID>` invocation.

Workspace close requires a valid `HERDR_WORKSPACE_ID` caller context and refuses the caller's workspace. It also refuses a target that shares its primary checkout or Git repository with another Herdr workspace. Every other workspace must expose a valid repository identity; missing, null, malformed, or unknown provenance fails closed because the bridge cannot prove repository exclusivity. This restriction is necessary because a Herdr close request can remove multiple workspace records that share a repository; readback after the command would be too late to protect those sessions. Workspace close also refuses a linked-worktree workspace and any workspace with a linked checkout that it owns. The bridge invokes only `herdr workspace close <ID>` after these checks. After close, it confirms the target record is gone and Git's worktree list and status are unchanged. A missing target is returned as an explicit `already_absent` no-op.

If a CLI call fails, times out, or readback does not prove the postcondition, the tool returns an MCP error. Do not repeat the mutation through a shell, force-remove a checkout, or switch to another workspace. Preserve state and report the IDs, observed status, and error. A teardown MCP tool being unavailable or refusing an operation is not authorization to bypass the MCP boundary.

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

The installed Herdr CLI's local schema identifies workspace focus and attached worktree provenance, agent lifecycle values (`idle`, `working`, `blocked`, `done`, `unknown`), and Git worktree fields including branch, path, linked status, and open workspace ID. Herdr 0.8.2 help confirms removal takes `--workspace <ID>` and supports `--force`; the bridge never supplies the force flag. Socket access must be checked separately through the direct shell and local MCP paths. A direct shell `EPERM` does not establish internal sandbox details or mean MCP registration changed the direct shell's sandbox settings.

## Regression tests

Run `python3 -m unittest tests.test_herdr_mcp_server` from the repository root. The suite includes an isolated subprocess-level MCP regression test with a temporary Git repository and a fake Herdr CLI. The fixture models the observed shared-repository cascade behavior and verifies that the bridge rejects the close before invoking the CLI, preserving both the caller and target workspaces. It does not connect to or mutate a user's Herdr session.
