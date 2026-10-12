# Herdr implementation and review procedure

Read this reference when running the Issue-to-PR loop.

The session receiving the user's request is the **entry coordinator**, launched with the user-level `entry-readonly` permission profile, and read-only for repository contents. This profile extends built-in `:read-only`; command network policy is defined by the selected user-level Codex permission profile and configuration. Its configuration includes a Herdr Unix socket rule, but CLI and MCP access must be checked independently. The coordinator inspects scope and state, plans, performs explicitly authorized Herdr orchestration, relays user and reviewer revision requests to the existing implementation agent, and verifies returned diffs and evidence read-only. It must not edit, test, fix, stage, commit, push, or create/update a PR in the repository. A separate **implementation agent** owns all repository mutations in its assigned worktree, subject to Issue and user authorization. **Review agents** are read-only. These profiles do not provide per-worktree filesystem isolation.

## Reuse before creating

Inspect Herdr logical state before editing or creating work. In the current session, use the registered Herdr MCP bridge's read-only inspection tools first when they are available:

- `herdr_server_status`
- `herdr_workspace_list`
- `herdr_agent_list`

When these MCP calls succeed, use their results for Herdr server, workspace, and agent state. Do not invoke the direct Herdr CLI as a second verification path for the same state. A configured socket rule does not guarantee direct CLI access; validate the CLI only when the approved fallback is actually required. Do not infer MCP failure from direct CLI failure. The bridge has no worktree-list tool, so independently inspect repository work state with Git and GitHub:

```bash
git worktree list --porcelain
git branch --list
gh pr list --state open
```

Do not call the direct Herdr CLI only to obtain worktree information when the MCP state calls succeeded. If the bridge is unavailable or a required MCP inspection fails, use the approved read-only Herdr CLI fallback. Keep the shell in its approved orchestration execution context; `--cwd "$REPO_ROOT"` tells Herdr which repository to inspect and is not an instruction to `cd` into that repository:

```bash
test "${HERDR_ENV:-}" = 1 || exit 1
herdr status server
herdr workspace list
herdr agent list
herdr worktree list --cwd "$REPO_ROOT"
```

If a Herdr CLI call returns `EPERM` or `Operation not permitted`, do not retry that denied command through escalation. Classify the failure first. If the call was redundant after successful MCP inspection, or was launched from an invalid/unapproved execution boundary, treat it as an orchestration defect and continue only through the already-authorized path after correcting the boundary. If the required Herdr capability itself cannot be completed through any authorized route, report that exact blocker and stop. A CLI failure alone does not establish that MCP failed.

If the required Herdr state cannot be inspected through either MCP or the CLI fallback, report the blocker before editing or creating work. Do not assume state that could not be inspected.

Use Git worktrees, local branches, open PRs, and Herdr metadata to match repository work by Issue number and branch. Never infer Issue ownership from a workspace ID, focus state, or proximity alone; reuse only when the Issue branch, Git worktree path/branch, and Herdr metadata establish the mapping. If the same Issue is active, resume its workspace and agent. Do not close or repurpose unrelated workspaces. If Herdr state cannot be read, retry read-only inspection with the available authorized execution context and search Codex sessions when that tool is available. Do not create a new workspace while same-Issue work may still be active.

If no matching work exists, create an unfocused Issue workspace and worktree. These are state-changing Herdr operations; when no MCP mutation equivalent exists, use the global Herdr skill's approval-reviewed escalated execution route on the first attempt rather than probing the ordinary sandbox. Read all IDs and paths from Herdr's JSON response; never guess IDs:

```bash
herdr workspace create --cwd "$REPO_ROOT" --label "issue-<N>" --no-focus
herdr worktree create --workspace "$WORKSPACE_ID" \
  --branch "agent/<N>-<slug>" --base dev --label "issue-<N>" --no-focus
```

Omit `--path` to use Herdr's configured worktree root and branch-derived directory name. Before starting any writer, verify the returned path is inside the allowed write roots of the `herdr-implementation` profile. If it is outside, stop before agent startup and identify the configuration boundary. Do not silently select, relocate, or synthesize a custom path.

