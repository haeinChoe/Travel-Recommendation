# Herdr implementation and review procedure

Read this reference when running the Issue-to-PR loop.

The session receiving the user's request is the **entry coordinator**, launched with the user-level `entry-readonly` permission profile, and read-only for repository contents. This profile extends built-in `:read-only` and permits command network access only to `api.github.com` and `chatgpt.com`. Its configuration includes a Herdr Unix socket rule, but CLI and MCP access must be checked independently. The coordinator inspects scope and state, plans, performs explicitly authorized Herdr orchestration, relays user and reviewer revision requests to the existing implementation agent, and verifies returned diffs and evidence read-only. It must not edit, test, fix, stage, commit, push, or create/update a PR in the repository. A separate **implementation agent** owns all repository mutations in its assigned worktree, subject to Issue and user authorization. **Review agents** are read-only. These profiles do not provide per-worktree filesystem isolation.

## Reuse before creating

Inspect Herdr logical state before editing or creating work. In the current session, use the registered Herdr MCP bridge's read-only inspection tools first when they are available:

- `herdr_server_status`
- `herdr_workspace_list`
- `herdr_agent_list`

When these MCP calls succeed, use their results for Herdr server, workspace, and agent state. A configured socket rule does not guarantee direct CLI access; validate CLI and MCP independently. Do not infer MCP failure from direct CLI failure. The bridge has no worktree-list tool, so independently inspect repository work state with Git and GitHub:

```bash
git worktree list --porcelain
git branch --list
gh pr list --state open
```

Do not call the direct Herdr CLI only to obtain worktree information when the MCP state calls succeeded. If the bridge is unavailable or any MCP call fails, use the approved read-only Herdr CLI fallback:

```bash
test "${HERDR_ENV:-}" = 1 || exit 1
herdr status server
herdr workspace list
herdr agent list
herdr worktree list --cwd "$REPO_ROOT"
```

If a Herdr CLI call returns `EPERM` or `Operation not permitted`, report that exact blocker and stop; do not retry through escalation. A CLI failure alone does not establish that MCP failed.

If the required Herdr state cannot be inspected through either MCP or the CLI fallback, report the blocker before editing or creating work. Do not assume state that could not be inspected.

Use Git worktrees, local branches, and open PRs to match repository work by Issue number and branch. If the same Issue is active, resume its workspace and agent. Do not close or repurpose unrelated workspaces. If Herdr state cannot be read, retry read-only inspection with the available authorized execution context and search Codex sessions when that tool is available. Do not create a new workspace while same-Issue work may still be active.

If no matching work exists, create an unfocused Issue workspace and worktree. Read all IDs and paths from Herdr's JSON response; never guess IDs:

```bash
herdr workspace create --cwd "$REPO_ROOT" --label "issue-<N>" --no-focus
herdr worktree create --workspace "$WORKSPACE_ID" \
  --branch "agent/<N>-<slug>" --base dev --label "issue-<N>" --no-focus
```

Omit `--path` to use Herdr's configured worktree root and branch-derived directory name. If the returned path is outside the allowed write roots, identify the boundary and follow the repository or session's approved alternate-root procedure before starting agents. Do not silently select a custom path.

The Herdr MCP bridge provides read-only inspection plus narrowly scoped, explicitly authorized teardown tools. Use the existing authorized Herdr orchestration path for general workspace or worktree creation, agent start or prompts, and pane control. Use `herdr_worktree_remove` and `herdr_workspace_close` only for cleanup authorized by the user or Issue and only with the safeguards below; these tools do not authorize other Herdr mutations.

Use the worktree returned by Herdr for the implementation branch. Confirm its branch, base, and clean state before starting agents. Use the returned shell pane when it is at an interactive prompt; otherwise split a pane with the worktree path as cwd and `--no-focus`. Start agents only in returned pane IDs and use unique names. Never start two agents in one pane.

## Agent allocation

Use one implementation writer by default. Add an implementation agent only when the Issue breaks into independent, non-overlapping file or subsystem scopes. Give each writer a separate worktree/branch and a precise deliverable; the lead integrates its result into the Issue branch. Never let multiple writers edit the same worktree concurrently. The entry coordinator never joins the writer role.

Use one independent reviewer for ordinary changes. Add a second reviewer when the Issue changes public/data contracts, security-sensitive code, or several subsystems. Reviewers must not edit, stage, commit, or run write-producing commands.

## Model and permission profile settings

Use the requested models when the installed CLIs support them. Check current CLI help if arguments have changed; do not silently substitute another model. The user-level `herdr-implementation` and `entry-readonly` permission profiles must exist. Select them with Codex `--config 'default_permissions="<profile>"'`. Do not combine permission profiles with legacy `sandbox_mode` or `sandbox_workspace_write` settings. The implementation profile extends `:workspace`, with command network access limited to `api.github.com` and `chatgpt.com`; its configuration includes a Herdr Unix socket rule, but CLI and MCP access must be checked independently. Its current writable root covers the entire `~/.herdr/worktrees`; it does not enforce per-worktree writes.

Codex implementer default:

```bash
herdr agent start <name> --kind codex --pane <pane-id> -- --config 'default_permissions="herdr-implementation"'
```

Full command with model settings:

