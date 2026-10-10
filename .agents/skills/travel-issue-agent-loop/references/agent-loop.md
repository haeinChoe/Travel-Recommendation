# Herdr implementation and review procedure

Read this reference when running the Issue-to-PR loop.

## Reuse before creating

Inspect the Herdr server, workspaces, and agents before editing or creating work. In the current session, use the registered read-only Herdr MCP bridge first when its tools are available:

- `herdr_server_status`
- `herdr_workspace_list`
- `herdr_agent_list`

If the bridge is unavailable or any MCP call fails, use the approved read-only CLI fallback:

```bash
test "${HERDR_ENV:-}" = 1 || exit 1
herdr status server
herdr workspace list
herdr agent list
herdr worktree list --cwd "$REPO_ROOT"
```

If the CLI path cannot complete the required state inspection, report the blocker before editing or creating work. Do not assume state that could not be inspected.

Also check the Issue's open PRs and the repository's local branches/worktrees. Match work by Issue number and branch. If the same Issue is active, resume its workspace and agent. Do not close or repurpose unrelated workspaces. If Herdr state cannot be read, retry read-only inspection with the available authorized execution context and search Codex sessions when that tool is available. Do not create a new workspace while same-Issue work may still be active.

If no matching work exists, create an unfocused Issue workspace and worktree. Read all IDs and paths from Herdr's JSON response; never guess IDs:

```bash
herdr workspace create --cwd "$REPO_ROOT" --label "issue-<N>" --no-focus
herdr worktree create --workspace "$WORKSPACE_ID" \
  --branch "agent/<N>-<slug>" --base dev --label "issue-<N>" --no-focus
```

Omit `--path` to use Herdr's configured worktree root and branch-derived directory name. If the returned path is outside the allowed write roots, identify the boundary and follow the repository or session's approved alternate-root procedure before starting agents. Do not silently select a custom path.

The MCP bridge is read-only. Use the existing authorized Herdr orchestration path for workspace or worktree creation, agent start or prompts, and pane control; never use MCP for mutations.

Use the worktree returned by Herdr for the implementation branch. Confirm its branch, base, and clean state before starting agents. Use the returned shell pane when it is at an interactive prompt; otherwise split a pane with the worktree path as cwd and `--no-focus`. Start agents only in returned pane IDs and use unique names. Never start two agents in one pane.

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
