# User-CF and Item-CF baseline

## Purpose and contract

This Issue #31 experiment compares binary implicit collaborative filtering with the Issue #29 popularity baseline from PR #30. It reuses the same loader, region namespace, trip grouping, split-overlap check, metric definitions, K=5/10/20 defaults, count buckets, rate bands, and `<10` small-cell suppression helpers from [`evaluate_popularity.py`](../../../scripts/recommendation/evaluate_popularity.py). PR #30 remains unchanged.

- User key: `(dataset region, TRAVELER_ID)`, memory-only; IDs are not features and are never serialized.
- Item key and base candidate universe: `(dataset region, nonblank POI_ID)` observed in TL. No `VISIT_AREA_ID`, name, coordinate, or canonical-POI fallback is used.
- An observed visit is a binary implicit positive. Repeated source events remain available to diagnostics, while user-item and item-user vectors use binary presence. Unvisited items are not asserted to be true negatives.
- TL is train and VL is validation. The evaluation unit is `(region, TRAVELER_ID, TRAVEL_ID)`. Test metrics and post-event feedback are excluded.
- Each region's TL/VL `TRAVEL_ID` intersection is checked before similarity construction or ranking. Any overlap fails the run closed; output exposes only `0`, `<10`, or `10+` buckets.

## Model definitions

### User-CF

For each region, a user's vector is the binary set of TL items. User-user cosine is computed from TL-only intersections. The target user is excluded from its neighbor list. Up to `--neighbors` positive-cosine neighbors are selected, ordered by descending cosine and then a stable HMAC-SHA256 digest of the region-scoped user key. The raw user key and digest are never written.

Candidate score is the similarity-weighted sum of neighbor binary presence:

```text
score(user, item) = sum(cosine(user, neighbor) * 1[item in neighbor TL history])
```

### Item-CF

For each region, an item's vector is binary presence across TL users. Item-item cosine is computed only from TL. For each item in the target user's TL history, the model retains its top `--neighbors` positive-cosine items; ties use a stable HMAC-SHA256 digest of the namespaced item key. Candidate score is the sum of those cosine similarities across the user's history items. The source item itself is excluded from its similar-item list.

### Shared ranking choices

- `--neighbors` defaults to 30 and is the sole similarity-list size; broad grid search is not performed.
- The base candidate universe is exactly the TL catalogue used by regional popularity, preserving `(region, POI_ID)` boundaries. Known TL items remain eligible recommendations so all methods use the same candidate set.
- Every TL candidate remains in the evaluation ranking, including candidates with a zero CF score, so Precision uses the same `min(K, candidate count)` denominator as PR #30. Candidates sort by descending CF score, then the deterministic HMAC-SHA256 item tie key. For a query with no positive CF score, the full tie-broken list remains available to preserve that denominator, but its effective relevant set is empty for ranking metrics: HMAC order cannot count as recommendation quality. Such trips remain in their applicable cohort denominators, with zero retrieved-positive support subject to the shared `<10` suppression rule. `recommendation_coverage` separately counts queries with positive collaborative signal. This does not use popularity scores or another fallback.
- Positive-score ties are deterministic using the existing popularity evaluator's HMAC-SHA256 item tie key. No ranked items are written to artifacts.
- A user with no TL history, or with no positive collaborative signal, has zero recommendation coverage and zero ranking hits. A VL POI absent from that region's TL catalogue is a cold-start positive and cannot be ranked.
- All/seen-positive/cold-positive trip cohorts follow PR #30. `user_history` contains candidate-covered validation trips whose region-scoped traveler has at least one usable TL item. `cold_start_user` contains candidate-covered validation evaluation trips whose region-scoped traveler has no usable TL item history; ranking metrics in this cohort are zero because such users cannot have collaborative scores. Both use the same `<10` trip and `<10` retrieved-positive suppression as #30. User-history coverage and cold-start share use mapped validation users from `visit_trip_keys`, including visit owners whose POI IDs are all blank; they do not use only users with usable POI events.

## Metrics and feasibility

The script emits aggregate and per-region macro trip-level Precision@K, Recall@K, NDCG@K, and MRR for `all`, `seen_positive`, `cold_positive`, `user_history`, and `cold_start_user`. Coverage and diagnostics include positive/candidate/recommendation/evaluation-trip coverage, user-history and user-cold-start share, train-user history coverage, cold-start item/event share, item identity coverage, bucketed train user distinct-item and item distinct-user distributions, candidate count, and safe input-exclusion counts. Candidate coverage matches PR #30's denominator of all validation trip units with a valid traveler mapping, including trips whose visit rows have no usable POI. Evaluation-trip coverage separately reports trip units with usable positive labels. Counts are only `0`, `<10`, or `10+`; rates use the existing broad bands and small-cell suppression. The aggregate retains region-namespaced IDs and cannot create cross-region similarity.

