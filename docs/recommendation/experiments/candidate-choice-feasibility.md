# Candidate choice feasibility

## Pre-data experiment contract

This framing was recorded before opening any actual travel-log rows.

- **Product question:** Can the approved 2023 four-region travel logs support a defensible choice set for a traveler/trip, and do observed visits provide enough in-set positive coverage to evaluate a ranking protocol?
- **Decision supported:** Go to a bounded context-aware ranking baseline, remain inconclusive pending a candidate/exposure contract, or reconsider the target/catalog strategy.
- **Prediction time:** Before the first relevant visit, at a hypothetical recommendation request. A field is eligible only if it is known at that time; the retrospective logs do not by themselves establish an actual serving request or exposure.
- **Entities:** region-scoped `TRAVELER_ID` is traveler; `(region, TRAVELER_ID, TRAVEL_ID)` is the trip/context unit; `(region, nonblank POI_ID)` is a provisional candidate item; `TN_VISIT_AREA_INFO` rows are observed visit interactions. `DGSTFN`, `REVISIT_INTENTION`, and `RCMDTN_INTENTION` are post-visit feedback.
- **Target:** Distinct observed POIs within a trip are implicit positive observations only. This is a proxy for a user's choices under unknown exposure, not explicit preference, relevance, or every recommendation opportunity.
- **Task type:** Descriptive candidate/coverage feasibility and ranking-evaluation feasibility, not binary classification and not a production ranker.
- **Candidate/exposure assumptions:** Candidate A is every nonblank region-scoped POI observed in that region's TL, fixed from TL only. This is a reproducible catalog proxy, not proof that every POI was available or exposed to each trip. Destination/admin-area and POI-category restrictions are only eligible if the source and availability contract shows the field was known at request time; post-event visit locations or inferred preferences cannot define candidates.
- **Unvisited semantics:** Eligible but unvisited items are unlabeled/unknown. They will not be turned into true negatives. If a deterministic sampled-unlabeled diagnostic is needed, it will be reported separately with its population and seed and will not be interpreted as a negative label.
- **Split and leakage:** TL is the sole source for candidate construction and popularity counts; VL is validation only and cannot define, tune, or filter candidates. Evaluation units are whole trips. Reject overlapping `TRAVEL_ID` across TL/VL within a region. Exclude post-event feedback and any location/category signal unavailable at request time. Report repeated visits as event counts but use distinct observed items for trip relevance. Cross-split traveler overlap limits external-generalization claims and will be diagnosed.
- **Baseline:** Reuse the region-popularity evaluator and its TL-only scores; deterministic random order is only a protocol smoke check if useful. Neither establishes exposure-aware user choice.
- **Metrics:** Candidate coverage, positive coverage, cold-start share, candidate-size buckets, privacy-banded positive density, and choice-set status; if ranking is technically evaluable, candidate-aware Recall@K, NDCG@K, and MRR with existing small-support suppression. Accuracy alone is not an acceptable ranking metric.

## Data, reproduction, and privacy contract

Use the already-approved AI Hub Domestic Travel Log 2023 capital, west, east, and jeju-islands TL/VL inputs. Bind roles from approved process variables or explicit role arguments, then validate provenance, approval/terms, region and role layout using the existing popularity evaluator contract (including its explicit capital filekey-layout validation). Keep raw roots read-only. Reuse the popularity baseline loader and safe aggregate helpers where their semantics fit. Results belong only under the ignored `results/experiments/candidate-choice-feasibility/<run-id>/` location. Do not persist raw paths, identifiers, rows, coordinates, free text, candidate lists, or source filenames.

The existing four-region role mapping, capital layout exception, and confirmation flags follow [`popularity-baseline.md`](popularity-baseline.md). Reproduce with the same local role variables and a new run ID:

```bash
python3 scripts/recommendation/analyze_candidate_choice_feasibility.py \
  --raw-root "$RAW_ROOT" \
  --input "capital:TL=$CAPITAL_TL" --input "capital:VL=$CAPITAL_VL" \
  --input "west:TL=$WEST_TL" --input "west:VL=$WEST_VL" \
  --input "east:TL=$EAST_TL" --input "east:VL=$EAST_VL" \
  --input "jeju-islands:TL=$JEJU_TL" --input "jeju-islands:VL=$JEJU_VL" \
  --allow-approved-capital-filekey-folders \
  --run-id "issue59-four-region-candidate-choice-YYYYMMDD" --k 5 10 20 \
  --confirm-approved --confirm-terms --confirm-poi-candidate
```

The command validates all eight explicit region/role bindings and their layout before opening rows. It writes only `metrics.csv` and path-free `run_metadata.json` under the ignored candidate-choice result directory. Synthetic regression tests run with `python3 -m unittest discover -s tests -p 'test_candidate_choice_feasibility.py' -v`.

## Four-region diagnostics

The final four-region run is `issue59-four-region-final3-20261014`. Run metadata fingerprints both output-affecting scripts: `analyze_candidate_choice_feasibility.py` SHA-256 `eb869c5e9c3852523b8f909f323506cab70ad6d0f545bf8eea412f9535627b32` and `evaluate_popularity.py` SHA-256 `84a9dbe268efbf7237c258c8547a304b1f2eb1882881a1e429092270cce6ae9a`. The recorded source revision is `711237507773bc587132440e293b8d12bb0dd6d7` with a dirty worktree (`code_worktree_dirty: true`); this is a pre-commit run and is not represented as a clean revision. The ignored output contains aggregate metrics and path-free run metadata only.

The run used AI Hub Domestic Travel Log 2023, the explicitly bound capital/west/east/jeju-islands TL/VL inputs, TL-only region-scoped nonblank `POI_ID` candidates and popularity counts, trip-level VL positives, K=5/10/20, no sampling seed, and no test metrics. All four TL/VL trip-ID overlap checks passed with a safe `0` bucket; the diagnostic traveler overlap was also `0` in all four regions. The only feature inputs read were the existing evaluator's trip owner and visit item identity fields. Post-visit feedback was not read.

| Region | Candidate items | Trips with a candidate | Candidate size per trip | Distinct positive density per trip | VL positive coverage | VL cold-start positive share |
| --- | --- | --- | --- | --- | --- | --- |
| capital | 10+ | 90–100% | 500+ | 0% and 0–<1% buckets | 25–<50% | 50–<75% |
| west | 10+ | 90–100% | 500+ | 0% and 0–<1% buckets | 50–<75% | 25–<50% |
| east | 10+ | 90–100% | 500+ | 0% and 0–<1% buckets | 50–<75% | 25–<50% |
| jeju-islands | 10+ | 90–100% | 500+ | 0% and 0–<1% buckets | 50–<75% | 25–<50% |

The density columns are trip-level distribution buckets, with trip support `10+` in each reported bucket. Choice-set status, candidate-support status, and positive-coverage status are separate dimensions, so an outside-candidate positive is still visible when the candidate list is empty or too small. Ranking metrics exclude trips with fewer than two candidates because a one-item list cannot measure a choice among candidates. Status counts are bucketed, and cells below 10 are marked `privacy_limited`. Every region had supported evaluable trips and supported cold-start/outside-positive trips. Exact small status counts are not released.

The same run also reports TL and VL distributions for distinct trips per traveler, distinct observed positive POIs per trip, and repeated visit events per trip. Traveler, trip, and item counts use buckets; event shares use the existing small-numerator and small-denominator suppression policy. Repeated source events remain visible in repeat-event diagnostics, while ranking relevance uses distinct POIs within each trip. Trips without a usable POI remain in the distinct-positive-per-trip distribution as the zero bucket.

