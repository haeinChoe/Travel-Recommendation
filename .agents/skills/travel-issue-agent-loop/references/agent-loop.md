# Herdr implementation and review procedure

Read this reference when running the Issue-to-PR loop.

## Reuse before creating

Check the Herdr session and current work before changing its layout:

```bash
test "${HERDR_ENV:-}" = 1
herdr workspace list
herdr agent list
herdr worktree list --cwd "$REPO_ROOT"
```

Also check the Issue's open PRs and the repository's local branches/worktrees. Match work by Issue number and branch. If the same Issue is active, resume its workspace and agent. Do not close or repurpose unrelated workspaces. If Herdr state cannot be read, retry read-only inspection with the available authorized execution context and search Codex sessions when that tool is available. Do not create a new workspace while same-Issue work may still be active.

Only for START, after the gate confirms there is no matching same-Issue branch, worktree, or open PR, create an unfocused Issue workspace and worktree from dev. Read all IDs and paths from Herdr's JSON response; never guess IDs.

For REENTER, an existing PR head branch is matching Issue work even when no Herdr worktree is listed. Do not use the following dev-branch creation commands. Reuse or create a workspace, then open the exact existing PR head branch with herdr worktree open --workspace "$WORKSPACE_ID" --branch "$PR_HEAD_BRANCH" --label "issue-<N>" --no-focus. If Herdr cannot open that branch, stop and report the blocker rather than creating a replacement branch.

```bash
herdr workspace create --cwd "$REPO_ROOT" --label "issue-<N>" --no-focus
herdr worktree create --workspace "$WORKSPACE_ID" \
  --branch "agent/<N>-<slug>" --base dev --label "issue-<N>" --no-focus
```

Omit `--path` to use Herdr's configured worktree root and branch-derived directory name. If the returned path is outside the allowed write roots, identify the boundary and follow the repository or session's approved alternate-root procedure before starting agents. Do not silently select a custom path.

Use the worktree returned by Herdr for the implementation branch. Confirm its branch, base, and clean state before starting agents. Use the returned shell pane when it is at an interactive prompt; otherwise split a pane with the worktree path as cwd and `--no-focus`. Start agents only in returned pane IDs and use unique names. Never start two agents in one pane.

## START / REENTER state resolution

Complete this gate before any target-file edit:

1. Confirm the repository root, Issue permissions, current branch, clean/dirty state, local branches, and `git worktree list --porcelain`.
2. Resolve the Issue identity. A user-supplied Issue number is authoritative. For a PR-only request, inspect the PR state, head branch, and linked/closing Issues using the repository's authorized GitHub access. Continue only when exactly one relevant Issue is identified; if none or multiple are linked, stop and ask rather than guessing from branch names.
3. Inspect `herdr workspace list`, `herdr agent list`, and `herdr worktree list --cwd "$REPO_ROOT"`. Match work by the resolved Issue and branch. Record the workspace/worktree/pane and agent states.
4. Check open PR status and the target repository's PR template. Do not edit target files until these checks finish.

## REENTER recovery rules

| Observed state | Action |
| --- | --- |
| Existing Issue worktree and implementer agent | Reuse both. If the agent is idle/done, send the authorized follow-up; if working, do not start a duplicate; if blocked, inspect its state/output before deciding. |
| Existing Issue worktree but no live agent | Reuse its branch and worktree; start an approved implementer in an available or newly split pane. |
| Open PR branch but no Herdr worktree | Reopen that existing branch in a Herdr-managed worktree. Do not create a new Issue branch or duplicate the PR. Confirm exact installed CLI syntax with `herdr worktree open --help`. |
| Herdr session/workspace lost | Reconstruct from the Issue, open PR, branch, Git worktree list, and commits. Do not rely on pane history for correctness. |
| Herdr unavailable or state cannot be inspected | Retry read-only inspection in the authorized execution context. If still unavailable, stop. Do not edit directly or substitute an unapproved general agent. |
| Approved implementer or read-only reviewer unavailable | Stop and report the blocker; do not bypass the required agent role. |

While a PR is open, preserve its Issue worktree and make it available for follow-up; correctness must remain recoverable from the Issue, branch, commits, and PR even if a pane disappears. After the PR is merged or closed, mark the worktree cleanup-eligible only when it is clean, no live agent is using it, and the user has not requested preservation. Eligibility is not permission to delete: cleanup requires separate authorization.

## Scenario checklist

Record the result for each applicable case:

- [ ] START with a newly authorized Issue resolves its branch/worktree before edits.
- [ ] REENTER with an Issue number reuses the matching Issue work.
- [ ] REENTER with only a PR number resolves exactly one linked Issue and its head branch.
- [ ] PR with no linked Issue or multiple possible Issues stops without guessing.
- [ ] Existing worktree plus idle/done, working, and blocked agent states are handled without duplicate writers.
- [ ] Existing worktree with no live agent is reused.
- [ ] Existing PR branch without a Herdr worktree is reopened rather than duplicated.
- [ ] Lost Herdr session is reconstructed from Issue/branch/PR state.
- [ ] `HERDR_ENV != 1` or unavailable Herdr state stops before edits.
- [ ] Approved implementer/reviewer unavailable stops without fallback.
- [ ] Repository-specific PR template is followed.
- [ ] Open PR work remains recoverable; closed/merged PR becomes cleanup-eligible only when clean and without a live agent.