The Herdr MCP bridge provides read-only inspection plus narrowly scoped, explicitly authorized teardown tools. Use the existing authorized Herdr orchestration path for general workspace or worktree creation, agent start or prompts, and pane control. Use `herdr_worktree_remove` and `herdr_workspace_close` only for cleanup authorized by the user or Issue and only with the safeguards below; these tools do not authorize other Herdr mutations.

Use the worktree returned by Herdr for the implementation branch. Confirm its branch, base, and clean state before starting agents. Pane inventory is not a mandatory preflight: prefer a pane returned by the authorized orchestration flow; if none is available, create or split one explicitly for the confirmed Issue worktree with `--no-focus`. Do not call `pane list` merely to discover a usable pane, and do not call `pane current --current` only to reconfirm already-set caller context. Start agents only in returned pane IDs and use unique names. Never start two agents in one pane.

## Herdr CLI execution boundary

Direct Herdr CLI calls are orchestration commands, not ordinary repository commands. Read-only inspection is a fallback when MCP cannot provide required state; explicitly authorized state-changing commands without an MCP mutation equivalent use the global Herdr skill's approval-reviewed escalated route on the first attempt.

1. Do not run direct Herdr CLI from an arbitrary repository or implementation-worktree cwd.
2. Prefer the registered MCP bridge for every inspection capability it provides. Successful MCP inspection forbids a redundant CLI re-check for the same state.
3. State-changing Herdr commands without an MCP mutation equivalent use the global skill's approval-reviewed escalated route on the first attempt; do not probe them first in the ordinary sandbox.
4. `pane list` and `pane current --current` are optional discovery commands, not mandatory Issue-start checks.
5. When a fallback CLI command needs a repository target, pass it explicitly with `--cwd "$REPO_ROOT"` or the documented equivalent while keeping the coordinator in its approved orchestration context.
6. Do not change shell cwd into `$REPO_ROOT` merely because a Herdr command accepts `--cwd "$REPO_ROOT"`.
7. Before starting an implementation agent, validate that the worktree path returned by Herdr falls under the writable roots of the `herdr-implementation` profile. Do not start the agent first and wait for an `EPERM` to discover the mismatch.
8. Implementation commands run only in the exact Herdr-returned worktree. Never guess, move, synthesize, or substitute another path as a recovery mechanism.
9. An `EPERM` from an invalid boundary, unnecessary optional discovery, or an ordinary-sandbox attempt of a command whose approved first-attempt route is already defined is an orchestration defect. Do not retry the denied invocation; correct the execution boundary and continue only through an authorized route. Use the already-defined approved route only if it has not yet been attempted.
10. Treat the failure as an Issue-level blocker only when the workflow requires that Herdr capability and it remains unavailable through every authorized route. If the approved required invocation is rejected or still returns `EPERM`, stop and report that blocker.
11. Never introduce a broader permission route, unrestricted profile, sandbox bypass, force option, or blind retry as recovery.

## Agent allocation

Use one implementation writer by default. Add an implementation agent only when the Issue breaks into independent, non-overlapping file or subsystem scopes. Give each writer a separate worktree/branch and a precise deliverable; the lead integrates its result into the Issue branch. Never let multiple writers edit the same worktree concurrently. The entry coordinator never joins the writer role.

Use one independent reviewer for ordinary changes. Add a second reviewer when the Issue changes public/data contracts, security-sensitive code, or several subsystems. Reviewers must not edit, stage, commit, or run write-producing commands.

## Model and permission profile settings

Use the requested models when the installed CLIs support them. Check current CLI help if arguments have changed; do not silently substitute another model. The user-level `herdr-implementation` and `entry-readonly` permission profiles must exist. Select them with Codex `--config 'default_permissions="<profile>"'`. Do not combine permission profiles with legacy `sandbox_mode` or `sandbox_workspace_write` settings. The implementation profile extends `:workspace`; command network policy is defined by the selected user-level Codex permission profile and configuration. Its configuration includes a Herdr Unix socket rule, but CLI and MCP access must be checked independently. Its current writable root covers the entire `~/.herdr/worktrees`; it does not enforce per-worktree writes.

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
  --config 'default_permissions="herdr-implementation"'
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
  --config 'default_permissions="entry-readonly"'
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

