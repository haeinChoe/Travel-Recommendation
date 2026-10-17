---
name: travel-issue-agent-loop
description: "Use when a user names a repository Issue and authorizes implementation through a PR; coordinate implementation and read-only review agents using the active session's authorized workspace tools."
---

# Issue-to-PR agent loop

Run a complete, bounded implementation and review loop for an explicitly selected repository Issue. The trigger is a clear instruction such as “Implement Issue #123; PR is authorized.” Routine work inside that scope should proceed without asking the user for intermediate approval. Herdr-specific orchestration rules apply only when the active session is Herdr-managed or the user explicitly asks to use Herdr.

The session that receives the user's request is the **entry coordinator**. In Herdr sessions, use the configured `entry-readonly` profile and follow its read-only repository boundary; the Herdr socket, CLI, and MCP rules below apply there. In other sessions, follow that session's own permission and workspace rules, and do not assume Herdr access or profiles exist. The coordinator inspects scope and state, performs only authorized orchestration, relays revision requests to the assigned writer when needed, and verifies diffs and evidence within the active session's permissions. A separate **writer agent** owns mutable work when the active workflow requires one. Writer assignment is based on required capability, not on whether repository files change: any task that reads approved raw/actual data—including read-only diagnostics such as file existence/counts, directory structure, provenance/role mapping, or schema/header inspection—must be delegated to the dedicated **data-science agent** defined below. Use an **implementation agent** for product or experiment-harness code that does not require actual-data reads. **Review agents** are read-only. Do not describe these profiles as stronger filesystem isolation than they provide.

## Skill preflight

Before using any specialized workflow or tool, inspect the skill catalog available in the current session and read the full `SKILL.md` for every applicable skill, including its referenced resources. Issue/PR work requires this repository's `travel-issue-agent-loop` skill. Read the global `herdr` skill only when the active session provides Herdr and the work will invoke Herdr. Actual-data analysis, recommendation experiment design, or repeated dataset inspection additionally requires the repository-local `travel-data-scientist` skill. Do not assume or hardcode a global skill location. If Herdr is unavailable or not part of the active context, do not invoke it and do not block otherwise authorized work; use the available authorized workspace, Git, GitHub, and subagent capabilities, preserving the branch/worktree and permission boundaries. If an actually required skill for the selected execution path is missing, search available skill roots; stop only when that required path cannot be used safely.

## Technical failure recovery

Classify failures before retrying: transient network/service failure, timeout or stalled agent, invocation/context error, missing credential or permission, provenance/data uncertainty, or code defect. Inspect only safe status and bounded diagnostics. Retry only idempotent operations, at most twice with backoff; do not create a second writer or duplicate worktree while the original may still be active. Preserve branch, worktree, and uncommitted work. When an external dependency is unavailable, continue independent synthetic tests, code, and documentation work. Never widen permissions, bypass a review, or convert an unavailable credential/approval into assumed authorization.

For network and credential preflight, check only whether the specifically required credential is present; never print its value. Confirm network/DNS/TLS reachability and endpoint authorization/terms before a bounded, non-billable smoke request. Distinguish DNS/TLS/timeout, 401/403, 429, and 5xx outcomes. Do not issue keys, accept terms, or incur charges. If access is unavailable, record the safe failure class and continue offline where possible.

Debug logs must be secret-safe: never dump environment contents, shell history, headers, config files, credential-bearing URLs, raw rows, exact local paths, or identifiers. Report only variable names with present/missing state, URL host and path with query removed, status/error class, request ID when safe, and timestamp. Redact tokens and personal or source data before preserving diagnostics.

When an agent times out or appears stalled, read its status/output without starting another writer. Give one bounded extension or request a narrow progress/checkpoint update. If there is still no progress, stop the writer through its supported control, preserve its worktree, and report the last safe checkpoint and blocker. Do not silently discard or duplicate its changes.

Routine continuation prompts are auto-skipped when they ask whether to continue an already authorized, in-scope, reversible step and introduce no new decision. Continue without asking the user. Do not auto-skip requests involving new product/data policy, credentials or terms, billable access, expanded scope, destructive cleanup, security controls, or material ambiguity; report the precise decision needed.

## Data-root preflight

Before an actual-data run, read the selected experiment's reproduction command and the relevant AI Hub workflow, then resolve the approved dataset inputs in this order:

1. Use the required data-root variables when they are available in the current process. For the current popularity/CF reproduction recipe, these may include `RAW_ROOT`, `CAPITAL_TL`, `CAPITAL_VL`, `WEST_TL`, `WEST_VL`, `EAST_TL`, `EAST_VL`, `JEJU_TL`, and `JEJU_VL`.
2. If the required paths are unavailable from the current process, use bounded discovery only in local or mounted locations explicitly authorized by the selected Issue or `docs/data/aihub-workflow.md`, with a strict depth limit and role-marker checks.
3. Before opening candidate inputs, verify dataset provenance, approval/terms, expected region, and TL/VL role mapping against the Issue and repository documentation.

Environment variables are a convenience for resolving local paths, not a mandatory authorization gate. Do not treat unavailable variables as evidence that the data is absent, and do not require inspection of an existing interactive shell before using an otherwise authorized bounded discovery path. Do not scan an entire home directory or drive. Never print or copy variable values or local paths into output, prompts, logs, Git, or PRs. Stop actual-data processing only when the approved dataset cannot be resolved unambiguously or its provenance/role mapping cannot be verified.

## Before implementation

1. If using Herdr, verify `HERDR_ENV=1` and follow the global Herdr skill. Otherwise, skip Herdr-only inspection and orchestration steps and use the active session's authorized repository/worktree tools. Do not report absence of Herdr as an Issue blocker when another authorized route is available.
2. Read the repository `AGENTS.md`, `docs/agent-workflow.md`, and the selected Issue. Treat the Issue as the source for purpose, scope, non-goals, acceptance criteria, validation, and data permissions.
3. Determine whether the request requires any actual-data read. If it does, the entry coordinator stops before touching raw roots or TL/VL inputs and assigns a dedicated data-science writer. In Herdr sessions this is the `herdr-data-science` writer; in other sessions use the available authorized dedicated agent route. Immediately before its first actual-data read, that writer completes the data-root preflight above, using current-process variables when available or the authorized bounded discovery path otherwise. The entry coordinator must not resolve local raw paths, traverse raw/TL/VL directories, count files, inspect headers/schema, or validate provenance/role mapping against actual files itself. Continue code preparation, synthetic/unit tests, documentation, and experiment-harness work without this preflight only when those steps do not read actual data.
4. In a Herdr session, inspect Herdr server, workspace, and agent state before editing, following the authorized MCP/CLI rules below. In a non-Herdr session, skip Herdr inspection and check the clean/dirty state, current branch, existing Issue worktrees, and open PRs using the active session's authorized tools. In either route, reuse or resume same-Issue work rather than creating duplicates, and never overwrite another worktree's changes.
5. Do not start implementation if required scope, acceptance criteria, or data access permission is missing or contradictory. Use repository evidence to resolve routine details; do not invent data meanings, contracts, or architecture decisions.

## Herdr execution boundary

This section applies only in a Herdr-managed session or when the user explicitly requests Herdr. In every other session, skip these Herdr commands, MCP bridge checks, and profile-specific steps; use the active session's authorized repository, worktree, and agent capabilities instead. Keep the same branch isolation, data delegation, privacy, and authorization requirements.

Do not run Herdr CLI commands from an arbitrary repository or worktree cwd.

