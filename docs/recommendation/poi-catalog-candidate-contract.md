# POI catalog, identity, and candidate contract (Issue #4)

Status: **current-public-listing snapshot and conservative identity coverage
measured; product candidate contract unresolved**. This document separates
observed catalog facts from product choices still needed to activate serving.
The 2023 travel logs contain no exposure or actual recommendation requests.

## Question and prediction moment

The product decision is which POIs the service can recommend for a request, and
whether an observed AI Hub visit can be linked to one of those POIs. The
prediction moment is the recommendation request **before** its relevant visits.
The service candidate set is the subset of a versioned authoritative catalog
that passes deterministic constraints known at that moment. Historical logs
contain visits, not requests or impressions, so this candidate set is a
prospective product definition and never historical exposure.

This Issue measures **identity and candidate coverage**, not ranking quality.
An observed visit can be an implicit positive. An unvisited candidate is
unknown/unlabeled. No negative samples or ranker are built here.

| Entity | Contract role |
| --- | --- |
| `(region, TRAVELER_ID)` | Offline traveler grouping only; no cross-region or service-account equivalence. |
| `(region, TRAVELER_ID, TRAVEL_ID)` | Whole-trip validation context. |
| `(region, nonblank POI_ID)` | Provisional AI Hub source item identity; the raw value stays in memory only. |
| `TN_VISIT_AREA_INFO` row | Observed visit event and implicit positive when it has a usable source item. |
| `TN_POI_MASTER` row | Source metadata candidate, with no assumed global canonical key or guaranteed join. |
| `DGSTFN`, `REVISIT_INTENTION`, `RCMDTN_INTENTION` | Post-visit feedback; excluded from request-time inputs and this diagnostic. |
| TourAPI `contentid` | Current KorService2 catalog identity, namespaced by provider and service. Unique in the verified displayed snapshot; stability across future snapshots is unverified. |