Only clean a workspace after explicit user authorization or an Issue that authorizes cleanup. Treat linked workspace-session closure, linked worktree removal, and plain workspace closure as three different operations with different safeguards. Linked-session closure preserves the checkout; linked-worktree removal deletes the checkout. An open PR is not a cleanup signal: confirm the target PR is merged, or that the user explicitly authorized abandoning the work.

Before any operation, read Herdr workspace and agent inventories and Git state. Match the Issue to the exact workspace ID, worktree path (if any), and branch; verify the target is not the caller or current focused workspace; confirm no other task needs it; and confirm every attached agent is `idle` or `done`. Stop if an agent is `working`, `blocked`, `unknown`, missing a status, or otherwise unsettled. Record the current inventory and Git state so the post-operation check can detect unrelated changes.

### Cleanup decision matrix

This table is the compact policy source for operation-specific checks. Automated documentation tests parse these rows; keep the operation/guard keys stable when editing the policy.

| Operation | Guard | Required condition |
| --- | --- | --- |
| linked workspace-session closure | target | One exact Herdr workspace maps to one linked-worktree path and branch, each uniquely confirmed by Herdr inventory and Git. |
| linked workspace-session closure | authorization | The user or Issue explicitly authorizes cleanup; the PR is merged or abandonment is explicitly authorized. |
| linked workspace-session closure | workspace | The target is neither caller nor focused, no other task needs it, and all attached agents are idle or done. |
| linked workspace-session closure | checkout_preservation | Capture peer workspace IDs, identity/focus/repository provenance, `git worktree list --porcelain`, and full status with `--untracked-files=all --ignored=matching` before close; afterward preserve all peer IDs and identity/focus/repository provenance, allowing at most one derived `open_workspace_id` association equal to the closed ID to be omitted from a linked-worktree row. Preserve that row's path, branch, linked flag, and all other metadata. Git worktree/status snapshots and checkout path/branch must be unchanged, including dirty and ignored files. |
| linked workspace-session closure | mutation | Use only guarded MCP `herdr_workspace_close` for the exact workspace ID; it must invoke `herdr workspace close <ID>` without `--group`. Never use CLI, raw API, or another route to bypass the guard. |
| linked workspace-session closure | readback | Confirm the target session is absent from Herdr; no peer workspace ID vanished or appeared; peer identity, focus, and repository provenance are unchanged; at most one derived `open_workspace_id` association equal to the closed ID was omitted from a linked-worktree row while its path, branch, linked flag, and other metadata stayed exact; and the checkout remains at the same path and branch with `git worktree list --porcelain` and `git status --porcelain=v1 --untracked-files=all --ignored=matching` unchanged. |
| linked worktree removal | target | One exact Issue workspace maps to one Herdr-linked worktree path and branch. |
| linked worktree removal | authorization | The user or Issue explicitly authorizes cleanup; the PR is merged or abandonment is explicitly authorized. |
| linked worktree removal | workspace | The target is neither caller nor focused, no other task needs it, and all attached agents are idle or done. |
| linked worktree removal | git_clean | `git status --porcelain=v1 --untracked-files=all --ignored=matching` is empty for the target checkout. |
| linked worktree removal | protected_branch | The target branch is not `dev`, `main`, or another branch protected by repository policy. |
| linked worktree removal | common_git_dir | Linked worktrees normally share `.git` common-dir; that fact alone does not block removing this eligible checkout. |
| linked worktree removal | mutation | Call `herdr_worktree_remove` for the exact workspace ID; do not pass force. |
| linked worktree removal | local_branch | After successful removal, if the branch is merged and no worktree uses it, run `git branch -d <branch>` and verify the local ref is absent; do not delete the remote branch or use `-D`. |
| linked worktree removal | readback | Confirm the requested workspace/path is absent from Herdr and `git worktree list --porcelain`; confirm unrelated workspace IDs and other worktree state remain. |
| plain workspace closure | target | The exact Issue workspace is a plain workspace with no linked worktree; remove a linked worktree first through its separate procedure. |
| plain workspace closure | authorization | The user or Issue explicitly authorizes cleanup; the PR is merged or abandonment is explicitly authorized. |
| plain workspace closure | workspace | The target is neither caller nor focused, no other task needs it, and all attached agents are idle or done. |
| plain workspace closure | repository_guard | `herdr_workspace_close` requires valid caller identity and verified plain-workspace provenance plus exact primary-checkout ownership. The bridge rejects mapped linked child rows owned by the target; other primary-close attempts may be refused by Herdr's single-ID guard. A secondary plain workspace may close only when the bridge can verify and preserve its primary checkout owner and all workspace peers. |
| plain workspace closure | cascade_reason | Herdr may require group intent to close a primary workspace that still has linked workspaces. The bridge never passes group intent and reports that refusal without retrying. Snapshot checks detect any unexpected peer or Git change. This close-only safeguard is not a blanket restriction on linked worktree removal or exact linked-session closure, which preserves its checkout. |
| plain workspace closure | mutation | Call guarded MCP `herdr_workspace_close` for the exact plain workspace ID only after the bridge's provenance and ownership checks pass; never use group-close or a CLI/raw-API bypass. |
| plain workspace closure | readback | Confirm the target workspace is absent and Git worktree/status snapshots are unchanged; preserve the primary checkout owner and unrelated workspaces. |