## Issue #20 documentation validation record (2026-10-10)

The scenario checklist above is a reusable execution plan. Check an item only after that runtime scenario has actually been exercised; no runtime lifecycle scenarios were run for this documentation change.

- `git diff --check origin/dev`: passed; Git reported only the existing AGENTS.md LF/CRLF conversion warning.
- Relative link check for `references/agent-loop.md` from SKILL.md: passed.
- `herdr workspace list`, `herdr agent list`, and `herdr worktree list --cwd "$REPO_ROOT"`: accepted by the installed CLI and returned state in the current authorized Herdr session.
- `herdr worktree open --help`: passed; confirmed supported `--workspace`, `--cwd`, `--path`, `--branch`, `--label`, and focus options.
- Manual acceptance cross-check: START/REENTER, PR-only Issue resolution, pre-edit gate, recovery states, lifecycle policy, and all required checklist scenarios are present.
- Automated tests and the runtime scenarios in the checklist were not run.

## Agent allocation

Use one implementation writer by default. Add an implementation agent only when the Issue breaks into independent, non-overlapping file or subsystem scopes. Give each writer a separate worktree/branch and a precise deliverable; the lead integrates its result into the Issue branch. Never let multiple writers edit the same worktree concurrently.

Use one independent reviewer for ordinary changes. Add a second reviewer when the Issue changes public/data contracts, security-sensitive code, or several subsystems. Reviewers must not edit, stage, commit, or run write-producing commands.

## Model and sandbox settings

Use the requested models when the installed CLIs support them. Check current CLI help if arguments have changed; do not silently substitute another model.

Codex implementer default:

```bash
herdr agent start implementer --kind codex --pane "$PANE_ID" -- \
  --model gpt-6-luna \
  --config 'model_reasoning_effort="high"' \
  --config 'service_tier="fast"' \
  --config features.fast_mode=true \
  --sandbox workspace-write \
  --ask-for-approval never
```

Agy is an alternative implementer:

```bash
herdr agent start implementer --kind agy --pane "$PANE_ID" -- \
  --model gemini-3.8-flash --effort high --mode accept-edits --sandbox
```

Do not use `--dangerously-bypass-approvals-and-sandbox` or `--dangerously-skip-permissions`.

Read-only Codex reviewer:

```bash
herdr agent start reviewer --kind codex --pane "$PANE_ID" -- \
  --model gpt-6-luna \
  --config 'model_reasoning_effort="high"' \
  --config 'service_tier="fast"' \
  --config features.fast_mode=true \
  --sandbox read-only \
  --ask-for-approval never
```

If the installed model or setting is unavailable, try the other user-approved implementation agent. If no approved agent can start, report that blocker rather than using an unapproved substitute.

## Handoff prompts

Give implementers the Issue link/number, repository instructions, acceptance criteria, non-goals, branch/worktree, assigned files, validation plan, and a requirement to report changed files and command results. Tell them to make only in-scope changes and not to push, create a PR, or merge; the orchestrator owns delivery.

Prompt reviewers with the Issue, acceptance criteria, full base-to-HEAD diff, and relevant repository instructions. Require findings in this form:

- Severity: blocker / high / medium / low
- File and line
- Concrete failure or unmet acceptance criterion
- Evidence and a focused correction

Explicitly instruct reviewers to remain read-only and report no findings when none exist. Codex's `--sandbox read-only` enforces the review boundary. Send tasks and findings through Herdr, for example `herdr agent prompt implementer "<scoped implementation task>" --wait` and `herdr agent prompt reviewer "<read-only review task>" --wait`. After review, send each actionable finding to the implementer with a focused fix request, then obtain a fresh reviewer response. Inspect `agent get`/`agent read` if a wait fails or an agent is blocked.

## Review and completion loop

1. Wait for the implementer to settle; inspect its status and full diff.
2. Start or prompt the reviewer after the diff is ready.
3. Relay each in-scope actionable finding to the implementer. Ask for a correction and evidence; do not ask the user to mediate.
4. Re-run the relevant validation and re-review the changed diff. Repeat up to three rounds.
5. Treat unresolved blocker/high findings or failed required validation as a stop condition. Medium/low suggestions that do not violate acceptance criteria may be recorded as limitations.
6. Before push, verify the worktree is clean, commits contain only Issue files, the base is `dev`, and no required validation was skipped. Summarize the pre-push state to the user, then continue without waiting because PR delivery was authorized.
7. Inspect the target repository's instructions and any applicable PR template. Use the conventions selected for that repository, preserving its required headings, checkboxes, and fields. Push the Issue branch and create or update one PR. If a PR already exists for the branch, update it instead of creating a duplicate. Inspect the resulting body against those conventions. Do not merge.

If Herdr reports an agent as blocked, inspect its state and output before sending anything. Continue only when the request is clearly within the Issue authorization; stop on approval requests outside that scope. Never answer a security or data-permission prompt by guessing.