Ranking metrics use the same definition as popularity: Precision divides by `min(K, candidate count)`, Recall uses distinct observed positives for that trip/cohort, and NDCG/MRR use the observed validation positives when collaborative signal exists. Metrics are macro-averaged over candidate-covered trip units using the entire TL candidate universe, including zero-score candidates. No-signal queries contribute zero metrics and zero retrieved-positive support regardless of their deterministic tie order. Trip cells or retrieved-positive support below 10 are suppressed. No row-level outputs, raw IDs, paths, filenames, coordinates, feedback, or free text are written.

## Reproduction

Use the same already-approved 2023 regional TL/VL role folders as PR #30. Put their paths only in local shell variables; do not place them in logs or artifacts. The script requires explicit confirmation of dataset approval, terms, and the provisional POI candidate identity.

```bash
python3 scripts/recommendation/evaluate_cf.py \
  --raw-root "$RAW_ROOT" \
  --input "capital:TL=$CAPITAL_TL" --input "capital:VL=$CAPITAL_VL" \
  --input "west:TL=$WEST_TL" --input "west:VL=$WEST_VL" \
  --input "east:TL=$EAST_TL" --input "east:VL=$EAST_VL" \
  --input "jeju-islands:TL=$JEJU_TL" --input "jeju-islands:VL=$JEJU_VL" \
  --allow-approved-capital-filekey-folders \
  --model user-cf --neighbors 30 --k 5 10 20 \
  --run-id user-cf-four-region-clean-YYYYMMDD \
  --confirm-approved --confirm-terms --confirm-poi-candidate
```

Repeat with `--model item-cf` and a distinct run ID. Results are written only to the ignored `results/experiments/cf-baseline/<run-id>/` directory. Each run records the code revision, clean/dirty state, script SHA-256, UTC timestamps, dataset/version label, configuration and privacy policy, but not input paths or filenames. No seed is used because the complete input is evaluated deterministically.

Synthetic-only validation:

```bash
python3 -m unittest discover -s tests -p 'test_cf_baseline.py' -v
```

## Popularity reference from PR #30

PR #30's clean four-region reference used AI Hub Domestic Travel Log 2023, TL=train, VL=validation, K=5/10/20, no seed, trip-level macro ranking, and the `<10` suppression rule. The aggregate `region_popularity` reference at K=10 is:

| Cohort | Precision@10 | Recall@10 | NDCG@10 | MRR@10 |
| --- | ---: | ---: | ---: | ---: |
| all | 0.050040 | 0.046788 | 0.068397 | 0.164868 |
| seen_positive | 0.053085 | 0.068287 | 0.079718 | 0.174903 |
| cold_positive | suppressed | suppressed | suppressed | suppressed |

The per-region K=10 values are recorded in PR #30 and its [`popularity-baseline.md`](popularity-baseline.md). Direct CF comparison requires both clean-commit CF runs on those exact inputs. Do not compare a partial region set as if it were the four-region reference.

## Run status and limitations

No CF real-data reference result is recorded in this change. The approved dataset identity, 2023 version, user-confirmed download approval, official source pages, and AI Hub open-data terms are documented in the [EDA provenance record](../../data/eda-travel-log-2023.md) and the four region manuals. During this implementation, the approved TL/VL files and the prior ignored popularity-run metadata were not found in the available local source locations searched, so no source bytes or records were opened and no actual-data run was attempted. The clean-commit run acceptance item therefore remains blocked on locating the approved local source and matching its provenance to those approval/terms records. Do not substitute data or infer CF results from the popularity metrics.

If completed later, append only privacy-audited aggregate metrics and safe run metadata: clean code commit, `code_worktree_dirty=false`, script hash, UTC run time, run IDs/configuration, suppression outcomes, overlap buckets, and per-region/aggregate comparison. Keep metrics and metadata under the ignored results directory; do not commit or upload those artifacts.

The comparison answers only validation ranking on the TL catalogue. Sparse history can leave many trips without a collaborative score, and unseen TL items cannot be recommended. A positive validation item is an observed event, not a confirmed negative for any unobserved candidate. These results do not establish production performance or cross-region POI identity. Matrix factorization, content/context models, and serving remain out of scope.