For linked worktree removal, the bridge verifies Herdr's linked-worktree mapping, absolute path, current branch, and Git's worktree list. It refuses `dev` and `main`, and checks tracked, untracked, and ignored state using the command in the matrix. A linked checkout normally shares a Git common directory with its primary checkout and sibling worktrees. Do not treat that normal Git arrangement as repository ownership of the Herdr workspace or as a removal blocker: the MCP removal guard is specific to the requested linked checkout and snapshots the other Git worktree/status state around removal.

For linked workspace-session closure, the bridge requires one exact mapping between Herdr's linked workspace provenance, its worktree row, and Git's path/branch records. It checks caller and focus identity and settled agents, then snapshots workspace peers, Git worktrees, and full status before invoking only `herdr workspace close <ID>`. Afterward it verifies the session is gone, no peer workspace ID vanished or appeared, and peer identity/focus/repository provenance are preserved. The sole tolerated peer metadata delta is omission of at most one derived `open_workspace_id` association from a linked-worktree row whose prior value was the closed workspace ID; that row's path, branch, linked flag, and all other fields remain exact. Git worktree and full status snapshots remain exact. This path preserves the checkout even when it contains dirty, untracked, or ignored files. Never call `herdr workspace close --group`, use direct CLI mutation, or bypass guarded MCP.

For plain workspace closure, the bridge requires a plain workspace provenance record and verifies exact ownership of its primary checkout. It identifies the primary owner across Herdr workspaces and Git worktree metadata, and rejects linked child rows that map directly to the target before mutation. Other primary-close attempts may reach Herdr's single-ID close guard; if Herdr returns `workspace_group_close_required`, the bridge reports the refusal and does not retry with group intent. A secondary plain workspace may close when the bridge can verify that the primary checkout owner and all workspace peers remain intact. This is distinct from linked-session closure, which has its own exact mapping and snapshot checks, and from linked worktree removal, which removes an eligible clean checkout.

After a successful `herdr_worktree_remove`, check whether the corresponding local branch remains. If the PR is merged, the branch is not checked out in another worktree, and repository policy permits deletion, delete it with `git branch -d <branch>` and verify `git branch --list -- <branch>` is empty. If Git refuses because it is not merged or is still checked out, preserve it and report why. Never use `git branch -D`, delete the remote branch, or use branch deletion to bypass a failed worktree-removal call.

If an MCP mutation is refused, times out, or returns an ambiguous result, reread Herdr workspace/agent inventories and Git state (`git status`, `git worktree list --porcelain`, and branch state) before reporting what remains. Report the exact tool error and observed state without workspace or pane IDs, local absolute paths, credentials, or data. For example, a `herdr_worktree_remove` refusal may report `Caller pane identity is unavailable; refusing teardown`; this is a caller-context failure, not a shared-`.git` refusal. Do not bypass an MCP refusal through direct Herdr CLI mutation, group-close, raw APIs, force options, or blind retries. Preserve unresolved state and report the exact blocker. If a call succeeds, report cleanup complete only after Herdr and Git readback confirm the requested target is absent and unrelated state is preserved; for linked-session closure, the checkout and its snapshots must remain present and unchanged.