```bash
herdr agent start implementer --kind codex --pane "$PANE_ID" -- \
  --model gpt-6-luna \
  --config 'model_reasoning_effort="high"' \
  --config 'service_tier="fast"' \
  --config features.fast_mode=true \
  --config 'default_permissions="herdr-implementation"' \
  --ask-for-approval never
```

Do not use `--dangerously-bypass-approvals-and-sandbox` or `--dangerously-skip-permissions`.

Read-only Codex reviewer:

```bash
herdr agent start <name> --kind codex --pane <pane-id> -- --config 'default_permissions="entry-readonly"'
```

Full command with model settings:

```bash
herdr agent start reviewer --kind codex --pane "$PANE_ID" -- \
  --model gpt-6-luna \
  --config 'model_reasoning_effort="high"' \
  --config 'service_tier="fast"' \
  --config features.fast_mode=true \
  --config 'default_permissions="entry-readonly"' \
  --ask-for-approval never
```

If either required permission profile is unavailable, or Herdr cannot create or start the required implementation agent, report the exact blocker and stop. Do not silently substitute an unrestricted/default writer or take over in the entry session. If an installed model or setting is unavailable, follow the repository's approved model fallback without changing the required profile.

## Handoff prompts

Give the implementation agent the Issue link/number, repository instructions, acceptance criteria, non-goals, branch/worktree, assigned files, validation plan, and a requirement to report changed files and command results. Tell it to make only in-scope changes and own all repository mutations, including implementation, tests, and review fixes. It may stage and commit only if Issue or user authorization permits; it may push or create/update a PR only when explicitly authorized. It must never merge without separate authorization. The entry coordinator remains read-only for repository contents and delegates any authorized delivery mutations to this same implementation agent.

Prompt reviewers with the Issue, acceptance criteria, full base-to-HEAD diff, and relevant repository instructions. Require findings in this form:

- Severity: blocker / high / medium / low
- File and line
- Concrete failure or unmet acceptance criterion
- Evidence and a focused correction

Explicitly instruct reviewers to remain read-only and report no findings when none exist. Start each Codex reviewer with `--config 'default_permissions="entry-readonly"'`; the profile must be available and read-only review access comes from that configured profile, not from a sandbox flag alone. Send tasks and findings through Herdr, for example `herdr agent prompt implementer "<scoped implementation task>" --wait` and `herdr agent prompt reviewer "<read-only review task>" --wait`. After review, relay each actionable finding and any user-requested revision to the existing implementation agent with a focused fix request, then obtain a fresh reviewer response. The entry coordinator does not apply fixes. Inspect `agent get`/`agent read` if a wait fails or an agent is blocked.

## Review and completion loop

1. Wait for the implementation agent to settle; inspect its status, full diff, and validation evidence read-only as coordinator.
2. Start or prompt the reviewer after the diff is ready.
3. Relay each in-scope actionable finding to the existing implementation agent. Ask it for a correction and evidence; do not ask the user to mediate or apply the fix in the coordinator session.
4. Have the implementation agent run relevant validation and request a fresh review of the changed diff. Verify the returned evidence. Repeat up to three rounds.
5. Treat unresolved blocker/high findings or failed required validation as a stop condition. Medium/low suggestions that do not violate acceptance criteria may be recorded as limitations.
6. Before delivery, inspect repository state read-only: verify all modified files are within Issue scope, the base is `dev`, and no required validation was skipped. If changes are already committed, verify the commit contents and confirm the worktree is clean before push. Report the pre-push summary to the user, including commit log when applicable, changed files, validation results, and remaining limitations. This is informational when delivery is already authorized; do not wait for another reply.
7. If local commit permission is allowed, delegate staging and commit to the same implementation agent. If push and PR permission is explicitly authorized, delegate pushing only the Issue branch and creating or updating its PR to that same agent. Never push directly to `dev` or `main`; never merge without separate authorization. Before PR creation/update, the coordinator reads the target repository's instructions and applicable PR template and passes their conventions to the implementation agent. If a PR already exists for the branch, update it instead of creating a duplicate. Inspect the resulting repository state and PR body read-only against those conventions.

If Herdr reports an agent as blocked, inspect its state and output before sending anything. Continue only when the request is clearly within the Issue authorization; stop on approval requests outside that scope. Never answer a security or data-permission prompt by guessing.
## Authorized Issue workspace cleanup

Only clean a workspace after explicit user authorization or an Issue that authorizes cleanup. Before calling a mutation tool:

1. Confirm the PR is merged, or the user explicitly authorized abandoning the work. An open PR is not a cleanup signal.
2. Confirm the target is an Issue workspace, is not the caller/current focused workspace, does not share a Git repository with the caller or any other Herdr workspace, and is not needed by another task.
3. Confirm all agents in the target are idle or done; stop if any agent is working, blocked, or unknown.
4. For a linked worktree, confirm git status --porcelain is empty and the branch is not dev or main; call the explicit MCP tool herdr_worktree_remove without force.
5. Close a workspace with herdr_workspace_close only after confirming it has no linked worktree.
6. Read Herdr workspace/agent inventory and git worktree list --porcelain again. Report success only if every requested target is absent and unrelated workspace IDs remain present.

If a tool is unavailable, denied, or returns a timeout/ambiguous result, read state before deciding what remains. Never retry through direct Herdr CLI, blindly repeat a mutation, use --force, or substitute raw API calls. Preserve unresolved work and report the exact result.
