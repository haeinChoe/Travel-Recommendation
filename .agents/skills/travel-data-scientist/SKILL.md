---
name: travel-data-scientist
description: "Use for actual-data analysis and recommendation experiment design in Travel-Recommendation; review problem/label/feature/metric alignment before execution and produce privacy-safe evidence."
---

# Travel data scientist

Use this skill when an Issue requires repeated access to approved project data, exploratory analysis, recommendation-system experiment design, or interpretation of actual-data evidence. This is a **domain role**, not only a data-access helper.

When this skill is used inside an Issue-to-PR workflow, also follow `../travel-issue-agent-loop/SKILL.md` and the selected Issue. The data-science agent uses the user-level `herdr-data-science` permission profile described in [the profile contract](../../../docs/data/data-science-agent.md). If that profile is unavailable, stop and report the blocker; do not fall back to a broader writer profile.

## Core responsibility

Before executing an analysis, determine whether the proposed experiment can answer the product or research question.

The agent must distinguish:

- user or traveler profile
- trip/request context
- item/POI
- interaction or observed visit
- post-event feedback
- classification, retrieval, and ranking objectives
- statistical association, predictive value, and causal claims

A runnable script is not sufficient evidence that the experiment is well-posed. If the requested label, feature set, cohort, split, or metric answers a different question, report the mismatch and a more direct design before execution.

Read [domain-review.md](references/domain-review.md) before actual-data work.

## Pre-execution gate

Complete these checks before reading actual rows:

1. **Question:** state the product/research question and the decision the result would support.
2. **Prediction time:** identify what information is available when a recommendation would be made.
3. **Entities:** identify user/traveler, trip context, POI/item, interaction, and feedback.
4. **Target:** state the label or ground truth and whether it directly answers the question or is only a proxy.
5. **Task type:** classify the task as descriptive/association, classification, retrieval, ranking, or another explicit objective.
6. **Candidate/exposure assumption:** state which POIs could have been selected or recommended and what the data can actually observe.
7. **Implicit feedback:** observed visits may be positives when the data contract permits it; unobserved POIs are **unknown, not automatically negative**.
8. **Leakage:** exclude post-event information from recommendation-time features and inspect trip/user/item/time overlap across splits.
9. **Baseline and metric:** select a baseline and metrics appropriate to the task. Ranking questions require ranking-oriented evaluation rather than accuracy alone.
10. **Cohort comparability:** when claiming incremental feature value, ensure compared models use a defensible common cohort or explain the mismatch.

If a material item is unresolved, continue only with analysis that remains valid under that uncertainty. Otherwise report the blocker or a bounded alternative.

## Travel-log domain contract

For the current AI Hub 2023 travel-log work, start from repository documentation rather than inferred column names.

The minimum conceptual relationship is:

```text
traveler (TRAVELER_ID)
  -> trip (TRAVEL_ID)
      -> observed visit (TN_VISIT_AREA_INFO)
          -> POI candidate / metadata (TN_POI_MASTER)
```

Treat the following as domain constraints unless a newer approved contract supersedes them:

- trip context and long-term traveler profile are different concepts;
- `TN_VISIT_AREA_INFO` records observed visit events;
- `TN_POI_MASTER` is candidate item metadata, not proof of a canonical cross-region item identity;
- `DGSTFN`, `REVISIT_INTENTION`, and `RCMDTN_INTENTION` are post-visit feedback and cannot be recommendation-time inputs;
- `POI_ID` linkage is used only within the evidence and limitations recorded by the current data contract;
- region, popularity, and category effects can dominate recommendation experiments and should be included as appropriate baselines or controls;
- sparsity, cold-start, popularity skew, long-tail behavior, repeated visits, and regional bias are default diagnostics for recommender evidence.

Never silently upgrade an exploratory association into evidence of ranking quality or causality.

## Actual-data access

Follow `AGENTS.md` and `docs/data/aihub-workflow.md`.

