---
name: travel-issue-agent-loop
description: "Use when a user authorizes implementation of a repository Issue through a PR, including follow-up changes to that Issue's open PR; coordinate implementation and read-only review agents in Herdr worktrees."
---

# Issue-to-PR agent loop

Run a complete, bounded implementation and review loop for an explicitly authorized repository Issue. The workflow has two entry modes:

- **START:** the user names an Issue and authorizes its implementation through a PR.
- **REENTER:** the user requests a follow-up to an already authorized Issue with an open PR, including a request that supplies only the PR number. Treat it as the same Issue execution, not a new task.

Routine work inside the authorized Issue scope should proceed without asking for intermediate approval.

## Before implementation

1. Verify `HERDR_ENV=1`. If this is not a Herdr-managed session, do not control Herdr; report the limitation.
2. Read the repository `AGENTS.md` and `docs/agent-workflow.md` before resolving or editing the task.
3. Resolve the entry mode before reading the Issue or editing. For START, use the user-selected Issue. For REENTER with only a PR number, inspect that PR's repository, state, head branch, and linked Issue; require one unambiguous Issue connection. If there is no linked Issue or the mapping is ambiguous, stop and ask which Issue applies. Do not infer authorization from a branch name alone. After resolving the Issue, read it and treat it as the source for purpose, scope, non-goals, acceptance criteria, validation, and data permissions.
4. Apply the same **pre-edit state gate** to START and REENTER. Before changing any target file, confirm the repository root and current Git state; inspect Issue/PR state, local branches and `git worktree list --porcelain`; inspect `herdr workspace list`, `herdr agent list`, and `herdr worktree list --cwd "$REPO_ROOT"`; identify same-Issue work to reuse or recover; and inspect the target repository's PR template when delivery is in scope. Record the resolved Issue, branch, worktree, workspace, and agent state. The orchestrator must not edit target files before this gate is complete.
5. Reuse or resume same-Issue work rather than creating duplicates. Never overwrite another worktree's changes. Follow the state-specific recovery rules in [references/agent-loop.md](references/agent-loop.md).
6. If Herdr state cannot be read, retry read-only inspection only through the available authorized execution context. If Herdr is unavailable, an approved implementer/reviewer cannot start, required permissions are missing, or requirements conflict, stop and report the blocker; do not fall back to direct editing or an unapproved general agent.
7. Do not start implementation if required scope, acceptance criteria, or data access permission is missing or contradictory. Use repository evidence to resolve routine details; do not invent data meanings, contracts, or architecture decisions.

## Worktree and agents

For START, create one dedicated Issue worktree and branch from `dev` only when no matching same-Issue branch, worktree, or open PR already exists, following `docs/agent-workflow.md` (normally `agent/<issue>-<slug>`). For REENTER, reuse or reopen the existing PR head branch and matching worktree; do not create a new Issue branch when the PR branch exists. Use Herdr and preserve the user's current focus. Keep every writer in a separate worktree when their file scopes are independent; use one lead implementer to integrate parallel work.

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

## Delivery

Before push, prepare and report the commit, changed files, validation results, and remaining limitations as required by repository policy. This report is informational when push/PR is already authorized; do not wait for a reply. Push only the Issue branch and create or update its PR. Never push directly to `dev` or `main`, merge the PR, deploy, or delete worktrees unless separately authorized.

Before creating or updating a PR, inspect the target repository's instructions and any applicable PR template. Follow the conventions selected by that repository; do not assume this skill's home-repository template applies elsewhere. After the PR write, inspect the resulting body against those conventions.

Finish with the branch and PR links, implementation summary, reviewers and rounds, validation performed, and any unresolved blocker. Leave the Issue worktree available for follow-up unless the user requested cleanup.