- Use the registered Herdr MCP bridge for supported inspection operations. If that inspection succeeds, do not repeat it with the CLI.
- `herdr pane list` and `herdr pane current --current` are optional discovery, not mandatory Issue-start preflight. If `HERDR_PANE_ID` and `HERDR_WORKSPACE_ID` are already set, do not call `pane current` only to reconfirm caller identity. An optional pane-discovery `EPERM` is not by itself an Issue-level blocker.
- When a CLI fallback is actually required, keep the coordinator in its approved orchestration execution context. Pass repository targets explicitly with documented arguments such as `--cwd "$REPO_ROOT"`; this argument identifies the repository to Herdr and does not require changing the shell cwd into that repository.
- For explicitly authorized state-changing Herdr commands with no MCP mutation equivalent (for example workspace/worktree creation, required pane creation/split, and agent start/prompt), use the global Herdr skill's approval-reviewed escalated execution route on the first attempt; do not probe them first in the ordinary command sandbox.
- Do not `cd` into a repository or worktree merely to invoke Herdr.
- After Herdr creates or resolves a worktree, verify the returned absolute path is inside the writable roots allowed by the selected writer permission profile before starting a writer agent.
- Implementation commands execute only in the exact worktree path returned by Herdr. Never guess, synthesize, relocate, or substitute a worktree path to recover from a permission error.
- If a denied CLI call used an invalid cwd or unapproved worktree path, do not retry that same call. Correct the orchestration boundary and continue only through an authorized path. If a state-changing command was wrongly attempted in the ordinary sandbox, use only its already-defined first-attempt approved route if that route has not yet been attempted; if the approved invocation is rejected or still returns `EPERM`, report the blocker and stop.
- Treat the failure as an Issue-level blocker only when the workflow requires that Herdr capability and it remains unavailable through every authorized route. A wrong cwd, unapproved path, or redundant CLI attempt is an orchestration configuration defect and must not stop the Issue by itself.
- Never introduce a new or broader permission route, sandbox bypass, force option, or unrestricted/default profile to recover from `EPERM`; the predefined approval-reviewed first-attempt route is not an `EPERM` recovery bypass.

## Worktree and agents

Create or reuse one dedicated Issue worktree and branch from `dev`, following `docs/agent-workflow.md` (normally `agent/<issue>-<slug>`), with the active session's authorized tools. Use Herdr only in a Herdr-managed session or when explicitly requested. The entry coordinator does not edit files in a writer-owned worktree. Assign a dedicated implementation writer for code that does not require actual-data reads and a dedicated data-science writer whenever approved raw/actual data must be read, even for a read-only diagnostic. In Herdr sessions, use the named `herdr-implementation` and `herdr-data-science` profiles; otherwise use the authorized agent route available in the active session. The assigned writer owns its in-scope edits, tests, analysis, and review fixes. Keep independent writers in separate worktrees and use one lead implementer to integrate parallel work.

The Herdr MCP bridge provides read-only inspection, a narrowly scoped `herdr_data_science_agent_start(workspace_id)` mutation, and guarded teardown tools. For data-science writer startup, use the guarded MCP startup tool first when it is registered and available; it owns linked-worktree verification, pane creation, fixed profile selection, and startup readback. Do not manually reproduce its `pane split` or `agent start` steps in the ordinary shell after an MCP startup failure. Use the existing authorized Herdr orchestration path for workspace/worktree creation, implementation/reviewer startup, prompts, or data-science startup only when the dedicated MCP startup tool is genuinely unavailable. Use `herdr_worktree_remove` or `herdr_workspace_close` only when the user or Issue explicitly authorizes cleanup and the guarded procedure in [references/agent-loop.md](references/agent-loop.md) is satisfied.

In Herdr sessions, use the path returned by Herdr and verify it against the selected profile's writable roots. In other sessions, use only a worktree path returned by that session's authorized repository workflow. If the path is inaccessible, identify the permission boundary before starting any agent; do not silently choose, move, or synthesize a custom location.

Do not infer that a workspace belongs to an Issue from its ID, focus state, or proximity alone. In Herdr sessions, reuse it only when the Issue branch, Git worktree path/branch, and Herdr metadata establish the mapping. In other sessions, establish reuse from the Issue branch and Git worktree path/branch using the active session's authorized tools. Prefer a pane returned by the authorized orchestration flow when using Herdr; do not require a global pane-list scan merely to find a shell pane.

Choose the number of agents to fit the task:

- Small, well-bounded Issue: one implementer and one reviewer.
- Medium Issue: one implementer and one reviewer; add an independent implementer only for non-overlapping work.
- Broad or high-risk Issue: a lead plus independent implementers in separate worktrees, and one or two reviewers.
- Simple read-only actual-data smoke/metadata inspection with no repository changes or experiment/contract judgment: one data-science writer is sufficient; a reviewer is optional unless the Issue or user requires one.

In Herdr sessions, use the configured `herdr-implementation` or `herdr-data-science` writer profiles and `entry-readonly` for reviewers. In other sessions, use the active session's authorized writer and reviewer capabilities. Never replace a required restricted profile with an unrestricted/default writer. Detailed Herdr commands, model settings, and handoff prompts are in [references/agent-loop.md](references/agent-loop.md).

## Data-science routing