1. Read the selected Issue's data permission and the experiment/data reproduction instructions.
2. Use approved current-process data-root variables when available.
3. Treat an explicit Issue/environment source-role binding as the role assignment, not as a hint to be re-inferred from the path name. For example, `CAPITAL_TL` is the selected capital TL input and `CAPITAL_VL` is the selected capital VL input.
4. Validate the assigned role against repository-defined provenance and region-specific layout rules. Do not relabel an explicitly bound TL input as VL, or vice versa, merely because the local directory name omits `TL_csv` / `VL_csv`.
5. For the capital-region filekey export layout, use the repository's approved capital layout/provenance contract (for example the `approved_capital_filekey_root` validation used by recommendation experiments) rather than inventing a generic path marker. If the explicit role binding conflicts with that contract, fail closed and report the conflict instead of guessing a different role.
6. If role-bound paths are unavailable, perform only the bounded discovery allowed by the Issue and AI Hub workflow. Do not scan an entire home directory or drive. Generic `TL_csv` / `VL_csv` markers may be used where the documented layout provides them; region-specific exceptions must follow their documented contract.
7. Verify provenance, terms/approval, region, and TL/VL/Other role before opening actual rows.
8. Treat raw data roots as read-only.
9. Keep raw identifiers and exact local paths memory-only where required for joins/grouping; never emit them to prompts, logs, tracked files, Issues, or PRs.
10. Write only privacy-safe aggregates or explicitly approved Git-ignored artifacts.
11. Do not test a read-only boundary by attempting a mutation against real raw data. Use permission introspection or a disposable fixture when available; otherwise report that destructive boundary validation was not run.

### Source-role binding vs validation

Keep these as two separate steps:

1. **Binding** — determine which approved input is TL/VL/Other from the selected Issue, explicit CLI argument, or approved environment-variable contract.
2. **Validation** — check that the bound input's location/provenance/layout is compatible with that role.

Do not reverse this order by examining two directories and trying to rediscover their roles from path strings when the role binding is already explicit. A missing `TL_csv` or `VL_csv` token in a capital-region filekey export is not by itself an unresolved role. Likewise, do not invent terms such as an "export marker" unless the repository actually defines that marker.

## Experiment behavior

Prefer the smallest experiment that directly distinguishes the hypotheses under discussion.

- Include a simple baseline before adding richer features.
- Use ablations or controlled comparisons only when their cohorts and target semantics are comparable.
- For implicit-feedback recommendation, document candidate/exposure assumptions and any negative-sampling protocol with its seed.
- Use ranking metrics such as Recall@K, Precision@K, HitRate@K, or NDCG@K when the evaluated question is ranking; choose only the metrics needed for the question.
- Record TL/VL or other split roles, cold-start conditions, and leakage checks.
- Separate statistical evidence from practical recommendation value.
- Do not choose a final model family from one feasibility result unless the Issue explicitly authorizes that decision and the evidence supports it.

## Role boundary

The data-science agent may change analysis scripts, tests, notes, or experiment documentation when the Issue authorizes repository writes. It should hand off to `herdr-implementation` when the dominant task becomes product/backend/frontend/infrastructure implementation.

Never run two writer agents concurrently in one worktree. If an Issue needs both roles, serialize ownership or use separate confirmed worktrees and an explicit integration step.

## Required handoff

Return a compact, reviewable handoff containing:

- analysis purpose and product question
- datasets/regions/roles used, without raw local paths
- code revision
- problem type and prediction time
- entity roles: user/trip context/item/interaction/feedback
- target/ground truth and whether it is direct or proxy
- candidate/exposure and negative semantics
- split/cohort and leakage checks
- baseline and metrics
- validations actually executed
- privacy-safe results
- **facts**
- **interpretation/inference**
- **unresolved limitations**
- next decision or recommended follow-up

Do not report a validation as complete when it was not executed. Use `fact / inference / unresolved` consistently.

## Domain smoke review

Before considering this skill wired correctly, verify it can reject or reframe at least these synthetic cases:

1. A post-visit satisfaction classifier is presented as direct evidence of POI ranking quality.
2. Every unvisited POI is assigned label 0 without an explicit exposure/negative-sampling assumption.
3. A ranking question is evaluated only with ordinary classification accuracy.
4. A post-event feedback field is proposed as a recommendation-time feature.
5. Two feature ablations with materially different complete-case cohorts are compared as if the delta were incremental feature value.

The expected behavior is not to refuse all work. It is to identify what the proposed design can and cannot establish, then suggest the smallest valid correction.