| Region | TL/VL distinct trips per traveler | TL distinct positives per trip | VL distinct positives per trip | TL repeat-event share | VL repeat-event share | Trips with repeats (TL / VL) |
| --- | --- | --- | --- | --- | --- | --- |
| capital | 1 / 1 (each `10+` support) | 0, 1, 2–4, 5–9, 10+ (`10+` support) | 2–4, 5–9, 10+ (`10+` support); smaller cells privacy-limited | 0–<10% | 0–<10% | 10–<25% / 10–<25% |
| west | 1 / 1 (each `10+` support) | 0, 1, 2–4, 5–9, 10+ (`10+` support) | 2–4, 5–9, 10+ (`10+` support); smaller cells privacy-limited | 0–<10% | 0–<10% | 25–<50% / 25–<50% |
| east | 1 / 1 (each `10+` support) | 0, 1, 2–4, 5–9, 10+ (`10+` support) | 2–4, 5–9, 10+ (`10+` support); smaller cells privacy-limited | 0–<10% | 0–<10% | 25–<50% / 25–<50% |
| jeju-islands | 1 / 1 (each `10+` support) | 0, 1, 2–4, 5–9, 10+ (`10+` support) | 2–4, 5–9, 10+ (`10+` support); smaller cells privacy-limited | 10–<25% | 10–<25% | 50–<75% / 50–<75% |

The trip-per-traveler distribution uses `TN_TRAVEL` trips with one unambiguous traveler owner; ownerless or ambiguous trips cannot be assigned to a traveler and are excluded from that distribution. Repeat-event shares count usable nonblank POI visit events beyond the first occurrence of the same region-scoped POI within a trip. No row-level or exact small-count results are retained in the document.

The region-popularity protocol check among in-candidate positives produced the following trip-macro metrics. These are feasibility evidence for the fixed candidate set, not production quality estimates; observed positives do not establish exposure or true negatives.

| Region | Recall@10 | NDCG@10 | MRR@10 |
| --- | ---: | ---: | ---: |
| capital | 0.064440 | 0.037433 | 0.051227 |
| west | 0.055809 | 0.058266 | 0.121140 |
| east | 0.067931 | 0.060881 | 0.113462 |
| jeju-islands | 0.084768 | 0.159746 | 0.406333 |

All released ranking cells have at least `10+` trip support and `10+` retrieved-positive support. The separately reported all-observed-positive metrics include out-of-candidate positives in the relevance denominator, so those metrics include the candidate-coverage limitation.

## Issue #4 product-catalog contract update

위 TL-observed 후보 실험은 과거 proxy 결과로 유지한다. 이후 Issue #66에서 TourAPI KorService2 v4.4 기반 별도 제품 후보 계약을 승인했으며, 지원 type은 `{12,14,28}`, 전체 권역 정책은 [`config/recommendation/poi-catalog-policy-v1.json`](../../../config/recommendation/poi-catalog-policy-v1.json)에 고정했다. AI Hub 네 권역은 공식 광역권 분류에 따라 결정적으로 매핑한다. `jeju-islands`는 제주 코드 `50`을 뜻하며 다른 도서를 포함한다고 주장하지 않는다. TourAPI snapshot 및 AI Hub read-only 실험은 완료했으며 privacy-safe aggregate와 수정 후 재측정 결론을 [POI catalog candidate contract](../poi-catalog-candidate-contract.md)에 별도로 기록했다. 기존 TL-observed 집합을 제품 eligibility로 부르거나 서로 다른 후보 universe의 지표를 같은 조건의 값처럼 비교하지 않는다.

### Issue #4 exact-mode #60 TL-observed proxy 재실행

2026-10-18 exact-mode run에서 기존 `diagnose_region`을 동일한 TL-only 후보 / VL validation 기준으로 다시 호출했다. 아래는 기존 TL-observed proxy와 product-catalog 후보 실험을 구분한 exact 집계다. positive event coverage 분모는 #60의 관측 visit-event이며, TourAPI funnel의 distinct `(TRAVEL_ID, POI_ID)` 양성 쌍과는 단위가 다르다.

| Region | TL-observed candidate items | VL requests / non-empty | VL positive events | Positive event coverage | Cold-start events | Cold-start share | TL/VL trip ID overlap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| capital | 8,655 | 320 / 320 (100.00%) | 1,942 | 956/1,942 (49.23%) | 986/1,942 | 50.77% | 0 |
| west | 9,429 | 320 / 320 (100.00%) | 2,596 | 1,655/2,596 (63.75%) | 941/2,596 | 36.25% | 0 |
| east | 10,381 | 320 / 320 (100.00%) | 2,715 | 1,668/2,715 (61.44%) | 1,047/2,715 | 38.56% | 0 |
| jeju-islands | 13,152 | 320 / 320 (100.00%) | 4,621 | 3,449/4,621 (74.64%) | 1,172/4,621 | 25.36% | 0 |

