# Popularity baseline

## Purpose and contract

This experiment establishes a reproducible first offline baseline for Issue #29. It follows the [recommendation training-data contract](../training-data-contract.md) without changing its provisional decisions.

- User identity is `(dataset region, TRAVELER_ID)` and stays in memory.
- Item identity is `(dataset region, nonblank POI_ID)`. Blank or absent `POI_ID` is excluded. `VISIT_AREA_ID`, names, and coordinates are never used as fallback identity.
- Each observed visit row is a binary implicit positive. Repeated rows remain separate training events and each contributes to popularity counts. Validation relevance is a set of distinct items within a trip because one ranked list can recommend an item only once.
- `TL_csv` is train and `VL_csv` is validation. The script does not read or report test metrics.
- Post-event feedback fields are not read.
- A validation evaluation unit is `(dataset region, TRAVELER_ID, TRAVEL_ID)`. Trips are not split into row-level evaluation cases.

The dataset region label scopes IDs and candidates. It is not a claim that every POI is geographically inside that region.

## Baselines and candidates

`region_popularity` ranks each region's candidates by the count of observed TL visit events for that region-scoped item. The candidate universe for every validation trip is all nonblank `(region, POI_ID)` items observed in that region's TL.

`global_popularity_diagnostic` pools TL events across the selected regions but retains `(region, POI_ID)` as its count key. It uses the exact same region-scoped candidate universe as `region_popularity`. Since a candidate can only be counted under its own region key, counts and rankings are identical by construction. The pooled run is a diagnostic of this scope limitation; it cannot estimate popularity over a shared nationwide item catalog or establish cross-region item identity.

Scores use training events only. Ties use a deterministic HMAC-SHA256 digest of the region-namespaced item key; the digest and item ID are never written. K defaults to 5, 10, and 20 and can be configured.

## Evaluation and coverage

Each metric is macro-averaged over candidate-covered trip units. Precision@K divides by `min(K, candidate count)`. Recall@K, NDCG@K, and MRR use the distinct observed validation item set for that trip. A cold-start positive remains relevant but is absent from the candidate list, so it lowers ranking metrics.

The report includes aggregate and per-region values for:

- Precision@K, Recall@K, NDCG@K, and MRR for `all`, `seen_positive`, and `cold_positive` trip cohorts.
- **Positive coverage:** among validation events with a nonblank `POI_ID` and unambiguous trip owner, the share present in the region's TL candidates.
- **Candidate coverage:** share of unambiguously grouped validation trip units with a nonempty region candidate universe.
- **Cold-start item share:** share of distinct usable validation POI candidates absent from the region's TL candidates.
- **Cold-start event share:** share of usable validation visit events whose POI candidate is absent from TL; repeated events remain represented.
- **Item identity coverage:** share of validation visit rows with a usable `POI_ID` and unambiguous trip owner.
- Validation event and exclusion counts, and number of candidate items.

Repeated validation events remain in positive coverage and cold-start event counts. Ranking relevance is binary within a trip, so repeating the same item in a trip does not create duplicate ranked positions. The cold-start item share counts distinct region-scoped POI candidates, consistent with the EDA set-based candidate coverage. Rows with no usable item are omitted from ranking labels and remain in coverage/exclusion aggregates. Trips with missing or ambiguous traveler ownership are omitted from evaluation units and reported as aggregate exclusions. Unobserved candidates have no explicit label; a metric hit means an item was observed in validation, not that every unobserved item is a confirmed negative.

Before ranking, the CLI checks the intersection of TL and VL `TRAVEL_ID` values within each region. Any overlap fails the run before metrics are calculated. The failure message and successful-run artifacts expose only `0`, `<10`, or `10+` overlap count buckets; raw trip IDs are never emitted.

Counts are published only as `0`, `<10`, or `10+`. Rates are broad categorical bands, with small numerators or denominators suppressed. Ranking metric values and their trip-cell size are suppressed whenever the cell has fewer than 10 trips or fewer than 10 retrieved validation positives, including zero retrieved positives. No ranked item lists, row-level data, raw paths, raw identifiers, coordinates, or source free text are written.

## Prior EDA context (not baseline results)