The source roles follow the [training data contract](training-data-contract.md),
the [four-region description index](../data/travel-log-2023/README.md), and the
[#59 candidate feasibility protocol](experiments/candidate-choice-feasibility.md).
The regional source role binding is explicit TL/VL/Other; folder spelling is
validated against the documented capital filekey exception or the regional
role folders. The official descriptions define `TN_POI_MASTER` name, address,
district code and coordinates, and visit-level `POI_ID`, but their Y/N markers
do not prove unique keys or foreign-key integrity.

## Official TourAPI review and access gate

The [official KTO Korean tourism information API listing](https://www.data.go.kr/data/15101578/openapi.do)
identifies the provider, the `KorService2` service, regional listing and
synchronization endpoints, JSON/XML formats, free use, an unrestricted general
use-license scope, automatic development approval, reviewed production
approval, and development traffic shown as 1,000 requests. The applicable
account quota and production entitlement still need account-owner review.
The [official Korean API manual v4.4](https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003603931&fileDetailSn=1)
defines `contentid` as content ID, `contenttypeid` as tourism type, `title` as
title, `addr1` as **address** (not specifically a road address),
`lDongRegnCd`/`lDongSignguCd` as legal-dong region/district codes, and
`modifiedtime` as content modification time. It defines sync-list `showflag`
as display state (`1` displayed, `0` not displayed). Neither endpoint proves
that a venue is open or was available in 2023. The listed image fields have
separate usage conditions and are excluded from this snapshot.

The earlier URL-encoded-key smoke check returned HTTP `403` with no parsed
provider result. With the existing environment value passed unchanged as the
`serviceKey` query value, a bounded public-list check returned HTTP `200`,
provider `resultCode=0000`, and one item. This establishes access to these
public listing endpoints in this process; it does not grant production use.
Acquisition never logs or stores the key, completed URL, raw response,
headers, or exception text. No new key, terms acceptance, paid resource, or
AI Hub data transmission was used.

### Catalog and canonical identity proposal

The existing ignored v1 manifests record the KTO service, official listing
reference, UTC retrieval interval, snapshot ID, content digest, pagination
checks, and public display-state meaning. The sync manifest also records the
official manual revision. The acquisition scripts now record their own code
hash, Issue authorization basis, terms reference, manual revision, and refresh
method on **future** runs; these fields were not present in the completed v1
artifacts and cannot be retroactively claimed. The catalog script will also
record that the product type allowlist and legal-dong crosswalk are unset.
The type dictionary and field interpretation are documented below, not in the
v1 manifests. The identity run records its analysis-code hashes separately.

Use `(provider=KTO, service=KorService2, contentid)` as the **current catalog
identity key**: the official manual defines the field and all 49,622 current
displayed records had unique nonblank IDs. Stability across future snapshots
and relationships to hidden or retired IDs still require longitudinal review.
Keep snapshot/version on each mapping and candidate result.
Never infer an AI Hub `POI_ID` equals a TourAPI ID. A `showflag=0` record is
`not_displayed` and excluded from the current public-display candidate universe;
that flag does not establish deletion or permanent removal.
Unknown display state, stale/incomplete snapshot, missing region/type metadata,
or unresolved content-type policy makes eligibility **UNRESOLVED** rather than
silently turning it into an empty or permissive candidate set. Opening hours
and temporary closures need separate verified fields and time semantics.

### Current bounded catalog evidence

| Snapshot | UTC acquisition | Scope and validation |
| --- | --- | --- |
| `issue4-kto-20261014-v1` | 2026-10-14 14:41:34–14:42:16 | 49,622 `areaBasedList2` rows, 50 pages, 49,622 unique nonblank content IDs, total/page checks and first-page recheck passed. Minimal text/code/time fields only; SHA-256 `7d4ce53de71d2daca6699591c762327cf7813281e5e6190a911b5dfdaca0d917`. |
| `issue4-kto-sync-20261014-v1` | 2026-10-14 14:52:18–14:53:14 | `areaBasedSyncList2`: 49,622 displayed (`showflag=1`), 19,530 not displayed (`showflag=0`), 70 pages, pagination and first-page checks passed; SHA-256 `8369ef91d191e4357d2d6085034b5156bea4625d6fa45aa53f7af1600a75740e`. |

The displayed sync IDs equal the regional-list IDs exactly; neither list
overlaps the not-displayed IDs. The API is live, so sequential pages are not
an atomic provider snapshot even though total counts, unique IDs, and first
pages were stable during acquisition. The provider's current display flag is
eligible as a **display-state** gate, not as a claim about opening hours,
temporary closures, ownership changes, or historical 2023 availability.
`areacode` is blank for 32,284 displayed records, while legal-dong region code
is blank for 1,018; an unvalidated legacy-code filter would silently drop much
of the catalog. No request-to-legal-dong crosswalk is approved in this Issue.

The official manual defines eight content types: `12` tourist attraction,
`14` cultural facility, `15` event/performance/festival, `25` travel course,
`28` leisure sports, `32` lodging, `38` shopping, and `39` restaurant. Their
displayed-record counts in this snapshot are respectively 12,569, 2,765,
888, 1,068, 3,735, 2,923, 12,271, and 13,403. This is inventory, not a
product allowlist. In particular, whether a travel course is a recommendable
single POI is a product decision still open.

## AI Hub to canonical matching

The synthetic reference implementation is
[`poi_identity_contract.py`](../../scripts/recommendation/poi_identity_contract.py).
Unicode NFKC, case folding, and whitespace normalization are applied without
geocoding, transliteration, punctuation deletion, or guessed aliases. Matching
operates within one complete approved catalog snapshot. A source `POI_ID` with
conflicting source metadata is held for review before applying the rule.

| Status | Deterministic rule | Meaning |
| --- | --- | --- |
| `MATCHED` | One and only one displayed catalog record has the same normalized nonblank title as source name and the same **address string** as the source road address, with a unique nonblank content ID. | Provisional exact-string link; TourAPI `addr1` is a generic address field and `validation_status=unreviewed` until precision is audited. |
| `AMBIGUOUS` | Exact name exists but source address is missing, conflicts, or maps to multiple catalog records; or a canonical ID has conflicting records. | Keep all plausible alternatives internally; publish only aggregate conflict counts. |
| `UNMATCHED` | Source identity/name is unusable, or the snapshot has no exact normalized name candidate. | No link under this conservative rule; fuzzy/geographic matches may exist. |

Record source identity, proposed canonical ID only for `MATCHED`, method,
snapshot, and validation status in memory or an explicitly authorized ignored
artifact. The current Issue run writes **none** of those row-level values.
Report status by region, TL/VL, and method, with denominators for distinct
source items and observed positive events. Precision requires independent
reviewed labels and a representative ambiguity sample; match rate alone does
not establish correctness.

Name plus mapped administrative area, geodesic distance, fuzzy name, and
category consistency are candidate signals for a later review stage. AI Hub
coordinate reference system, TourAPI coordinate semantics, code crosswalk,
distance tolerance, and fuzzy score threshold are not validated here. Those
signals never automatically promote a result to `MATCHED` in this contract.
Region namespaces remain on AI Hub IDs until cross-region identity is proven.

## Request-time eligibility

The synthetic rule in `candidate_eligibility` returns `ELIGIBLE`,
`INELIGIBLE`, or `UNRESOLVED`; the latter prevents an unsupported filter from
appearing as zero available POIs. An eligible catalog item must have a listed
state verified by the official snapshot, a supported type, and a mapped region
equal to an explicit request region. Supported types and mapping versions are
required inputs, not inferred from AI Hub visit categories.

Before any item can be eligible or ineligible, the snapshot gate requires
provider use authorization, completeness, validated schema, freshness for the
request time, and validated provenance of display state. Missing or false
evidence in any field returns `UNRESOLVED`. The current snapshot verifies
public display state, but no final supported-type policy, validated
request-area crosswalk, or actual request context exists, so **product
eligibility remains unresolved**. A non-displayed item would be ineligible
under a future approved display-state rule; it is not necessarily deleted.

| Input | Role | Boundary |
| --- | --- | --- |
| Explicitly selected region | Hard constraint after a validated request-to-catalog code crosswalk. | Missing/unknown mapping is unresolved. |
| Explicitly selected district | Optional hard constraint after a validated district crosswalk. | Trip or visit destination observed afterward cannot stand in for the request. |
| Service-supported POI types and verified display state | Hard product/catalog constraints. | Type allowlist is unresolved; the sync flag proves public display state, not deletion or operating status. |
| Explicit category/theme filter | Potential hard constraint only with a defined request field and catalog crosswalk. | Current reference rule returns unresolved until that contract exists. |
| Travel style, motive, companion, age, gender | Potential ranking context when available and appropriate. | Never automatically exclude a candidate. |
| Observed visit category/location or post-event feedback | Excluded. | These are target-derived or unavailable at prediction time. |

The downstream evaluation contract is `request context -> deterministic
eligibility -> eligible candidate POIs -> ranking score -> Top-K`. Any future
ranking metric is computed only on a defined candidate universe, with
candidate-outside positives and cold-start reported separately. Metrics from
different candidate contracts are not directly comparable.

### Domain smoke review

| Synthetic proposal | Gate result and smallest correction |
| --- | --- |
| Predict post-visit satisfaction and call it POI ranking quality. | Proxy only; evaluate ranking on observed positives inside a fixed candidate universe for a direct ranking claim. |
| Assign every unvisited item label 0. | Rejected; retain unknown/unlabeled semantics and name any future sampled-unlabeled protocol explicitly. |
| Use classification accuracy alone for a ranking question. | Rejected; use candidate-aware Recall/NDCG/MRR with coverage and support reporting. |
| Use post-event feedback as a request-time feature. | Rejected as unavailable/leakage; use only fields known at request time. |
| Compare feature ablations on different complete-case cohorts. | Not an incremental feature estimate; fix a common cohort or report the cohort difference. |

## Coverage protocol and current limitation

Use TL to define the historical region-observed proxy from #59 and VL only as
validation. Reject overlapping trip IDs per region. Keep whole trips and the
same VL trip units and observed positive events as denominators for both
candidate definitions. Report traveler overlap and distinct source-item
overlap as generalization context. Do not use validation visits, feedback, or
future popularity to build candidates. A current catalog snapshot cannot
prove that an item was listed or exposed during a 2023 trip.

For each region and TL/VL role, identity coverage should include `MATCHED`,
`AMBIGUOUS`, and `UNMATCHED` shares, method mix, and conflicts. For each VL
trip, a validated product catalog should report nonempty eligible-candidate
share and candidate-size distribution. For VL observed positives, report
matched-and-eligible share, ambiguous/unmatched share, outside-candidate
share, and item cold-start/catalog-outside share. Compare the product rule
with the TL-observed proxy on those **same** denominators. No negative label
or historical exposure claim follows from the comparison.

The current displayed listing permits **conservative identity feasibility**,
but no actual request-time selected region/district, product content-type
allowlist, approved AI Hub-to-legal-dong crosswalk, or operational-open signal
is established. The `candidate_eligibility` result for a historical trip is
therefore `UNRESOLVED`. Product candidate nonempty-trip rate, size
distribution, positive-in-candidate/outside-candidate share, and
outside-catalog share are **unavailable**, not zero. The entire 49,622-item
displayed catalog is an inventory, not a candidate list for each request.

### Type-scope decision evidence (analysis-time only)

`issue4-scenarios-20261015-v4` compares the three requested type scopes against
the same current displayed snapshot and the same observed-positive denominators.
The exact KTO public inventory is:

| Type | KTO category | A | B | C |
| --- | --- | ---: | ---: | ---: |
| 12 | Tourist attraction | 12,569 | 12,569 | 12,569 |
| 14 | Cultural facility | 2,765 | 2,765 | 2,765 |
| 15 | Event / performance / festival | 888 | 888 | — |
| 25 | Travel course | 1,068 | 1,068 | — |
| 28 | Leisure sports | 3,735 | 3,735 | 3,735 |
| 32 | Lodging | 2,923 | — | — |
| 38 | Shopping | 12,271 | — | — |
| 39 | Restaurant | 13,403 | — | — |
| **Total** | | **49,622** | **21,025** | **19,069** |

The three scope sizes are comparable public-catalog inventories, not per-request
candidate sizes. A retains all catalog types; B excludes lodging, shopping,
and restaurants; C excludes those plus events and travel courses. Type `15`
requires event-date eligibility that the listing snapshot does not establish.
Type `25` can represent a multi-stop course rather than a single recommendable
POI. Those semantics make B/C useful sensitivity scenarios, but the Issue and
current product documents do not choose among them. This is decision evidence,
not a final allowlist recommendation.

As a decision-evidence recommendation, use C as the narrow comparison baseline
for the next product discussion: it retains the three more atomic inventory
groups and avoids the date-dependent event and multi-stop course semantics.
Its 19,069-item inventory is about 38% of A. The observed-positive linked
coverage is below 10% in every scenario at this reporting resolution, so the
current evidence does not show a coverage advantage for A or B. Keep A/B as
sensitivity alternatives. C is not a serving default or finalized allowlist;
product scope, request geography, and match precision still need decisions.

The analysis groups inventory by KTO `lDongRegnCd`; it does **not** infer a
user-selected region from an AI Hub visit, and it does not filter historical
visits as if they were requests. The ignored scenario metrics contain the
inventory and type counts by legal-dong region code. `lDongSignguCd` is not
used for district filtering because a request-code mapping has not been
validated. The Issue's product area input remains open to either direct KTO
codes or service-level codes with a versioned, validated crosswalk.

The displayed-record inventory by KTO legal-dong region code is:

| `lDongRegnCd` | A | B | C |
| --- | ---: | ---: | ---: |
| 11 | 8,024 | 1,661 | 1,469 |
| 12 | 3,678 | 2,047 | 1,971 |
| 26 | 2,229 | 609 | 534 |
| 27 | 1,197 | 486 | 467 |
| 28 | 1,981 | 741 | 707 |
| 30 | 844 | 227 | 209 |
| 31 | 654 | 292 | 275 |
| 36110 | 206 | 85 | 79 |
| 41 | 9,425 | 3,004 | 2,868 |
| 43 | 1,860 | 1,131 | 1,104 |
| 44 | 2,414 | 1,376 | 1,324 |
| 47 | 3,089 | 1,870 | 1,804 |
| 48 | 3,757 | 1,958 | 1,903 |
| 50 | 2,114 | 817 | 791 |
| 51 | 4,711 | 2,330 | 2,245 |
| 52 | 2,421 | 1,374 | 1,319 |

The A/B/C counts with missing `lDongRegnCd` are 1,018 / 1,017 / 0. Per-code
positive shares are also in the ignored scenario metrics; they are rates of
identity-linked in-scope positives over the full source-region TL/VL positive
denominator, not code-conditional recommendation coverage. AI Hub observations
without a linked KTO ID cannot be placed in a KTO legal-dong group.

For observed visits, every A/B/C scenario uses each region and TL/VL split's
same usable positive-event denominator. In every region and split, all three
scenarios have the same coarse bands: linked inside the scenario type scope
`0–<10%`, linked to a displayed KTO item outside the scenario type scope
`0–<10%`, ambiguous `10–<25%`, and unmatched under the exact rule `75–<90%`.
The result shows low linked-positive coverage under all three scopes; the
coarse bins do not distinguish their small differences. `linked outside type
scope` is a known type exclusion among exact links. `unmatched` means no link
under this rule and is **not** evidence that the POI is absent from the
catalog. The area-code rows assign a positive only to its linked KTO record;
each reported code share uses the full regional positive-event denominator.
Unmatched and ambiguous positives cannot be allocated to a KTO code.

These are global type-scope identity diagnostics, not true request-time
candidate coverage. Since no selected request region or validated crosswalk
exists in the travel logs, per-trip nonempty candidate share and candidate
size distribution remain unestimable. TL-observed item membership remains a
proxy only; unvisited items remain unknown.

### Matching precision sample audit

The audit frame is proposed `MATCHED` source items under the unique normalized
name plus address-string rule, stratified by region and TL/VL role. Within each
stratum, SHA-256 ranks the in-memory source identity using seed
`issue4-match-audit-v1`; select up to 20 items per stratum. The scenario run
records only the sample support by region/split and matching method. It stores
no pair, ID, name, address, row, or coordinate.

The run selected 160 proposed pairs: 20 in each of the eight region × TL/VL
strata. All 160 use method `unique_exact_name_address`. The independently
adjudicated denominator is 0/160, so SAME / DIFFERENT / AMBIGUOUS label counts
are unavailable, not zero.

The sample was selected reproducibly, but **manual SAME / DIFFERENT / AMBIGUOUS
adjudication was not performed**: this agent has no private non-logging view in
which to inspect name, address, and type evidence. Sending those fields to a
terminal/tool transcript or another agent would violate the no-identity-output
boundary. Therefore the adjudicated denominator is zero, method-specific
adjudicated counts are unavailable, and no population precision estimate or
confidence interval is claimed. The exact-string rule's match rate is not a
precision estimate.

Alternative review path: an authorized local human reviewer with a non-logging
in-memory review interface can inspect the deterministic sampled pairs directly
from the approved sources and return only region/split/method counts for
`SAME`, `DIFFERENT`, and `AMBIGUOUS`, plus the reviewed denominator. No example
or pair-level key should be exported. With a recorded sampling design and
adjudicated labels, a later analysis can report sample accuracy and a
stratified interval; until then, linkage precision remains unresolved.

### Four-region current-listing identity feasibility

`issue4-identity-20261015-v3` revalidated all eight TL/VL bindings, four
Other POI masters, split-table headers, and zero per-region TL/VL trip-ID
overlap before row analysis. It validated both catalog/sync file hashes and
the exact equality of displayed sync IDs and regional-list IDs. The ignored
result contains 184 privacy-safe metric rows with no source identifiers,
names, addresses, coordinates, or exact small cells. The table below uses
**distinct observed source items** as the status denominator; method and
positive-event bands are recorded in the ignored metrics.

| Region | TL matched / ambiguous / unmatched | VL matched / ambiguous / unmatched | VL exact-linked positive events | VL positives in TL-observed proxy |
| --- | --- | --- | --- | --- |
| Capital | 0–<10% / 0–<10% / 90–100% | 0–<10% / 10–<25% / 75–<90% | 0–<10% | 25–<50% |
| West | 0–<10% / 0–<10% / 75–<90% | 0–<10% / 10–<25% / 75–<90% | 0–<10% | 50–<75% |
| East | 0–<10% / 0–<10% / 75–<90% | 0–<10% / 10–<25% / 75–<90% | 0–<10% | 50–<75% |
| Jeju/islands | 0–<10% / 0–<10% / 75–<90% | 0–<10% / 10–<25% / 75–<90% | 0–<10% | 50–<75% |

For VL distinct source items, missing POI-master metadata accounts for
25–<50% in every region. No exact catalog title accounts for 25–<50% in
capital, west, and east, and 50–<75% in Jeju/islands. Name-present/address-
different ambiguity is 0–<10% in capital and Jeju/islands and 10–<25% in
west and east. Duplicate exact pairs are suppressed where fewer than ten
items support the cell. `MATCHED` is an unreviewed exact-string result, not a
precision estimate. `UNMATCHED` under this rule does **not** prove absence
from the KTO catalog; alternate addresses, spelling, and missing source
metadata may explain it.

The final two table columns share the **same VL usable positive-event
denominator** but answer different questions. TL proxy membership is a
historical-data-derived item-set check. Current-listing exact linkage is a
conservative identity check, not product-candidate coverage or 2023
exposure. TL-outside/cold-start positive-event share is 50–<75% in capital
and 25–<50% elsewhere. Exact-linked positives that are TL item cold-start
are 0–<10% in each region. Catalog-outside positives cannot be isolated from
ambiguous/unmatched links without reviewed identity evidence.

### Local 2023 four-region source readiness

The current local run `issue4-source-readiness-20261014-rerun1` used all four regions'
TL/VL trip and visit tables plus each region's Other POI master. The eight
explicit TL/VL bindings and four Other sources passed provenance/layout
checks before row reads; per-region TL/VL trip overlap was `0`. These bands
use the shared small-cell policy. `Source ID in master` divides source POIs
observed in TL or VL by all distinct observed source POIs; `road address`
divides stable master-linked source IDs with a nonblank road address by all
stable master-linked IDs. `TL proxy VL coverage` divides VL usable observed
positive events inside the TL-observed region set by all VL usable observed
positive events. The candidate set is fixed from TL and is not exposure.
The current run used the revised script, including coordinate-value conflict
detection and required-table/header checks. Its coarse bands are unchanged
from the earlier run; that agreement does not establish row-level identity quality.

| Region | Observed source ID in POI master | Road address on stable linked IDs | TL proxy VL positive coverage | TL proxy outside-positive share |
| --- | --- | --- | --- | --- |
| Capital | 50–<75% | 90–100% | 25–<50% | 50–<75% |
| West | 50–<75% | 75–<90% | 50–<75% | 25–<50% |
| East | 50–<75% | 90–100% | 50–<75% | 25–<50% |
| Jeju/islands | 50–<75% | 75–<90% | 50–<75% | 25–<50% |

Each region had `10+` observed source IDs linked to its master and `90–100%`
VL trip units with a nonempty TL proxy. The share of linked source IDs with
conflicting master metadata was `0–<10%` in each region, which does not prove
zero conflicts. This is source-side feasibility only. It does not measure a
TourAPI match, validate address equivalence, or establish a product catalog.
The current ignored run metadata recorded script hashes, code revision
`86e5abac35fed425529c459a049880e11bca378f`, dirty worktree state, UTC
completion, roles, protocol, and absence of TourAPI input. Its script hashes
identify the revised working files used for this run.

## Reproduction and privacy

The local source-readiness run uses only approved four-region 2023 TL/VL and
Other POI master inputs. Bind the existing current-process role variables;
the capital direct filekey layout is validated explicitly. It writes only
coarse counts/rates and path-free metadata under an ignored results directory:

```bash
python3 scripts/recommendation/analyze_poi_source_readiness.py \
  --raw-root "$RAW_ROOT" \
  --input "capital:TL=$CAPITAL_TL" --input "capital:VL=$CAPITAL_VL" \
  --input "west:TL=$WEST_TL" --input "west:VL=$WEST_VL" \
  --input "east:TL=$EAST_TL" --input "east:VL=$EAST_VL" \
  --input "jeju-islands:TL=$JEJU_TL" --input "jeju-islands:VL=$JEJU_VL" \
  --allow-approved-capital-filekey-folders \
  --confirm-approved --confirm-terms --confirm-poi-candidate \
  --run-id issue4-source-readiness-YYYYMMDD
```

Run synthetic contract checks with
`python3 -m unittest tests.test_poi_catalog_contract -v`. The script emits
`metrics.csv` and `run_metadata.json` under
`results/experiments/poi-source-readiness/<run-id>/`. Results exclude raw
paths, source filenames, identifiers, records, candidate lists, exact
coordinates, and free text. Counts use `0`, `<10`, or `10+`; rates use the
existing coarse bands and small-support suppression. No seed is needed.

The public TourAPI acquisition and identity run are reproducible with the
existing `TOUR_API_SERVICE_KEY` process variable. The acquisition code uses
the previously verified unchanged key representation, constructs the query in
memory, bounds page count/size, and never prints or saves the completed URL,
key, raw response, or exception text. It selects minimal public catalog fields
and display-state IDs into Git-ignored results; it never sends AI Hub data to
TourAPI. Replace each `NEW-DATE-vN` placeholder with a fresh unique run ID;
the scripts reject an existing destination:

```bash
python3 scripts/recommendation/acquire_tourapi_catalog.py \
  --run-id issue4-kto-NEW-DATE-vN --page-size 1000 --max-pages 80
python3 scripts/recommendation/acquire_tourapi_sync_state.py \
  --run-id issue4-kto-sync-NEW-DATE-vN --page-size 1000 --max-pages 100
python3 scripts/recommendation/analyze_poi_catalog_identity.py \
  --snapshot-id issue4-kto-NEW-DATE-vN \
  --sync-id issue4-kto-sync-NEW-DATE-vN \
  --run-id issue4-identity-NEW-DATE-vN
python3 scripts/recommendation/analyze_poi_catalog_scenarios.py \
  --snapshot-id issue4-kto-NEW-DATE-vN \
  --sync-id issue4-kto-sync-NEW-DATE-vN \
  --run-id issue4-scenarios-NEW-DATE-vN
```

The identity command reads current-process `RAW_ROOT` and eight approved
TL/VL role variables internally, validates them before row access, and writes
only coarse metrics and path-free metadata under ignored results. No sampling
is used; seed is `None`. Catalog and sync acquisitions are sequential live
reads, not an atomic transaction. A future refresh must revalidate both.
The scenario command records exact public inventory totals/type composition,
privacy-banded positive coverage, KTO legal-dong catalog groupings, and the
deterministic bounded sample frame. It never applies AI Hub visit region as a
request-area filter. The sample labels remain unadjudicated until a local
non-logging reviewer returns aggregate decisions.

### Validation on the revised worktree

- Four-region source-readiness run `issue4-source-readiness-20261014-rerun1`:
  completed with exit `0`; all eight TL/VL role bindings, four Other master
  roles, required table headers, and region-specific provenance checks passed.
  The ignored artifact contains 72 coarse metric rows and path-free metadata.
- `python3 -m unittest tests.test_poi_catalog_contract -v`: 23 synthetic
  tests passed.
- `python3 -m py_compile` on the six Issue scripts and the synthetic test
  module: passed.
- `git diff --check`: passed.
- `git check-ignore -v` on the run's metrics file confirmed the output is
  excluded by `/results/`.
- Bounded `areaBasedList2` acquisition: 49,622 rows, 50 pages, unique
  content IDs and first-page recheck passed. Bounded sync acquisition:
  49,622 displayed and 19,530 not-displayed IDs over 70 pages; the displayed
  ID set exactly equals the public listing ID set.
- Four-region identity run `issue4-identity-20261015-v3`: completed with exit
  `0`, 184 privacy-safe metric rows, validated catalog/sync hashes, all eight
  TL/VL bindings and four Other master roles, and zero TL/VL trip-ID overlap
  per region.
- Four-region type-scenario run `issue4-scenarios-20261015-v4`: completed with
  exit `0`, 857 privacy-safe metrics, 16 KTO legal-dong region groups, exact
  public inventory totals/type counts, and TL/VL positive coverage on common
  denominators. The deterministic sample selected 160 proposed matches
  (20 per region × TL/VL stratum); no pair fields were persisted and no
  independent adjudication labels were recorded.

The local run used the current working files, so its recorded Git revision is
the `dev` base plus a dirty-worktree flag and script hashes. The catalog and
sync input snapshot IDs and content hashes are recorded separately; the Git
revision alone does not represent the acquired data version.

**Facts:** The four AI Hub regional inputs and their roles have approved
repository provenance. The official KTO manual v4.4 defines content ID,
type, address, legal-dong codes, and display flag. A bounded current-public
catalog plus display-state snapshot passed pagination and ID validation.
The source-readiness and identity bands were run against the revised code.
The #59 TL proxy has no exposure guarantee.

**Inference:** The strict exact-string identity rule links fewer than ten
percent of observed source items in every region/split. Its recall is likely
limited by missing source metadata and untested address/name variation; its
precision has not been measured. Current displayed-list membership is a
defensible catalog status signal, but not operational or historical status.

**Unresolved:** Product content-type policy; actual request-time region,
district and category input contract; request-to-legal-dong crosswalk;
temporary closure/operational status; future ID stability and refresh cadence;
reviewed match precision and alternatives; product candidate coverage and
2023 availability. A non-displayed item is not necessarily deleted.

**Next decision:** Confirm the product type allowlist and request-time area
field with its validated code crosswalk, review an identity sample to set
precision/ambiguity policy, and define freshness/closure handling. Only then
compute product candidate size and positive coverage on a fixed, documented
request cohort. The account owner must separately confirm production rights
and traffic for serving.