각 region-level TL candidate set은 모든 VL 요청에 공통 적용되므로 요청당 후보 수는 candidate items와 같다. 정확한 후보 수는 capital 8,655, west 9,429, east 10,381, jeju-islands 13,152다. 네 권역 모두 VL 320/320 요청 non-empty, TL/VL trip ID overlap 0, traveler overlap 0이었다.

이 exact-mode 재실행에서 이전 privacy band `10+` 후보 수는 위 정확 수로 풀렸고, `90–100%` non-empty request는 모두 `320/320 (100.00%)`였다. 이전 broad event-coverage band도 exact numerator/denominator로 교체했다. 이 표는 #60의 과거 후보 대리값이며 TourAPI canonical identity coverage나 과거 exposure를 뜻하지 않는다.

### Issue #4 identity diagnostic follow-up

2026-10-18 재실행의 고정 TourAPI snapshot + AI Hub 원본 TL/VL exact aggregate identity 진단은 [POI catalog candidate contract](../poi-catalog-candidate-contract.md)의 Identity 진단 funnel 절에 기록했다. 이 진단은 historical TL-observed proxy와 별개이며, API 재호출이나 row-level export 없이 source-name/title, address, row-signal variation, matched type, eligibility reason을 source POI와 observed-positive 단위로 분리한다. exact-title 후보 0은 같은 권역에서 exact normalized title 후보를 찾지 못했다는 뜻이며 catalog 부재로 해석하지 않는다.

## Candidate alternatives and limits

- **A — region-level TL-observed POIs:** implemented uniformly in all four regions. It creates an auditable catalog proxy, but every trip inherits a `500+` candidate list and most trips have observed-positive density below 1%. It does not show that those items were available or exposed to the traveler.
- **B — destination/admin-area constraint:** not used. The available contract does not establish an actual recommendation request or prove that a retrospective trip destination was known at the simulated prediction time. Visit-area location is post-event and cannot filter candidates. A later run needs an explicit request-time destination contract plus a validated item-to-area mapping.
- **C — context/category constraint:** not used. A POI category or trip survey value alone is not an exposure or candidate-membership record, and no explicit request-time user filter is defined. Applying a category from an observed visit would infer preference from the target.
- **Unvisited and sampling:** eligible unvisited TL candidates remain unlabeled. No negative sampling was required for this feasibility diagnostic. Any follow-up sampled-unlabeled protocol must name its population, ratio, seed, replacement rule, positive exclusion and region/context rule, and must continue to call samples unlabeled.

## Decision

**Inconclusive.** The same deterministic region-level candidate rule can be built and evaluated across all four regions, with nonempty candidates for 90–100% of VL trip units and ranking metrics supported by the privacy threshold. However, the candidate space is `500+` per trip, positive density is concentrated below 1%, and 25–75% of observed VL positive events are outside the TL candidate catalog depending on region. Most importantly, travel logs contain observed visits rather than a record of what was offered or considered. The data therefore do not establish a serving-time choice set or justify treating unvisited candidates as negatives. Destination/category filters do not resolve that exposure gap under the current contract.

**Follow-up contract:** capture or approve a request-time candidate/exposure snapshot (or an authoritative catalog and deterministic eligibility rule), its region/destination/category availability, and the time at which each field is known. Keep TL as the sole candidate-definition source and VL as validation; group by whole trip; preserve region-scoped item identity; report cold-start and outside-candidate positives; use ranking metrics with the existing support suppression. Only after this contract is fixed should a context-aware ranking baseline be compared.

Issue #4 defines the next product-catalog candidate contract in [`poi-catalog-candidate-contract.md`](../poi-catalog-candidate-contract.md). The TL-observed set above remains a historical proxy. It is not interchangeable with product-defined eligibility, and its metrics must not be compared directly with a future catalog snapshot unless the candidate universe and evaluation support rules are aligned.