The [Issue #12 EDA report](../../data/eda-travel-log-2023.md) records user-confirmed approvals for the four 2023 regional datasets and completed structural and recommendation-fit aggregate EDA. It also documents that `POI_ID` is only an observed candidate and that region-level dataset labels do not establish a canonical POI relationship.

That report's TL/VL POI overlap and cold-start shares are EDA aggregates from its own set-based analysis. For example, it records integrated overlap in the `50–<75%` band and integrated validation cold-start share in the `25–<50%` band; regional bands also differ. Those observations are context for the experiment, not popularity rankings or Precision/Recall/NDCG/MRR results. No baseline metric values are inferred from them.

The EDA report's aggregates remain context only. This document's real-data metrics below come from the separate Issue #29 baseline run and are not inferred from EDA.

## Reproduction

Set paths in local shell variables to the already-approved raw root and the corresponding role folders. Do not put raw paths in run metadata or shared logs. The CLI rejects missing confirmation flags, role paths outside `--raw-root`, symlinks, and duplicate split paths. The standard layout uses `TL_csv` and `VL_csv`; the capital region's approved direct export folders are accepted only with `--allow-approved-capital-filekey-folders` and only under the documented capital export layout.

```bash
RAW_ROOT="/local/approved/raw/root"
CAPITAL_ROOT="$RAW_ROOT/2023-travel-log-capital"
CAPITAL_TL="$CAPITAL_ROOT/extracted/filekey-TL-placeholder"
CAPITAL_VL="$CAPITAL_ROOT/filekey-VL-placeholder"
WEST_TL="/local/approved/west/TL_csv"
WEST_VL="/local/approved/west/VL_csv"
EAST_TL="/local/approved/east/TL_csv"
EAST_VL="/local/approved/east/VL_csv"
JEJU_TL="/local/approved/jeju-islands/TL_csv"
JEJU_VL="/local/approved/jeju-islands/VL_csv"
RUN_ID="popularity-2023-four-region-YYYYMMDD"

python3 scripts/recommendation/evaluate_popularity.py \
  --raw-root "$RAW_ROOT" \
  --input "capital:TL=$CAPITAL_TL" --input "capital:VL=$CAPITAL_VL" \
  --input "west:TL=$WEST_TL" --input "west:VL=$WEST_VL" \
  --input "east:TL=$EAST_TL" --input "east:VL=$EAST_VL" \
  --input "jeju-islands:TL=$JEJU_TL" --input "jeju-islands:VL=$JEJU_VL" \
  --allow-approved-capital-filekey-folders \
  --run-id "$RUN_ID" --k 5 10 20 \
  --confirm-approved --confirm-terms --confirm-poi-candidate
```

The run writes `metrics.csv` and `run_metadata.json` under the ignored `results/experiments/popularity-baseline/<run-id>/` directory. Metadata records the safe dataset name/version, TL/VL roles and region labels, code revision and script hash, configuration, UTC timestamps, and privacy/policy settings; it excludes input paths and filenames. No seed is used because the full input is evaluated deterministically.

Synthetic-only validation:

```bash
python3 -m unittest discover -s tests -p 'test_popularity_baseline.py' -v
```

## Four-region baseline run

The approved local four-region TL/VL run completed on 2026-10-11. It used dataset version 2023, TL as train, VL as validation, K=`5, 10, 20`, no seed, trip-level macro ranking metrics, the `<10` support suppression policy, and the region-scoped identities above. The per-region TL/VL trip-ID overlap check passed in all four regions; each safe overlap bucket and the aggregate bucket is `0`.

Run ID: `issue29-four-region-20261011`. The ignored local artifacts are `metrics.csv` and `run_metadata.json` under `results/experiments/popularity-baseline/<run-id>/`. Metadata records the region/role labels, timestamp, config, policy, source revision `74037251a48957c4f1463a98eff23e705a4823bc`, and script SHA-256 `b6afa6707386423a5793cf68172688e4bce6bd7ffac04955632fb9341a1f20f3`. The run used the worktree's updated overlap-check implementation; `code_worktree_dirty` is `true`, and the script hash identifies the exact script. No input paths or filenames are included.

The tables show `region_popularity`; `global_popularity_diagnostic` has identical values in every scope and cohort by construction. Metric vectors list K=`5 / 10 / 20`. All displayed ranking metric cells have trip support `10+`. Cold-positive ranking values are suppressed because retrieved validation-positive support is zero. Counts remain bucketed and rates remain coarse-banded.

| Scope | Cohort | Precision@K | Recall@K | NDCG@K | MRR@K |
| --- | --- | --- | --- | --- | --- |
| capital | all | 0.018006 / 0.016720 / 0.014630 | 0.015330 / 0.033796 / 0.056761 | 0.018903 / 0.024296 / 0.032954 | 0.037085 / 0.046286 / 0.052285 |
| capital | seen_positive | 0.019929 / 0.018505 / 0.016192 | 0.031373 / 0.064440 / 0.105087 | 0.025953 / 0.037433 / 0.051495 | 0.041044 / 0.051227 / 0.057867 |
| west | all | 0.051118 / 0.035783 / 0.025879 | 0.031829 / 0.041640 / 0.060347 | 0.055980 / 0.050125 / 0.056440 | 0.108626 / 0.116496 / 0.119335 |
| west | seen_positive | 0.053156 / 0.037209 / 0.026910 | 0.040676 / 0.055809 / 0.080414 | 0.059823 / 0.058266 / 0.068276 | 0.112957 / 0.121140 / 0.124093 |
| east | all | 0.041905 / 0.038413 / 0.030952 | 0.025466 / 0.043461 / 0.070945 | 0.048507 / 0.048577 / 0.057927 | 0.099788 / 0.108419 / 0.115605 |
| east | seen_positive | 0.043854 / 0.040199 / 0.032392 | 0.041039 / 0.067931 / 0.104294 | 0.055470 / 0.060881 / 0.075208 | 0.104430 / 0.113462 / 0.120982 |
| jeju-islands | all | 0.158228 / 0.108544 / 0.071519 | 0.048525 / 0.067991 / 0.086994 | 0.195550 / 0.149658 / 0.122535 | 0.380802 / 0.385759 / 0.386003 |
| jeju-islands | seen_positive | 0.166667 / 0.114333 / 0.075333 | 0.060488 / 0.084768 / 0.108336 | 0.206046 / 0.159746 / 0.140052 | 0.401111 / 0.406333 / 0.406590 |
| aggregate | all | 0.067570 / 0.050040 / 0.035857 | 0.030347 / 0.046788 / 0.068828 | 0.080059 / 0.068397 / 0.067635 | 0.157211 / 0.164868 / 0.168928 |
| aggregate | seen_positive | 0.071682 / 0.053085 / 0.038039 | 0.043583 / 0.068287 / 0.099431 | 0.087751 / 0.079718 / 0.084256 | 0.166779 / 0.174903 / 0.179210 |
| every scope | cold_positive | suppressed at K=5, 10, 20 | suppressed at K=5, 10, 20 | suppressed at K=5, 10, 20 | suppressed at K=5, 10, 20 |

| Scope | Positive coverage | Candidate coverage | Cold-start item share | Cold-start event share | Item identity coverage | TL/VL trip-ID overlap |
| --- | --- | --- | --- | --- | --- | --- |
| capital | 25–<50% | 90–100% | 50–<75% | 50–<75% | 50–<75% | 0 |
| west | 50–<75% | 90–100% | 25–<50% | 25–<50% | 50–<75% | 0 |
| east | 50–<75% | 90–100% | 25–<50% | 25–<50% | 75–<90% | 0 |
| jeju-islands | 50–<75% | 90–100% | 25–<50% | 25–<50% | 75–<90% | 0 |
| aggregate | 50–<75% | 90–100% | 25–<50% | 25–<50% | 75–<90% | 0 |

The pooled and regional values have zero difference across all ranking and coverage metrics: with the current candidate universe, pooled counts preserve each region's item key and cannot change its regional ranking. Jeju-islands has the highest all-cohort Precision@5 and MRR@5 among these four scopes; these validation observations describe this split and are not estimates of future performance. Cold-start positives are not rankable by the TL-only candidate universe, so their ranking metric rows have zero retrieved positives and remain suppressed under policy. No raw data or real identifiers are included in the document or artifacts.

## Result status and limitations

The result is a provisional offline development baseline, not an independent test set or a guarantee of future destination coverage. It has no negative labels, uses only historical visit frequency, and cannot recommend unseen POIs. The global diagnostic cannot answer how a national shared-identity popularity model would perform because cross-region POI identity is unresolved.

Future contextual, content-based, and collaborative models should use the same TL/VL split, trip units, candidate universe, cohorts, metrics, and suppression policy for a direct baseline comparison. Any contract change should be recorded as a separate experiment decision.
