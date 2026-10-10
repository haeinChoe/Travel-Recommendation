---
name: travel-issue-agent-loop
description: "Use when a user names a repository Issue and authorizes implementation through a PR; coordinate implementation and read-only review agents in Herdr worktrees."
---

# Issue-to-PR agent loop

Run a complete, bounded implementation and review loop for an explicitly selected repository Issue. The trigger is a clear instruction such as “Implement Issue #123; PR is authorized.” Routine work inside that scope should proceed without asking the user for intermediate approval.

The Codex session that receives the user's request is the **entry coordinator**, launched with the user-level `entry-readonly` permission profile, and is read-only for repository contents. The profile extends `:read-only` and allows command network access only to `api.github.com` and `chatgpt.com`. Its configuration includes a Herdr Unix socket rule, but CLI and MCP access must be checked independently. The coordinator inspects scope and state, plans the work, performs explicitly authorized Herdr orchestration, relays user or reviewer revision requests to the existing implementation agent, and verifies returned diffs and evidence read-only. It must not edit, test, fix, stage, commit, push, or create/update a PR in the repository. A separate **implementation agent** owns all repository mutations in its assigned worktree, subject to the Issue's and user's authorization gates. **Review agents** are read-only. Do not describe these profiles as stronger filesystem isolation than they provide.

## Before implementation

1. Verify `HERDR_ENV=1`. If this is not a Herdr-managed session, do not control Herdr; report the limitation.
2. Read the repository `AGENTS.md`, `docs/agent-workflow.md`, and the selected Issue. Treat the Issue as the source for purpose, scope, non-goals, acceptance criteria, validation, and data permissions.
3. Before editing, inspect Herdr server, workspace, and agent state. Prefer the registered Herdr MCP bridge's read-only inspection tools when they are available in the current session; follow [references/agent-loop.md](references/agent-loop.md) for the CLI fallback. A configured socket rule does not guarantee direct CLI access; validate CLI and MCP independently. If a Herdr CLI call returns `EPERM` or `Operation not permitted`, report that exact blocker and stop without retrying through escalation; do not infer MCP failure from CLI failure. If neither path completes the state check, report the blocker before editing or creating work. Then check the clean/dirty state, current branch, existing Issue worktrees, and open PRs. Reuse or resume the same Issue's active work rather than creating duplicates. Never overwrite another worktree's changes.
4. Do not start implementation if required scope, acceptance criteria, or data access permission is missing or contradictory. Use repository evidence to resolve routine details; do not invent data meanings, contracts, or architecture decisions.

## Worktree and agents

Create one dedicated Issue worktree and branch from `dev`, following `docs/agent-workflow.md` (normally `agent/<issue>-<slug>`). Use Herdr and preserve the user's current focus. The entry coordinator does not edit files in that worktree. Assign a dedicated implementation agent as the writer; it owns all edits, tests, and review fixes there. Keep every writer in a separate worktree when their file scopes are independent; use one lead implementer to integrate parallel work.

The Herdr MCP bridge provides read-only inspection plus narrowly scoped, explicitly authorized teardown tools. Use the existing authorized Herdr orchestration path for general workspace/worktree creation, agent start or prompts, and pane control. Use `herdr_worktree_remove` or `herdr_workspace_close` only when the user or Issue explicitly authorizes cleanup and the guarded procedure in [references/agent-loop.md](references/agent-loop.md) is satisfied.

Use the path and naming returned by Herdr's configured worktree flow. If that location is inaccessible, identify the permission boundary and follow the repository or session's approved alternate-root procedure; do not silently choose a custom location.

Choose the number of agents to fit the task:

- Small, well-bounded Issue: one implementer and one reviewer.
- Medium Issue: one implementer and one reviewer; add an independent implementer only for non-overlapping work.
- Broad or high-risk Issue: a lead plus independent implementers in separate worktrees, and one or two reviewers.

Use Codex as the default implementation agent with the user-level `herdr-implementation` permission profile; start every Codex reviewer with `entry-readonly`. These named profiles must exist in the user's Codex configuration. The implementation profile extends `:workspace`, allows command network access only to `api.github.com` and `chatgpt.com`, and has a configured Herdr Unix socket rule; check CLI and MCP access independently. Its current writable root covers the entire `~/.herdr/worktrees`, so it does not enforce per-worktree writes. If either required profile is unavailable, report the exact blocker and stop; do not silently use an unrestricted/default writer or take over in the entry session. Select profiles through Codex `--config 'default_permissions="<profile>"'`; do not combine them with legacy `sandbox_mode` or `sandbox_workspace_write`. Detailed Herdr commands, model settings, and handoff prompts are in [references/agent-loop.md](references/agent-loop.md).

## Autonomous review loop

Have the implementation agent read the Issue, repository instructions, acceptance criteria, and assigned file scope before editing. It performs edits, tests, and review fixes in its assigned worktree. It may stage and commit only when the Issue or user authorization permits; it may push or create/update a PR only when explicitly authorized, and must never merge without separate authorization. The entry coordinator verifies the implementation agent's state, actual diff, and validation evidence read-only; it does not perform repository mutations.

Ask the read-only reviewer to inspect the Issue, acceptance criteria, and full diff. Relay actionable findings, and any user-requested revisions, to the existing implementation agent; have that agent make the fixes and request a fresh review. Do not apply findings in the entry session. Repeat for at most three review rounds. Do not treat an agent's “done” message as evidence: verify the diff, working tree, validation output, and review result yourself.

Do not ask the user about routine implementation choices. Continue through the authorized work. When delivery is authorized, the entry coordinator reports the pre-push summary, then delegates the permitted commit, push, and PR steps to that same implementation agent and inspects the resulting repository state and PR read-only. The implementation agent must follow all repository authorization gates, including commit permission, explicit push/PR permission, branch restrictions, and the prohibition on merging without separate authorization. Stop only for a real blocker: missing or conflicting requirements/permissions, unavailable required access, a security concern outside the authorization, or an issue that remains unresolved after three review rounds.

## Authorized cleanup

Clean an Issue workspace only when the user explicitly requests cleanup or the Issue authorizes it. Follow the guarded MCP teardown sequence in [references/agent-loop.md](references/agent-loop.md). Do not close the caller, current focused workspace, or any workspace that shares a Git repository with the caller or another Herdr workspace. Use only the guarded MCP teardown tools; never fall back to `herdr workspace close` or another direct CLI mutation when the bridge refuses or is unavailable. Report cleanup as complete only after Herdr inventory and Git worktree readback confirm the targets are absent. If a teardown tool is unavailable, denied, or returns an ambiguous result, preserve the remaining state and report the exact blocker.

## Delivery

The implementation agent prepares repository changes and, when separately permitted, staging and the local commit. The entry coordinator inspects the worktree and proposed delivery state read-only, then reports the required pre-push summary: commit log (if committed), changed files, validation results, and remaining limitations. If push/PR permission is explicit, delegate the authorized push and PR creation/update to that same implementation agent; do not perform those repository mutations in the coordinator session. The implementation agent pushes only the Issue branch and creates or updates its PR. Never push directly to `dev` or `main`; never merge, deploy, or delete worktrees unless separately authorized.

Before creating or updating a PR, the coordinator reads the target repository's instructions and any applicable PR template, then gives those conventions to the implementation agent. The implementation agent follows them; the coordinator inspects the resulting PR body and state read-only.

Finish with the branch and PR links, implementation summary, reviewers and rounds, validation performed, and any unresolved blocker. Leave the Issue worktree available for follow-up unless the user requested cleanup.