The separate Issue #4 `TN_POI_MASTER` link diagnostic uses four regional Other candidate files that the user explicitly confirmed as approved. That approval does not change this TL-only proxy's basis or establish a serving catalog, canonical identity, or product-candidate coverage.

## Issue #4 identity-source / search-scope comparison (2026-10-18)

The fixed-snapshot A/B/C/D comparison is recorded in [the POI catalog candidate contract](../poi-catalog-candidate-contract.md). It reuses identical positives and TourAPI snapshot data. Arm D (TN_POI_MASTER metadata + global identity search) resolves 4,696/97,640 positives (4.81%), compared with Arm A's visit-row metadata + source-region search at 3,000/97,640 (3.07%). For B/D, 26,884 positives lack same-region Master metadata; they are now recorded only as `identity_source_missing` and excluded from title-candidate diagnostics. Thus D has 70,756 source-available positives and a 6.64% conditional identity rate while its all-positive rate remains 4.81%. Candidate-contained positives are 2,097/97,640 (2.15%) in D. The four-region Master union contains none of the same-region missing IDs (0/26,884 found elsewhere), so a D2 global Master identity arm has no observed recovery benefit at this stage. The identity path for further candidate research remains D, while request-region eligibility and the `{12,14,28}` product policy remain unchanged. The remaining 95.19% is unresolved or source-missing, so this result supports **modify and remeasure**, not a claim that the identity/coverage contract is sufficient.

### Arm E follow-up (2026-10-18)

Arm E uses same-region Master metadata when present and explicitly falls back to visit-row metadata only when Master is missing; global TourAPI identity search and D's exact matching rules remain unchanged. Of the 97,640 positives, 70,756 use `master` provenance and 26,884 use `visit_fallback`. E statuses are MATCHED 5,195 (5.32%), AMBIGUOUS 20,297 (20.79%), and UNMATCHED 72,148 (73.89%). E contains 2,423 positives in the eligible candidate set (2.48% end-to-end; 46.64% conditional among MATCHED), compared with D's 4,696 MATCHED (4.81%) and 2,097 contained (2.15%). The increases are +499 MATCHED and +326 contained.

Within the 26,884-positive visit-fallback subset, 499 are MATCHED (1.86%), 5,170 AMBIGUOUS (19.23%), and 21,215 UNMATCHED (78.91%). Global exact-title candidate counts are 0 for 22,777 (84.72%), 1 for 3,894 (14.48%), and 2+ for 213 (0.79%). The 499 fallback matches include 326 `eligible` (65.33%) and 173 `unsupported_content_type` (34.67%); 326 positives are candidate-contained. This is a measurable but low-rate recovery with a meaningful ambiguity burden. **Keep E as a diagnostic arm; retain canonical D pending review of visit-fallback signal quality.** The exact aggregate and provenance counts are in the ignored artifact described by the POI catalog contract.

### Master / visit shadow validation (2026-10-18)

For the 70,756 observed positives with both same-region metadata sources, Master and visit metadata were independently matched against the same fixed global TourAPI snapshot with D's existing exact rule. Both sources MATCHED for 1,927 positives; all 1,927 selected the same `contentid` (100.00% agreement within the both-MATCHED subset; 0 different IDs). Of 2,545 visit MATCHED positives, 1,927 (75.72%) were also Master MATCHED, 583 were Master AMBIGUOUS, and 35 were Master UNMATCHED.

Visit signal class is reported separately: 58,092 positives had a single visit metadata signal, while 12,664 had `source_signal_conflict`. All 12,664 conflict cases were visit AMBIGUOUS under the unchanged rule; they were not relaxed or promoted. The full 3×3 status matrix, exact count/rate, and agreement metric are recorded in the POI catalog contract and ignored aggregate. This is a conditional consistency proxy, not independent ground truth or a canonical-ID promotion decision.

The existing fixed snapshot omits `mapx/mapy`, so the coordinate-distance compatibility diagnostic could not be computed. Coordinates remain disabled as identity evidence. `UNMATCHED` and `AMBIGUOUS` remain distinct from catalog absence.