When the selected Issue requires any actual-data read or asks whether a recommendation experiment is well-posed, route that work to a dedicated data-science agent and require the local [`travel-data-scientist` skill](../travel-data-scientist/SKILL.md). A repository mutation is not required to trigger this routing: file existence/counts, directory structure, provenance/role mapping, and schema/header inspection against raw/TL/VL inputs are all actual-data reads.

- In Herdr sessions, start the data-science agent with `herdr-data-science` and prefer the guarded `herdr_data_science_agent_start(workspace_id)` tool. If that guarded tool is unavailable or errors, follow the Herdr-specific failure rules below; do not bypass it through ordinary-shell CLI. In other sessions, use the authorized dedicated data-science agent route available there. If no safe dedicated route exists, defer only actual-data reads and continue independent synthetic/code/documentation work.
- The data-science agent owns problem framing, data-role/provenance checks, actual-data reads, privacy-safe analysis, experiment-design review, and the data-science handoff.
- Before executing an analysis request, it must check whether the product question, prediction time, label, features, cohort/split, baseline, and metric answer the same question. A technically runnable but misaligned experiment must be reported as such before execution.
- Observed visits may be treated as implicit positive interactions when the selected data contract permits it; unobserved items are not automatically negative. Negative sampling or exposure assumptions require an explicit experiment protocol.
- Post-event feedback must not be used as a recommendation-time input. Classification, retrieval, and ranking must be distinguished, and ranking questions should not be justified solely with classification accuracy.
- If the Issue also requires product or experiment-harness code changes outside the data-science scope, hand those changes to an implementation agent (`herdr-implementation` in Herdr sessions). Never run two writers concurrently in one worktree; serialize ownership or use separate confirmed worktrees.
- The entry coordinator remains read-only and must not take over the data-science role. It must not traverse raw roots or TL/VL inputs, count files, inspect schema/header content, or validate provenance/role mapping against actual files; delegate those checks to the dedicated data-science writer.

The permission contract, machine-local profile example, and validation boundary are documented in [`docs/data/data-science-agent.md`](../../../docs/data/data-science-agent.md).

## Autonomous review loop

Have the assigned writer (implementation or data-science) read the Issue, repository instructions, acceptance criteria, applicable role skill, and assigned scope before editing or reading actual data. It performs its authorized edits, tests/analysis, and review fixes in its assigned worktree. It may stage and commit only when the Issue or user authorization permits; it may push or create/update a PR only when explicitly authorized, and must never merge without separate authorization. The entry coordinator verifies the assigned writer's state, actual diff, and validation evidence read-only; it does not perform repository mutations.

Ask the read-only reviewer to inspect the Issue, acceptance criteria, and full diff. Relay actionable findings, and any user-requested revisions, to the existing assigned writer; have that agent make the fixes and request a fresh review. Do not apply findings in the entry session. Repeat for at most three review rounds. Do not treat an agent's “done” message as evidence: verify the diff, working tree, validation output, and review result yourself.

Do not ask the user about routine implementation choices. Continue through the authorized work. When delivery is authorized, the entry coordinator reports the pre-push summary, then delegates the permitted commit, push, and PR steps to that same assigned writer and inspects the resulting repository state and PR read-only. The assigned writer must follow all repository authorization gates, including commit permission, explicit push/PR permission, branch restrictions, and the prohibition on merging without separate authorization. Stop only for a real blocker: missing or conflicting requirements/permissions, unavailable required access, a security concern outside the authorization, or an issue that remains unresolved after three review rounds.

## Maintenance fast path

When an approved Issue is blocked by a small repository-operation or agent-workflow defect, apply the repository's **유지보수 신속 경로** only when every eligibility condition in `docs/agent-workflow.md` is satisfied.

