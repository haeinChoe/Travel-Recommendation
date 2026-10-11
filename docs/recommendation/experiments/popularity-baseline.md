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

Counts are published only as `0`, `<10`, or `10+`. Rates are broad categorical bands, with small numerators or denominators suppressed. Ranking metric values and their trip-cell size are suppressed whenever the cell has fewer than 10 trips or fewer than 10 retrieved validation positives, including zero retrieved positives. No ranked item lists, row-level data, raw paths, raw identifiers, coordinates, or source free text are written.

## Prior EDA context (not baseline results)

The [Issue #12 EDA report](../../data/eda-travel-log-2023.md) records user-confirmed approvals for the four 2023 regional datasets and completed structural and recommendation-fit aggregate EDA. It also documents that `POI_ID` is only an observed candidate and that region-level dataset labels do not establish a canonical POI relationship.

That report's TL/VL POI overlap and cold-start shares are EDA aggregates from its own set-based analysis. For example, it records integrated overlap in the `50–<75%` band and integrated validation cold-start share in the `25–<50%` band; regional bands also differ. Those observations are context for the experiment, not popularity rankings or Precision/Recall/NDCG/MRR results. No baseline metric values are inferred from them.

No real-data baseline output is included here. The isolated implementation worktree had no local `data/raw` directory and no configured `AIHUB_RAW_ROOT`; no approved input paths were available to verify in this run. The EDA report documents approval and historical processing, but does not itself make raw TL/VL files available in this worktree. Real-data execution should occur only after the user supplies or configures the already-approved local raw root and its TL/VL role folders.

## Reproduction

Set paths in local shell variables to the existing, already-approved raw root and the corresponding extracted role folders. Do not put raw paths in run metadata or shared logs. The CLI rejects missing confirmation flags, role paths outside `--raw-root`, symlinks, duplicate split paths, and role folder names that do not match `TL_csv` or `VL_csv`.

```bash
RAW_ROOT="/local/approved/raw/root"
CAPITAL_TL="/local/approved/capital/TL_csv"
CAPITAL_VL="/local/approved/capital/VL_csv"
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
  --run-id "$RUN_ID" --k 5 10 20 \
  --confirm-approved --confirm-terms --confirm-poi-candidate
```

The run writes `metrics.csv` and `run_metadata.json` under the ignored `results/experiments/popularity-baseline/<run-id>/` directory. Metadata records the safe dataset name/version, TL/VL roles and region labels, code revision and script hash, configuration, UTC timestamps, and privacy/policy settings; it excludes input paths and filenames. No seed is used because the full input is evaluated deterministically.

Synthetic-only validation:

```bash
python3 -m unittest discover -s tests -p 'test_popularity_baseline.py' -v
```

## Result status and limitations

Baseline metrics remain ungenerated until verified local approved TL/VL role folders are available. The existing EDA aggregates are not substitutes. This is a provisional offline development split, not an independent test set or a guarantee of future destination coverage. The baseline has no negative labels, uses only historical visit frequency, and cannot recommend unseen POIs. The global diagnostic cannot answer how a national shared-identity popularity model would perform because cross-region POI identity is unresolved.

Future contextual, content-based, and collaborative models should use the same TL/VL split, trip units, candidate universe, cohorts, metrics, and suppression policy for a direct baseline comparison. Any contract change should be recorded as a separate experiment decision.
