---
name: travel-issue-agent-loop
description: "Use when a user names a repository Issue and authorizes implementation through a PR; coordinate implementation and read-only review agents in Herdr worktrees."
---

# Issue-to-PR agent loop

Run a complete, bounded implementation and review loop for an explicitly selected repository Issue. The trigger is a clear instruction such as “Implement Issue #123; PR is authorized.” Routine work inside that scope should proceed without asking the user for intermediate approval.

## Before implementation

1. Verify `HERDR_ENV=1`. If this is not a Herdr-managed session, do not control Herdr; report the limitation.
2. Read the repository `AGENTS.md`, `docs/agent-workflow.md`, and the selected Issue. Treat the Issue as the source for purpose, scope, non-goals, acceptance criteria, validation, and data permissions.
3. Check the clean/dirty state, current branch, existing Issue worktrees, live Herdr agents/workspaces, and open PRs. Reuse or resume the same Issue's active work rather than creating duplicates. Never overwrite another worktree's changes.
4. Do not start implementation if required scope, acceptance criteria, or data access permission is missing or contradictory. Use repository evidence to resolve routine details; do not invent data meanings, contracts, or architecture decisions.

## Worktree and agents

Create one dedicated Issue worktree and branch from `dev`, following `docs/agent-workflow.md` (normally `agent/<issue>-<slug>`). Use Herdr and preserve the user's current focus. Keep every writer in a separate worktree when their file scopes are independent; use one lead implementer to integrate parallel work.

Use the path and naming returned by Herdr's configured worktree flow. If that location is inaccessible, identify the permission boundary and follow the repository or session's approved alternate-root procedure; do not silently choose a custom location.

Choose the number of agents to fit the task:

- Small, well-bounded Issue: one implementer and one reviewer.
- Medium Issue: one implementer and one reviewer; add an independent implementer only for non-overlapping work.
- Broad or high-risk Issue: a lead plus independent implementers in separate worktrees, and one or two reviewers.

Use Codex as the default implementer. An implementation agent may instead use Agy when its CLI is available. All reviewers use Codex with a read-only sandbox. Detailed Herdr commands, model settings, and handoff prompts are in [references/agent-loop.md](references/agent-loop.md).

## Autonomous review loop

Have each implementer read the Issue, repository instructions, acceptance criteria, and assigned file scope before editing. After implementation, inspect the actual diff and run the validation required by the Issue and repository instructions.

Ask the read-only reviewer to inspect the Issue, acceptance criteria, and full diff. Relay actionable findings to the implementer, have it fix them, and request a fresh review. Repeat for at most three review rounds. Do not treat an agent's “done” message as evidence: verify the diff, working tree, validation output, and review result yourself.

Do not ask the user about routine implementation choices. Continue through the authorized work, including branch push and PR creation when the user explicitly authorizes PR delivery. Stop only for a real blocker: missing or conflicting requirements/permissions, unavailable required access, a security concern outside the authorization, or an issue that remains unresolved after three review rounds.

## Authorized cleanup

Clean an Issue workspace only when the user explicitly requests cleanup or the Issue authorizes it. Follow the guarded MCP teardown sequence in [references/agent-loop.md](references/agent-loop.md). Do not close the caller, current focused workspace, or unrelated work. Report cleanup as complete only after Herdr inventory and Git worktree readback confirm the targets are absent. If a teardown tool is unavailable, denied, or returns an ambiguous result, preserve the remaining state and report the exact blocker; do not fall back to force or arbitrary shell deletion.

## Delivery

Before push, prepare and report the commit, changed files, validation results, and remaining limitations as required by repository policy. This report is informational when push/PR is already authorized; do not wait for a reply. Push only the Issue branch and create or update its PR. Never push directly to `dev` or `main`, merge the PR, deploy, or delete worktrees unless separately authorized.

Before creating or updating a PR, inspect the target repository's instructions and any applicable PR template. Follow the conventions selected by that repository; do not assume this skill's home-repository template applies elsewhere. After the PR write, inspect the resulting body against those conventions.

Finish with the branch and PR links, implementation summary, reviewers and rounds, validation performed, and any unresolved blocker. Leave the Issue worktree available for follow-up unless the user requested cleanup.