- The user's explicit phrase `유지보수 게이트로 처리` authorizes the eligible blocker change, validation, **dedicated maintenance workspace/worktree and branch creation**, validated commit, maintenance-branch push, and maintenance PR creation for that blocker only. It does not authorize merge, force push, or direct writes to `dev`/`main`.
- Preserve the blocked Issue's existing `agent/<issue>-<slug>` worktree and branch. Do not repurpose that worktree for maintenance edits, because its unmerged Issue changes must not enter the maintenance PR.
- Create the maintenance work in a separate worktree based on `dev`, using branch `agent/<blocked-issue>-maintenance-<slug>` and the maintenance-isolation procedure in `references/agent-loop.md`. This is an explicit isolation exception to ordinary same-Issue workspace reuse; the blocked Issue remains the traceability anchor and no replacement Issue is created.
- Use `.github/PULL_REQUEST_TEMPLATE/maintenance.md` and record the blocked Issue, blocked Issue branch, maintenance branch, scope, non-goals, validation, and resume steps.
- Run `scripts/maintenance/validate-fast-path-scope.ts` against the maintenance-branch changed file list. Passing the path check is necessary but not sufficient: product, data, preprocessing, evaluation, API, DB, domain, recommendation, or model semantics must remain unchanged.
- If the change is outside the allowlist or its semantic impact is uncertain, stop using the fast path and elevate it to a normal Issue.
- After an authorized maintenance PR is merged into `dev`, identify the exact **original blocked Issue worktree/branch mapping**, return to that worktree, fetch, and merge `origin/dev` into the original Issue branch. Do not resume the Issue in the maintenance worktree, and do not make rebase/force-push the default resume mechanism.

This is not a break-glass path. It does not bypass branch protection, required validation, review, the repository's separate merge-authorization rule, or the worktree-isolation rules.

## Authorized cleanup

Clean an Issue workspace only when the user explicitly requests cleanup or the Issue authorizes it. Follow the separate linked-worktree removal, linked workspace-session closure, and plain-workspace closure procedures in [references/agent-loop.md](references/agent-loop.md). Confirm the Issue-to-workspace-to-worktree-to-branch mapping, merged PR or explicit abandonment, caller/focus protection, no remaining task need, and settled agents before any operation.

For `herdr_workspace_close` on a linked workspace session, verify one exact Herdr workspace/path/branch mapping against Git, ensure the target is neither caller nor focused and its agents are settled, then verify the bridge's before/after snapshots preserve every peer ID, identity, focus, and repository provenance. Herdr may omit at most one derived `open_workspace_id` association from a peer's linked-worktree row when it referred to the closed session; preserve the row's path, branch, linked flag, and all other metadata. Git worktree and full checkout status snapshots must remain unchanged. This closes only the session and preserves its checkout, including dirty, untracked, and ignored files. Use only this guarded MCP tool path; never substitute CLI, group-close, raw API, force, or blind retries. For `herdr_worktree_remove`, a linked checkout's shared Git common directory is normal and is not, by itself, a reason to refuse removal. Verify that the exact linked checkout is clean, including untracked and ignored files, and is not on a protected branch. Plain workspace closure has separate provenance and primary-checkout ownership/cascade guards; do not apply those plain-close rules to linked-session closure or linked worktree removal.

Use only the guarded MCP teardown tools. If a call is refused or ambiguous, reread Herdr inventories and Git state, then report the exact blocker and preserve unresolved state. Do not bypass the refusal through CLI, raw APIs, group-close, force options, or blind retries. Report linked-session closure complete only after Herdr readback confirms the target session is absent and its checkout path, branch, worktree listing, and full status are unchanged. Report linked-worktree removal complete only after Herdr and Git readback confirm the requested target is absent. After a successful linked-worktree removal, delete a merged local branch only with non-force `git branch -d` when no worktree still uses it; verify the local branch is absent and leave the remote branch untouched.

## Delivery

The assigned writer prepares repository changes and, when separately permitted, staging and the local commit. The entry coordinator inspects the worktree and proposed delivery state read-only, then reports the required pre-push summary: commit log (if committed), changed files, validation results, and remaining limitations. If push/PR permission is explicit, delegate the authorized push and PR creation/update to that same assigned writer; do not perform those repository mutations in the coordinator session. The assigned writer pushes only the Issue branch and creates or updates its PR. Never push directly to `dev` or `main`; never merge, deploy, or delete worktrees unless separately authorized.

Before creating or updating a PR, the coordinator reads the target repository's instructions and any applicable PR template, then gives those conventions to the assigned writer. The assigned writer follows them; the coordinator inspects the resulting PR body and state read-only.

Finish with the branch and PR links, implementation summary, reviewers and rounds, validation performed, and any unresolved blocker. Leave the Issue worktree available for follow-up unless the user requested cleanup.
