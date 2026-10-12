# Context × POI signal feasibility

**Issue:** [#45](https://github.com/haeinChoe/Travel-Recommendation/issues/45)

**Status:** approved four-region local-data run complete; privacy-safe aggregate review supports an **Inconclusive** conclusion.

## Purpose and contract

This exploratory and predictive feasibility analysis asks whether documented travel context and observed POI representations contain reproducible associations. It does not estimate causal effects, choose a serving contract, or validate a production ranking system. It follows the [recommendation training-data contract](../training-data-contract.md) and the four 2023 regional schema guides.

- `TL_csv` is discovery/training and `VL_csv` is replication/validation. The script rejects overlapping `TRAVEL_ID` values in each region and never randomly re-splits the roles.
- A nonblank visit `POI_ID` is only a region-scoped candidate key. Matching it exactly against `TN_POI_MASTER.POI_ID` is an empirical candidate join. It does not establish a canonical POI, PK/FK contract, or cross-region identity.
- The script uses only fields named in the documented allowlist. Raw category values are kept in memory as opaque strings; code meanings are not inferred from their values. `TRAVEL_MISSION` remains audited but excluded from analysis while its representation is unresolved.
- `DGSTFN`, `REVISIT_INTENTION`, and `RCMDTN_INTENTION` are analyzed as three independent post-visit targets. Their values are treated as nominal response codes; they are never averaged, interpreted as future behavior, or used as input features.
- `TRAVELER_ID`, `TRAVEL_ID`, `VISIT_AREA_ID`, and `POI_ID` are memory-only join/group keys. Names, addresses, exact dates, coordinates, free text, companion raw values, row records, and category values are not written to results.
- Unvisited items are not negative labels. No ranking metric is produced.

## Features and candidate joins

Availability is audited by region and role for:

- `TRAVEL_STYL_1`–`TRAVEL_STYL_8`, `TRAVEL_MOTIVE_1`–`TRAVEL_MOTIVE_3`, destination, and companion status/count from `TN_TRAVELLER_MASTER`.
- `TRAVEL_MISSION`, `TRAVEL_START_YMD`, and `TRAVEL_END_YMD` from `TN_TRAVEL`. Month is derived from the start date. Duration is represented only as the elapsed calendar-day difference `end - start`; this does not assert an inclusive trip-day definition. No season mapping is defined by the cited schema, so season is reported as unresolved.
- Companion relation codes from `TN_COMPANION_INFO`, grouped by the documented candidate `TRAVEL_ID` relation. No companion row is not interpreted as proof of no companions.
- `VISIT_AREA_TYPE_CD` and visit `SGG_CD` from `TN_VISIT_AREA_INFO`.
- `SGG_CD`, `ASORT_LCLASDC`, `ASORT_MLSFCDC`, and `ASORT_SDASDC` from `TN_POI_MASTER`. POI names, business identifiers, addresses, and coordinates are never loaded.
- `GENDER` and `AGE_GRP` are audited and analyzed in separate descriptive associations. They are excluded from the primary predictive feature sets and do not define the core hypothesis.

The audit reports role-level missingness/cardinality buckets and candidate join coverage, master-key uniqueness/duplicates, visit-key reuse across visit rows, multiple-`SGG_CD` keys, category-field availability, and cross-region candidate-ID collisions. POI candidate coverage counts every visit row with a nonblank candidate `POI_ID`, independently of whether that row resolves to a unique trip; trip-link coverage is reported separately. Only a unique exact candidate key is used to attach POI master metadata to an analyzed visit. All join conclusions remain scoped to the observed files and region.

## Analysis protocol

### Feature and join audit

`availability_audit.csv` contains field-level `0`, `<10`, or `10+` count buckets, coarse missing-rate bands, cardinality buckets, category-support distribution buckets, and candidate join diagnostics. For each feedback target and region/role it also reports missingness, cardinality, and counts/cardinality for values outside the schema-documented 1–5 code range, with values treated as opaque and never emitted. It does not contain raw code values. A missing table or unusable join is explicitly marked unavailable; it is not silently replaced with another identity or source.

### Context ↔ POI association

`associations.csv` reports Cramér's V and Pearson chi-square p-values for observed categorical context/POI pairs, each feedback target separately, and context × POI joint categories against each feedback target. It also compares region, TL-derived popularity band, and broad POI category/visit type against each feedback target. Results include both visit-row weighting and deduplicated trip × feature-pair support for context-to-POI associations.

Small-support statistics are not emitted. `privacy-limited` means a computable statistic is withheld by the `k=10` publication threshold. `insufficient-support` means there are no usable observations or fewer than two observed categories on either side. These are separate statuses. Trip-grain sensitivity deduplicates by region, role, `TRAVEL_ID`, and feature pair, without requiring `TRAVELER_ID`; the bucketed count of otherwise usable pairs excluded for missing trip IDs is reported separately. P-values are descriptive; effect size, support, regional patterns, and TL-to-VL replication must be considered together. Visit-level chi-square results do not correct for repeated observations within a trip.

The joint-category association is descriptive and predictive. It is not an interaction causal effect. Within-region outputs and aggregate outputs are both retained so region-only association can be inspected separately from within-region patterns.

### Predictive ablation

`predictive_ablation.csv` evaluates the three feedback targets independently with a deterministic categorical Naive Bayes model. It uses exact observed response codes as nominal classes, Laplace smoothing `alpha=1`, and no hyperparameter search. Models are trained on TL and evaluated on VL. Each ablation uses its own complete-observed feature/target rows; no value is imputed. The majority class is selected from that ablation's TL training counts, then its accuracy is measured on the same valid VL evaluation pairs as the model, using the VL support as denominator. The table reports support buckets, model accuracy, this VL constant-prediction baseline, and their difference, with metric values withheld below `k=10`.

The feature groups are:

1. `popularity_only`: TL-only frequency band for the region-scoped candidate item; the item ID itself is not a feature.
2. `poi_only`: region, visit-area type/district, and uniquely joined POI master metadata.
3. `context_only`: documented style/motive/destination/companion candidates and the derived month and elapsed-day value.
4. `context_plus_poi`: context plus visit-area type and district.
5. `context_plus_richer_poi`: context plus visit-area and POI master categories/district.

Each ablation's support is reported because optional-feature coverage can differ. `common_cohort_sensitivity.csv` also intersects VL observations that have the target and every feature in `context_only`, `context_plus_poi`, and `context_plus_richer_poi`; each model still uses its own complete-case TL training rows. It reports bucketed TL and identical common-VL support and suppresses all metrics below `k=10`. Accuracy deltas across the ordinary ablations use different cohorts and are not controlled incremental effects. Feedback prediction only establishes feedback-code predictability for observed visits; it does not establish POI-choice ranking value.

### Dominant signals and dependence

The report compares associations with region, TL-only POI popularity bands (`1`, `2–4`, `5–9`, `10+` visit events), `ASORT_LCLASDC`, and `VISIT_AREA_TYPE_CD` as separate signals. It does not substitute one for the other when a value is missing or claim that these descriptive comparisons remove confounding. It presents region-level and aggregate evidence. Metadata also reports bucketed same-region TL/VL traveler and candidate-item overlap plus the VL candidate-item cold-start rate per region; the trip-ID overlap check remains a run gate. Visit-row association and feedback analyses can over-weight trips with more recorded visits. Context-to-POI associations additionally report a deduplicated trip-feature-pair grain. No per-trip feedback aggregation is invented because the contract does not define how multiple POI feedback values should be combined.

## Reproduction

Before reading source rows, check only whether `RAW_ROOT`, `CAPITAL_TL`, `CAPITAL_VL`, `WEST_TL`, `WEST_VL`, `EAST_TL`, `EAST_VL`, `JEJU_TL`, and `JEJU_VL` are set in the current process. These variables are a convenience for locating approved inputs; an interactive-shell check is not required. Do not print values or paths. When variables are unavailable, use only an explicitly permitted local or mounted candidate, with a strict depth limit and exact `2023-travel-log-{region}` markers. Do not scan an entire home or drive. Reject symlinks; verify one common raw root, unique TL/VL roles for all four regions, the documented region suffix and capital filekey markers, and each `Other` folder's unique POI master candidate. Cross-check dataset identity, filekey mapping, provenance, and terms against the approved Issue evidence and official regional schema documentation. Report only variable set/unset, target existence/type, and role-structure status. Do not open CSV rows until provenance, approval, terms, and every role mapping are unambiguous.

After successful preflight, assign the verified role roots and common raw root to shell-local variables; set the four `*_OTHER` variables to the corresponding approved POI master role. Keep values local, do not enable shell tracing, and do not record paths. Select a new run ID that has no existing artifact directory. The capital role folders use the documented approved filekey layout; other regions use `TL_csv` and `VL_csv`.

```bash
RUN_ID="context-poi-2023-four-region-YYYYMMDD"

python3 scripts/recommendation/analyze_context_poi.py \
  --raw-root "$RAW_ROOT" \
  --input "capital:TL=$CAPITAL_TL" --input "capital:VL=$CAPITAL_VL" \
  --input "west:TL=$WEST_TL" --input "west:VL=$WEST_VL" \
  --input "east:TL=$EAST_TL" --input "east:VL=$EAST_VL" \
  --input "jeju-islands:TL=$JEJU_TL" --input "jeju-islands:VL=$JEJU_VL" \
  --poi-master "capital=$CAPITAL_OTHER" --poi-master "west=$WEST_OTHER" \
  --poi-master "east=$EAST_OTHER" --poi-master "jeju-islands=$JEJU_OTHER" \
  --allow-approved-capital-filekey-folders \
  --run-id "$RUN_ID" \
  --confirm-approved --confirm-terms --confirm-poi-candidate
```

The command writes `availability_audit.csv`, `associations.csv`, `predictive_ablation.csv`, `common_cohort_sensitivity.csv`, and `run_metadata.json` beneath ignored `results/experiments/context-poi-signal/<run-id>/`. Metadata records dataset/version, role labels, code revision, script hash, settings, timestamps, and policy; input paths and filenames are omitted. The raw source is read-only. Do not copy ignored results into Git or share them outside the authorized local analysis context.

Safe synthetic checks:

```bash
python3 -m unittest discover -s tests -p 'test_context_poi_feasibility.py' -v
python3 -m py_compile scripts/recommendation/analyze_context_poi.py tests/test_context_poi_feasibility.py
```

## Results

The corrected follow-up run reused the Issue #12 approved 2023 AI Hub Domestic Travel Log sources under Issue #45's read-only local-use authorization. Before opening rows, the current process variable check found all required variables unset. A bounded depth-five discovery under the permitted mounted candidate then verified the four exact 2023 region-root markers and one common raw root. One additional nested capital marker lacked the documented role layout and was excluded; the complete four-region mapping remained unique. The selected TL/VL roles matched the approved regional filekey inventory and schema suffixes; each `Other` role contained the unique `TN_POI_MASTER` marker. Issue #45, Issue #12 approval evidence, the documented filekey inventory, regional schema guides, and local-use terms were cross-checked. No interactive-shell check was claimed. TL remained discovery/training and VL replication/validation; no random split or seed was used. The trip-ID overlap gate passed in every region. No download or external transfer occurred.

Final corrected run ID: `issue45-context-poi-final-20261012T132926Z-873520`. Its metadata records the source/version, role labels, code revision, dirty-worktree status, script hash, and privacy policy, without local input paths or filenames. The script hash matches the code used for this run. The five expected ignored aggregate artifacts were written; earlier artifact sets remain unchanged. Metadata confirms no raw paths, identifiers, category values, coordinates, free text, or row-level outputs.

The evidence below uses only reviewed aggregate artifacts. Support is bucketed, no category values or contingency cells are reproduced, and effects are reported only where the script marked support as observed. `privacy-limited` remains distinct from `insufficient-support`.

### Coverage and feature availability

Core style, motive, destination/accompaniment, companion-count, month, and elapsed-day candidates were generally in the `0-<10%` missing-rate band. A small number of motive fields had a higher or suppressed missingness band. Source codes remain opaque; `TRAVEL_MISSION` remains unresolved and excluded. Demographics stayed descriptive and separate.

| Diagnostic | Result |
| --- | --- |
| Candidate join coverage | Capital, west, east: `50-<75%`; jeju-islands: `75-<90%` in both roles |
| Duplicate candidate keys / multiple-`SGG_CD` keys | Both in the `0` bucket |
| Visit-side `SGG_CD` missingness | Capital, west, east: `50-<75%`; jeju-islands: `75-<90%` |
| POI classification missingness among matched visits | Each field: `90-100%` |
| Cross-region candidate-ID collisions | `10+`; candidate identities remain region-scoped |

### Context-to-POI association

Most tested pairs had `10+` support and an observed statistic; a minority were `privacy-limited` or `insufficient-support`. The tables show regional median Cramér's V by role and grain. These are unsigned nominal associations, not effect directions. Tests are exploratory and unadjusted for multiplicity.

**Visit-row grain.**

| Region | TL median V | VL median V | Median absolute Δ |
| --- | ---: | ---: | ---: |
| Capital | 0.228 | 0.332 | 0.163 |
| West | 0.335 | 0.298 | 0.122 |
| East | 0.263 | 0.288 | 0.117 |
| Jeju | 0.228 | 0.350 | 0.105 |

These values weight observed visit-feature pairs, so trips with more recorded visits can contribute more.

**Distinct trip × feature-pair grain.**

| Region | TL median V | VL median V | Median absolute Δ |
| --- | ---: | ---: | ---: |
| Capital | 0.219 | 0.342 | 0.168 |
| West | 0.330 | 0.295 | 0.128 |
| East | 0.264 | 0.293 | 0.122 |
| Jeju | 0.201 | 0.349 | 0.102 |

This sensitivity deduplicates by trip and feature pair. The broad patterns appeared in both roles, while magnitudes shifted; both grains remain subject to coverage and dependence limits.

### Feedback and predictive ablation

Feedback targets remain independent nominal outcomes. Their missingness was `25-<50%` in capital and `10-<25%` elsewhere; no values fell outside the documented 1–5 range. Aggregate context-only feedback association medians were small (Cramér's V about `0.04-0.06`). Joint context × POI medians were higher in VL than TL, and remain descriptive nominal associations.

The tables compare the previously reported deltas with the corrected VL constant-prediction baseline. The corrected baseline predicts the label selected by TL training counts, and its accuracy is measured on each ablation's VL evaluation cohort.

| Target | Popularity old → corrected | Context old → corrected |
| --- | ---: | ---: |
| `DGSTFN` | +0.007 → 0.000 | -0.018 → -0.019 |
| `REVISIT_INTENTION` | +0.007 → 0.000 | -0.025 → -0.026 |
| `RCMDTN_INTENTION` | +0.011 → 0.000 | -0.034 → -0.032 |

These changes remove the prior use of the TL majority proportion as if it were validation accuracy. The context-only deltas remain negative after correction.

| Target | Context + POI old → corrected |
| --- | ---: |
| `DGSTFN` | -0.032 → +0.001 |
| `REVISIT_INTENTION` | -0.059 → -0.021 |
| `RCMDTN_INTENTION` | -0.061 → -0.018 |

The aggregate `10+` TL / `10+` VL support applied to popularity-only, context-only, and context-plus-POI rows for each target. POI-only and context-plus-richer-POI rows had `10+` TL support but `<10` VL support, so their metrics remain `privacy-limited` and suppressed. Per-ablation complete-case cohorts differ; deltas are not controlled incremental effects.

**Common-VL-cohort sensitivity.** The cohort is the intersection of valid VL observations with a nonmissing target and all eligible features present in each of the three context ablations. TL training remains complete-case per ablation.

| Target | TL support per ablation | Shared VL support | Metric status |
| --- | ---: | ---: | --- |
| `DGSTFN` | `10+` | `<10` | Suppressed |
| `REVISIT_INTENTION` | `10+` | `<10` | Suppressed |
| `RCMDTN_INTENTION` | `10+` | `<10` | Suppressed |

The shared VL cohort falls below the publication threshold, so this sensitivity cannot resolve incremental effects. This is privacy-limited evidence, distinct from an empty or unusable cohort.

### Other signals and overlap

Aggregate Cramér's V for region and TL-only popularity was small (about `0.02-0.05`). Broad POI category was about `0.07-0.13` in TL and `0.11-0.13` in VL; visit-area type was about `0.05-0.06` in TL and `0.06-0.07` in VL. These comparisons do not establish that category explains context associations.

| Region | TL/VL traveler overlap rate | Candidate-item overlap | VL cold-start rate |
| --- | ---: | ---: | ---: |
| Capital | `0-<10%` | `25-<50%` | `50-<75%` |
| West | `0-<10%` | `50-<75%` | `25-<50%` |
| East | `0-<10%` | `50-<75%` | `25-<50%` |
| Jeju | `0-<10%` | `50-<75%` | `25-<50%` |

The trip-ID overlap gate passed in each region. Candidate-item overlap does not establish canonical identity. Unvisited items remain unlabeled; ranking feasibility was not evaluated.

### Aggregate result details

Same-region VL candidate-item overlap was `25-<50%` in capital and `50-<75%` in the other regions; VL item cold-start was `50-<75%` in capital and `25-<50%` elsewhere. Traveler overlap counts were `0`; their rates were in the `0-<10%` band. Candidate overlap does not establish canonical identity.

Across regional runs, context-only and context + POI did not show consistent improvement over the baseline. Feedback prediction is not observed-POI ranking, and unvisited items were not labeled negative.

### Conclusion

**Inconclusive.** The corrected run reproduced nominal context–POI associations in TL and VL, though magnitudes varied between roles. Context-only feedback deltas remained negative; context-plus-POI was near zero for one target and negative for the other two. POI-only and richer-POI validation metrics remained privacy-limited, and the shared VL cohort for the three context ablations was below the reporting threshold. Candidate joins remained incomplete, cross-region candidate collisions existed, and POI master classification metadata remained sparse. These results do not support Go, while the restricted feature support and withheld common-cohort metrics do not justify Reconsider. Ranking was not evaluated, and this result does not establish absence of a context-aware ranking signal.

## Limitations and remaining decisions

- The corrected run used bounded local discovery because the required variables were unset in the current process. A later run should repeat the documented preflight and choose a new run ID; do not reuse or overwrite either artifact set.
- Code mappings for `TRAVEL_MISSION`, a season definition, inclusive trip-duration semantics, and feedback ordinal direction are unresolved. The implementation does not guess them.
- Candidate table links are audited empirically and remain noncanonical. The sparse POI master classification coverage limited the richer-POI feature subset; do not make a `Reconsider` conclusion from that subset.
- The Naive Bayes ablation predicts feedback codes for observed visit rows. It is not an observed-choice ranking evaluation, an independent test set, or a causal analysis.
- Visit observations within a trip may not be independent. Feedback stays visit-row weighted because no trip-level target aggregation has been specified.
