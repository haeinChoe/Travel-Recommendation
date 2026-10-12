# Context × POI signal feasibility experiment

Issue #45 defines this as a reproducible feasibility check before any context-aware ranking work. It tests statistical association and held-out predictive signal. It does not estimate causal effects.

The field scope follows the [recommendation training-data contract](../training-data-contract.md), the [2023 regional schema index](../../data/travel-log-2023/README.md), the [popularity baseline](popularity-baseline.md), and the [CF feasibility protocol](cf-baseline.md).

## Current execution status

Approval for the four 2023 regional datasets and the applicable AI Hub terms are recorded under [Issue #12](../../data/eda-travel-log-2023.md). The established Issue #31 TL/VL role mapping was exercised in PR #40's clean four-region runs; the [CF results](cf-baseline.md) record successful execution and zero TL/VL trip-ID overlap in every region and overall, alongside parity with the prior popularity baseline. The Issue #45 run completed locally as `context-poi-20261012-9c0b12` after the coordinator verified the original-shell preflight and approved source evidence. Bounded marker-only discovery under the mounted project-pilot data tree resolved the established four-region role folders. Header, containment/symlink, join-quality, and within-region TL/VL overlap checks passed; there were four regional TL roles and four external VL roles, with zero trip-ID overlap. Input paths and capital filekey values were not recorded. Run artifacts remain under the ignored local results directory and are not committed.

The run produced 4 observed context/POI association rows; 299 were k=10-suppressed, 116 had insufficient support, and one had sparse expected cells. All region-specific association rows lacked sufficient support or were suppressed; the four observed rows were from the pooled-region scope. Median Cramér's V among those four rows was 0.1704. Feedback associations had 20 observed rows (pooled-region scope), 855 k=10-suppressed rows, 174 insufficient-support rows, and one sparse-expected row; their median Cramér's V was 0.0268. All 180 joint context × POI × feedback distribution tables were suppressed at k=10. These summaries are descriptive, not causal, and chi-square p-values remain descriptive only.

All 60 feedback ablation scores were available. Across 15 scope × outcome comparisons, context+POI had higher (worse) mean log loss than popularity-only in all 15 (mean difference +0.1124), and higher loss than POI-only in all 15 (+0.0976). This provides no held-out evidence for advancing context+POI in #41.

## Hypotheses and feature scope

The primary hypothesis is that documented trip context and visit-area attributes have measurable associations and can improve held-out prediction of each post-visit feedback field over popularity-only or single feature-family baselines. The script uses only fields whose join path is explicit in the current schemas/contracts:

| Role | Included fields | Handling |
| --- | --- | --- |
| Trip context | `TN_TRAVEL.TRAVEL_MISSION`, `TRAVEL_START_YMD` month | Mission is a categorical value; month is parsed from the documented `YYYY-MM-DD` date form. It does not infer season or ordinal meaning. |
| POI / area | region source label, `TN_VISIT_AREA_INFO.SGG_CD`, `VISIT_AREA_TYPE_CD` | The region label and visit-area attributes are kept distinct; input codes remain categorical and are not cross-walked. |
| Popularity | `POI_ID` grouped by `(region, POI_ID)` in TL | A region-scoped visit-frequency band only. `POI_ID` is never a model feature or output value. For a TL feedback row, visits from its own trip are excluded from its popularity feature. VL popularity uses TL counts only. |
| Post-visit outcomes | `DGSTFN`, `REVISIT_INTENTION`, `RCMDTN_INTENTION` | Kept as three separate 1–5 categorical targets. No value is used as an input; no ordinal direction or common composite scale is assumed. |

`TRAVEL_MISSION` is named “individual mission” in the regional schema. Both `TRAVEL_MISSION` and `TRAVEL_START_YMD` are optional schema columns. Their availability is recorded per region/role in `column_availability.csv`; if either header is absent or partial, dependent context associations and ablations are marked unavailable rather than failed or populated with synthetic missing categories. When present, mission is treated as a category and month is parsed from the date without inferring category semantics. Travel-style/motive profile fields, companion fields, trip duration, and `TN_POI_MASTER` categories remain excluded: their serving availability, aggregation rules, or visit-to-master join are unresolved in the training-data contract. The schema says names and required flags do not establish key constraints. In particular, this experiment does not join `TN_POI_MASTER` to a visit using a guessed `POI_ID` relation.

## Outcomes and statistical tests

Observed visit rows are positives only. They are used for context × area contingency tests, not as “preference” labels. For each context/area pair, the script reports a safe contingency support table, Cramér's V, and a chi-square reference p-value when support and expected-cell assumptions allow it. The output field is named `p_value_descriptive`: repeated visits are clustered within trips, so ordinary row-level chi-square p-values are not calibrated independent-row inference. They are descriptive only, are not corrected for multiple comparisons, and are excluded from any #41 Go criterion. Contingency labels are opaque category indexes local to a region/role/feature/popularity group; raw category strings and area codes are not written. It reports each region and all-region scope separately, for TL and VL separately, and repeats associations within TL-derived popularity bands. The all-region view keeps region as an explicit POI feature; within-region views check whether an aggregate pattern is confined to one region. Small cells are suppressed at k=10; sparse expected cells are marked instead of assigned a p-value. Results are event-weighted and descriptive.

Each feedback field is separately checked for missing, documented 1–5, and out-of-range categories, plus its category distribution across each included context/area feature. These checks run separately for each region and role, with an additional pooled-region view that retains region as an explicit area feature. Feature/outcome category labels in cross tables are opaque indexes, and small category counts and test cells are suppressed at k=10.

`feedback_context_poi_distributions.csv` adds joint context × POI × feedback contingency distributions for each of the three outcomes separately and every included context/POI feature pair. Context, POI, and feedback categories are represented only by opaque indexes. If any observed joint cell has support below k=10, the entire feature-pair/outcome table is suppressed; missing optional context, POI, or feedback headers are marked unavailable. This artifact reports distributions only and does not add inferential p-values.

The visit-only data does not identify non-visits, opportunity-to-visit, or a negative sampling universe. Accordingly, no binary visit classifier, visit ranking metric, or claim about unobserved POI relevance is produced. Treating an unobserved POI as a negative would change the label contract and is not authorized by #45.

## Predictive ablations

The script fits a deterministic categorical Naive Bayes model for each feedback outcome independently. This is a small predictive diagnostic, not a recommender or ranking model. It evaluates mean multiclass log loss on VL after fitting on TL, with a separate all-region fit and per-region fits. Missing optional feature/label headers are recorded in `column_availability.csv`; dependent analyses and ablations are marked `unavailable_missing_column` instead of treating absent columns as all-missing values. The four feature sets are:

1. popularity-only frequency band;
2. context-only mission and start month;
3. POI-only region, administrative-area code, and visit-area type;
4. context plus POI features.

Popularity is computed from TL, never VL. No TL/VL merge, random resplit, hyperparameter search, negative sampling, or row-level artifact is created. Insufficient train/validation support and any outcome class with support below k=10 are suppressed. An ablation is also suppressed when a VL outcome class has no TL support; it is not scored using an arbitrary probability floor. Log loss is not interpreted as a ranking metric. Compare context+POI against popularity-only and POI-only on the same VL role and report whether the direction is consistent across regions. The popularity-band association checks provide a coarse within-popularity sensitivity analysis; they do not eliminate all popularity confounding. A stronger claim needs a separately approved model/estimand.

## Leakage and privacy checks

- `TRAVEL_ID` joins visit rows to trip context in memory and groups TL events to remove the current trip's events from its popularity feature. It is never included in a feature vector or serialized.
- `POI_ID` is only a region-scoped grouping key for popularity, and is never included in a feature vector, log, metadata, or result file.
- `VISIT_AREA_ID` and traveler IDs are not used as features. No traveler identifier or trip identifier is written.
- Required ID/join headers are checked before any data rows are loaded. Optional candidate and trip-context columns (`TRAVEL_MISSION`, `TRAVEL_START_YMD`, `POI_ID`, `SGG_CD`, `VISIT_AREA_TYPE_CD`, and the three separate feedback labels) are reported as available, partial, or missing for each region/role/table.
- Feedback is the prediction target only. Feedback fields, `REVISIT_YN`, visit order/time, names, coordinates, GPS, photos, captions, and consumption/event fields are not predictors.
- The runner requires one TL and one VL folder for each of the four regions because regional consistency is part of this experiment. Source validation follows the established `evaluate_popularity.py`/`evaluate_cf.py` contract: every folder must exist under `--raw-root`, be distinct, and be named for its role (`TL_csv`/`VL_csv`); approved capital filekey folders are accepted only with `--allow-approved-capital-filekey-folders`. The runner does not infer region identity from a directory path. `capital`, `west`, `east`, and `jeju-islands` labels come from the explicit `--input` role mapping, which must be locally verified against the approved Issue #31 mapping before reading data. Paths and folder names are never written to reports. TL is training/development; VL is external replication. The code does not merge source roles or split rows.
- Before analysis, `TRAVEL_ID` values are compared between TL and VL independently within each region. Any overlap aborts the run and reports only the region and a `<10` or `10+` count bucket; IDs and paths are never included in the error.
- Before analysis, trip-context join integrity is checked per source role: missing travel IDs, trips with missing available context values, conflicting contexts for one trip ID, and visit rows with no unambiguous matching trip are counted separately. Any issue fails closed before feature analysis. The error contains only `<10`/`10+` buckets and region/role labels; it never contains identifiers or paths, and no unjoinable rows are silently dropped.
- Results contain documented feature/outcome names, opaque category indexes, support bands, effect sizes, descriptive-only p-values, and aggregate log loss only. Small supports are suppressed at k=10. Raw category values, IDs, paths, filenames, and capital role-folder names are excluded from output metadata.
- The runner requires explicit confirmation flags for dataset approval, terms, the original-shell preflight, and provisional POI-candidate handling. These flags record the operator's completed checks; they do not discover approval or inspect another shell.

Limits include non-random exposure to places, trip-clustered visits, uncertain serving-time availability of survey/date context, provisional `POI_ID` identity, incomplete POI metadata linkage, missing/out-of-domain feedback, and observational confounding. Effects and predictive feature associations are not causal explanations.

## Reproduction

First read the selected source-role contract and inspect the following variables in the user's actual local shell, including non-exported variables: `RAW_ROOT`, `CAPITAL_TL`, `CAPITAL_VL`, `WEST_TL`, `WEST_VL`, `EAST_TL`, `EAST_VL`, `JEJU_TL`, and `JEJU_VL`. Record only set/unset, target existence/type, and expected TL/VL role structure; never print values or paths. Verify the four 2023 dataset identities, #12 approval and terms, and TL/VL roles before opening any CSV. This worktree shell is not a substitute for that check.

After those checks pass, set local shell variables to the already-approved role folders using the same TL/VL role mapping as the Issue #31 popularity/CF runs. The evaluator contract requires role folder names, containment under `RAW_ROOT`, and distinct TL/VL paths; it does not derive region identity from folder location. Approved capital filekey folders use the established TL/VL mapping and require `--allow-approved-capital-filekey-folders`. Supply the locally verified `CAPITAL_TL` and `CAPITAL_VL` folders. The command below uses local shell variables:

```bash
RUN_ID="context-poi-2023-YYYYMMDD"
python3 scripts/recommendation/experiment_context_poi_signal.py \
  --raw-root "$RAW_ROOT" \
  --input "capital:TL=$CAPITAL_TL" --input "capital:VL=$CAPITAL_VL" \
  --input "west:TL=$WEST_TL" --input "west:VL=$WEST_VL" \
  --input "east:TL=$EAST_TL" --input "east:VL=$EAST_VL" \
  --input "jeju-islands:TL=$JEJU_TL" --input "jeju-islands:VL=$JEJU_VL" \
  --allow-approved-capital-filekey-folders \
  --output "results/experiments/context-poi-signal/$RUN_ID" \
  --run-id "$RUN_ID" \
  --confirm-approved --confirm-terms --confirm-user-shell-preflight \
  --confirm-poi-candidate
```

Use a fresh run ID. The output is under the ignored `results/experiments/context-poi-signal/` path and contains `associations.csv`, `context_poi_distributions.csv`, `column_availability.csv`, `feedback_distributions.csv`, `feedback_cross_distributions.csv`, `feedback_context_poi_distributions.csv`, `feedback_associations.csv`, `feedback_ablations.csv`, and `run_metadata.json`. The metadata records the dataset/version, roles, split policy, seed (none), code revision/dirty state, script hash, run times, outcome list, and privacy threshold without recording input paths, source filenames, or filekey values.

Synthetic-only validation:

```bash
python3 -m unittest tests.test_context_poi_signal -v
```

## #41 recommendation

Recommend **Reconsider** for #41 based on this run: regional context/POI tests did not have sufficient support, all joint context × POI × feedback distributions were suppressed, and context+POI worsened held-out feedback log loss against both popularity-only and POI-only in all 15 comparisons. Do not use descriptive row-level chi-square p-values as evidence for Go. A future Go decision would require supported, regionally consistent patterns and context+POI improvement over both baselines under the documented leakage checks; it would remain associational rather than causal.
