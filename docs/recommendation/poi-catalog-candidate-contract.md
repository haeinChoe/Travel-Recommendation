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
Stage 1 applies Unicode NFKC, case folding, and whitespace normalization to
both strings, then requires one exact normalized title plus address-string
pair. Stage 2 keeps the original source/catalog fields and builds separate
punctuation-to-separator and no-spacing candidate keys for names and address
fields. Punctuation is represented by a separator; it is never globally
deleted. The intentionally lossy keys retain every collision and retrieve
candidates only. Stage 3 uses name-token, two-character-prefix, admin-component
and address-piece blocks where available, then trigram blocks as a broader
fallback. Candidate generation is separate from identity decisions. Matching
operates within one complete approved catalog snapshot. A source `POI_ID` with
conflicting source metadata is held for review.

| Status | Deterministic rule | Meaning |
| --- | --- | --- |
| `MATCHED` | One and only one displayed catalog record has the same normalized nonblank title as source name and the same **address string** as the source road address, with a unique nonblank content ID. | Stage 1 provisional exact normalized-string link; TourAPI `addr1` is a generic address field and the result remains unreviewed. |
| `AMBIGUOUS` | Exact name exists but source address is missing, conflicts, or maps to multiple catalog records; or a canonical ID has conflicting records. | Keep all plausible alternatives internally; publish only aggregate conflict counts. |
| `UNMATCHED` | Source identity/name is unusable, or the snapshot has no exact normalized name candidate. | No link under this conservative rule; fuzzy/geographic matches may exist. |

Record source identity, proposed canonical ID only for `MATCHED`, method,
snapshot, and validation status in memory or an explicitly authorized ignored
artifact. The current Issue run writes **none** of those row-level values.
Report status by region, TL/VL, and method, with denominators for distinct
source items and observed positive events. Precision requires independent
reviewed labels and a representative ambiguity sample; match rate alone does
not establish correctness.

The enhanced analyzer emits privacy-safe phase markers for catalog loading,
sync validation, index construction, source-master scanning, candidate
generation, metric/sample aggregation, and aggregate writing. Source-master
progress is reported every 50,000 scanned rows and candidate generation is
reported in deterministic batches of 32 source items. Blocking-index traversal
callbacks occur every 100,000 entries and broad-set scoring callbacks every
5,000 candidates, while forwarded work-progress markers are limited to one
every 15 seconds per region. Atomic status checkpoints are written at phase,
region, and batch boundaries, with same-state heartbeats no more often than
every 15 seconds. A background heartbeat persists the current coarse phase,
region, batch, and completed-work bucket while a single candidate-scoring call
is still running; checkpoint replacement is serialized with main-thread updates.
Completed-work values and all small sample counts use the repository's coarse
buckets; identifiers and source/catalog values are never printed. Candidate membership
uses fixed-size arrays indexed by catalog row (16-bit block masks, generation
stamps, and first-discovery ordinals) plus a compact ordinal buffer capped at
one entry per catalog row. This replaces per-candidate dictionaries, block
sets, and full evidence objects. The generator retains only the configured
top-five evidence rows while preserving full candidate-record counts, all
blocking-rule coverage, ambiguity status, and full canonical-ID union counts
across source variants. Conflicted-source evidence deduplicates catalog records
by per-run row identity across variants while retaining separate per-variant
evidence for the adjudication interface. Before computing expensive similarity scores, safe
length and shared-character upper bounds skip candidates that cannot outrank
the current top-five floor; candidates still contribute to counts and blocking
coverage. Candidate-generation scratch memory is therefore bounded by catalog
size. Source metadata and aggregate analysis results are still held in memory
until final construction; restartable matching-result checkpoints are not
written. The separate atomic `run_status.json` records only coarse phase,
region, batch, status, and sanitized exception details on failure or
interruption. `run_metadata.json` and `sample_support.json` also bucket sample
size and selected counts; exact sample counts used to validate a reused audit
remain in memory only.

For `--audit`, terminal support is checked before catalog loading or source
input access. A terminal below the UI's minimum dimensions fails during
startup. After matching, metrics, and the sample frame are built, the analyzer
atomically writes aggregate-only `metrics.csv`, `sample_support.json`, and an
`aggregate_checkpoint.json` marked `incomplete` before it opens the manual
review UI. If review is cancelled, the terminal fails, or the process is
interrupted, that aggregate checkpoint remains incomplete and `run_status.json`
is `failed` or `interrupted`; temporary row-level audit evidence is deleted by
the UI cleanup path. The final metadata, audit-augmented metrics, completed
checkpoint, and `run_status.json=complete` are written only after successful
review and artifact construction. Consumers must treat `run_status.json` as the
completion authority; a checkpoint or aggregate file alone never means the run
completed.

Failed or interrupted audit runs are not resumable: use a fresh run ID to
recompute the source scan, candidate results, metrics, and sample frame. The
prior run's aggregate checkpoint remains useful for diagnosis but is not an
input to a rerun. `--reuse-audit-run-id` reuses a completed audit aggregate only
when the newly computed sample frame matches; it does not resume a failed run.
Successful run metadata records coarse duration bands (`<1m`, `1-5m`, `5-15m`,
`15m+`) for source scanning, candidate generation, metrics, sample framing, and
manual audit. When `--reuse-audit-run-id` validates and imports a completed
aggregate, no TUI review occurs: `audit_review` is `not_run` and the elapsed
time is recorded separately as `audit_reuse_validation`. These bands describe
execution phases without exposing row-level activity or exact sample counts.

A synthetic `cProfile` fanout check used 2,500 catalog entries and 10 source
items, with each source retrieving all 2,500 candidates. Before feature
caching, candidate evidence construction took 5.4 seconds and made about 23.5
million calls; normalization was repeated for every candidate and five
similarity calculations were made per candidate. Precomputing normalized
catalog features and source features reduced that check to 2.8 seconds and
about 10.0 million calls, with the same 2,500 candidates per source and the
same ranking policy. This synthetic timing is diagnostic, not a prediction of
actual-data runtime.

A second synthetic broad-fanout check used 25,005 catalog rows for one source
identity. The materialized reference and bounded resolver both counted all
25,005 records and returned the same top five. The reference took 0.498
seconds; bounded ranking took 0.241 seconds and built detailed evidence for
five records. A synthetic `cProfile` run of the bounded path took 0.562 seconds
under profiler instrumentation; the leading costs were the safe character
bound checks and block-index traversal. These single local timings are
diagnostic only, not actual-data runtime estimates.

Profiling the revised candidate path found exact `SequenceMatcher` scoring to
be the leading synthetic cost when many catalog rows repeated the same title
and address. A bounded 65,536-entry LRU cache for exact string-pair similarity
preserves the same score function and candidate ordering. On a synthetic
25,000-candidate duplicate fanout, elapsed time fell from 0.633 to 0.213
seconds (2.96x); full candidate count and top-five order were identical. This
fixture measures repeated string pairs and does not predict speedup on unique
catalog text.

Stage 2 punctuation-normalized name/address keys and Stage 3 fuzzy name
similarity are review-only candidate signals. Address-component parsing,
province/district aliases, and service-code crosswalks are unresolved; the raw
error analysis did not validate a specific abbreviation or administrative
mapping. Coordinate field validation is summarized below; AI Hub coordinate
meaning/CRS and TourAPI coordinate values remain unresolved, so coordinates
are unused. Category consistency is support evidence only. None of these
signals automatically promotes a result to `MATCHED`. Region namespaces remain
on AI Hub IDs until cross-region identity is proven.

Source variants are grouped by normalized name, road address, and lot address.
When all three normalized values agree, the implementation selects one
deterministic observed tuple for candidate generation rather than joining
variants into synthetic text. If the name or road address differs, the source
metadata is conflicting and the result remains ambiguous; candidate generation
evaluates each observed tuple together and the local review view preserves those
associations. If only the lot address differs, Stage 1 keeps its strict
name-plus-road result and the enhanced result requires review. The local review
view does not combine names or addresses from separate source rows.

### Coordinate field validation and limits

The four local AI Hub 2023 schema descriptions label the POI-master and visit
fields only as `X_COORD` (“X coordinate”) and `Y_COORD` (“Y coordinate”). They
do not identify a CRS, units, axis order, or transformation. A read-only scan
under the approved four-region TL/VL and Other-master provenance bindings
found the following pooled diagnostics; no coordinate values or point rows
were emitted or persisted:

| AI Hub table family | Rows checked | Both fields nonblank, finite numeric | Within hypothetical longitude/latitude axis bounds |
| --- | ---: | ---: | ---: |
| `TN_POI_MASTER` | 29,771,464 | 29,771,464 | 29,771,464 |
| `TN_VISIT_AREA_INFO` | 140,555 | 108,236 | 108,236 |

The visit table had 32,319 rows with at least one coordinate field blank. The
range check used only the hypothetical bounds `X ∈ [-180, 180]` and
`Y ∈ [-90, 90]`; no complete numeric pair was outside those bounds, and none
fit the swapped-axis bounds. These checks describe numeric shape only. They do
not establish geographic degrees, WGS84, another CRS, axis meaning, accuracy,
or same-place tolerance.

The existing KTO v1 listing snapshot contains 49,622 records and its recorded
field set excludes `mapx` and `mapy`. The local Issue documentation cites the
KTO manual revision but does not include a coordinate-field definition or CRS
statement. No new API request was made. Thus there is no approved local KTO
coordinate value to compare with AI Hub, even for the already adjudicated
exact-name/address pairs. No same-place distance distribution was computed.
Stage 4 remains disabled until both coordinate contracts and comparable
coordinate fields are documented and validated; then a bounded distance
analysis can be run on independently confirmed pairs.

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

`issue4-enhanced-20261015-v7` compares the three requested type scopes against
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
coverage is below 10% in every scenario at this reporting resolution. A does
show a higher rate of review-only candidate lists containing an in-scope type
than B or C, but those candidates are not confirmed identities or request-time
eligible items. Keep A/B as sensitivity alternatives and weigh that larger
review set against A's broader type semantics. C is not a serving default or
finalized allowlist; product scope, request geography, and match quality still
need decisions.

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

The A/B/C counts with missing `lDongRegnCd` are 1,018 / 1,017 / 0. The v7
ignored metrics also group confirmed identity-linked positive events by the
linked KTO `lDongRegnCd`, with each code/region/TL-VL share divided by the full
source-region positive-event denominator. These are post-hoc catalog-area
groups, not code-conditional recommendation coverage. Ambiguous, review, and
unmatched positives have no single linked catalog code and are not assigned to
one. Code-level rates use the small-cell suppression policy. AI Hub observed
region is not treated as a request-time selected area.

For observed visits, each A/B/C comparison uses the same usable positive-event
denominator within a region and TL/VL split. Across the eight region/split
cells, each scenario has the same coarse bands for confirmed identity status:
matched inside the scenario type scope `0–<10%`, matched outside that scope
`0–<10%`, `REVIEW` `10–<25%`, `AMBIGUOUS` `25–<50%`, and `UNMATCHED`
`25–<50%`. The observed-positive status bands therefore do not distinguish
the scenarios at this resolution. `UNMATCHED` is not evidence that the POI is
absent from the catalog.

Review-only candidate display differs by scope: across the same eight
region/split cells, candidate lists include at least one A item in `50–<75%`
of observed positives; B and C are each `25–<50%`. Candidate lists with no
in-scope type but at least one displayed out-of-scope type are `0–<10%` for A,
`10–<25%` in six B cells and `25–<50%` in two, and `10–<25%` in five C cells
and `25–<50%` in three. These are retrieval-review rates, not eligible
candidate coverage or confirmed identity links. The TL-observed proxy inside
share for VL positives is `25–<50%` in capital and `50–<75%` in the other
three regions, the same under A/B/C.

Per-code positive shares assign a positive only to a confirmed linked KTO
record; each uses the full source-region TL/VL positive denominator, not a
request-area denominator. The v7 metrics contain code-level rows for 13 KTO
legal-dong codes, privacy-banded and suppressed where support is below ten.
Unmatched, ambiguous, and review positives cannot be allocated to a single
KTO code.

These are global type-scope identity diagnostics, not evidence of serving-time
requests: the travel logs do not show that a user selected a region when
requesting recommendations. The user-provided official AI Hub v3.5 usage guide
defines purpose-region as a valid offline cohort for region-scoped evaluation.
Purpose-region-scoped catalog candidate coverage has not been computed because
no authoritative membership crosswalk from purpose-region to KTO
`lDongRegnCd` is available. This is distinct from request-time candidate
coverage, for which the serving contract and selected-area evidence remain
unresolved. TL-observed item membership remains a proxy only; unvisited items
remain unknown.

### Matching and candidate-review audits

The separate Stage 1 baseline audit sampled proposed `MATCHED` source items
under the unique normalized-name plus address-string rule, stratified by
region and TL/VL role. Within each stratum, SHA-256 ranked the in-memory source
identity using seed `issue4-match-audit-v1`; it selected 20 items in each of
the eight region × role strata. The ignored audit records aggregate labels
only; it stores no pair, ID, name, address, row, or coordinate.

The run selected 160 proposed pairs: 20 in each of the eight region × TL/VL
strata. All 160 use method `unique_exact_name_address`. A separate read-only
reviewer completed the local manual audit: 160 `MATCH`, 0 `NO_MATCH`, and 0
`UNCERTAIN` for that method. The local temporary evidence file was deleted
after completion and its deletion was verified.

This 160/160 result is an initial false-positive check for the unique exact
name-plus-address rule only. Its `MATCH` label was a manual judgment of that
single proposed pair. It is not a population precision estimate; the equal
stratum allocation, possible repeat identities across TL/VL, and selection
design prevent population precision and confidence intervals from being
claimed.

`scripts/recommendation/adjudicate_poi_match_sample.py` now provides the
private review path. Its data reader and renderer run under the dedicated
`herdr-data-science` profile. A reviewer other than the matching implementation
author is preferred and completed this audit on the local alternate-screen
terminal. The data-science process reads inputs, creates/deletes ephemeral
evidence, and writes the aggregate; the read-only reviewer needs only local TUI
visibility and input controls. The reproducible command is:

```sh
python3 scripts/recommendation/adjudicate_poi_match_sample.py --snapshot-id issue4-kto-20261014-v1 --sync-id issue4-kto-sync-20261014-v1 --run-id issue4-match-audit-independent-v1 --adjudicator-role independent
```

The data-science process needs current-process `RAW_ROOT` and all four region's
TL/VL bindings (`CAPITAL_*`, `WEST_*`, `EAST_*`, `JEJU_*`), the approved
read-only AI Hub 2023 inputs, the existing Git-ignored KTO listing/sync
snapshots, an interactive terminal with alternate-screen support (at least
80 × 18), and write access to the approved Git-ignored results location. The
read-only reviewer does not access the raw roots and needs only the local TUI
view and input controls. The tool checks the
terminal and revalidates source provenance and role mapping before raw row
access. Each split/master's data rows are scanned once after preflight. It
materializes only an ephemeral 160-record evidence file in a mode-0700
temporary directory; that file is mode 0600 and contains an ordinal, matching
method, and only source/catalog name, address, and type fields needed for
review. It contains no source/catalog identifiers or coordinates. The
alternate-screen local TUI reads that file and presents one pair at a time:
source name, road address, optional source classification codes, catalog title,
generic `addr1`, and `contentTypeId`. Source classification
codes and KTO types are **not** assumed to share a crosswalk. Keys `1`, `2`, and
`3` select only `MATCH`, `NO_MATCH`, and `UNCERTAIN`. The reviewer then presses
SPACE to confirm the selected label and advance exactly one pair; repeated label
keys before confirmation are ignored, and queued keys are flushed before the
next pair. `q` cancels. The screen is cleared between pairs and before exit.
A cancel or handled interruption before all 160 decisions leaves no review
output, and normal exception paths remove the temporary evidence. On
completion, the ignored result
contains only aggregate label counts overall and by matching method, plus the
adjudicator role; the temporary evidence file is immediately deleted and its
absence verified. No pair values, IDs, coordinates, paths, or per-row labels
are persisted. The reviewer must avoid terminal
capture, screenshots, and copying fields into shared logs. Record
`--adjudicator-role independent` only when a different reviewer actually makes
the decisions; use default `author` for self-adjudication. The tool cannot
verify who pressed the keys.

The enhanced candidate-generation review used a separate deterministic sample
of 144 deduplicated `(region, POI_ID)` identities, selected up to six per
region/identity stratum and split between development and validation
partitions. The previous UI asked for `MATCH`, `NO_MATCH`, or `UNCERTAIN` while
showing up to five candidates. The reviewer clarified that `MATCH` meant **at
least one displayed candidate looked like the same place**. It did not specify
which candidate, distinguish the primary candidate, or establish a pairwise
decision. The observed 48 `MATCH`, 30 `NO_MATCH`, and 66 `UNCERTAIN` labels
are therefore only adjudicated hit/no-hit/uncertain outcomes among at most
five displayed candidates. They are not pair precision, top-1 accuracy,
recall, or threshold validation.

| Candidate method | Sample stratum | Reviewed | MATCH / NO_MATCH / UNCERTAIN |
| --- | --- | ---: | ---: |
| `unique_exact_name_address` | `strict_matched` | 24 | 24 / 0 / 0 |
| `exact_name_address_string_variant` | `stage2_normalized_review` | 24 | 16 / 2 / 6 |
| `exact_name_address_string_variant` | `missing_metadata` | 1 | 0 / 0 / 1 |
| `fuzzy_character_trigram_block` | `stage3_fuzzy_review` | 24 | 2 / 21 / 1 |
| `fuzzy_character_trigram_block` | `multi_candidate_ambiguous` | 24 | 4 / 7 / 13 |
| `fuzzy_character_trigram_block` | `missing_metadata` | 4 | 2 / 0 / 2 |
| `missing_source_name` | `missing_metadata` | 19 | 0 / 0 / 19 |
| `no_candidate_block_hit` | `still_unmatched` | 24 | 0 / 0 / 24 |
| **Total** | | **144** | **48 / 30 / 66** |

This audit's display cap and ambiguous label semantics limit what its outcomes
mean. It did not tune any threshold. The stratified selection was not weighted
by frame size, and only `(region, POI_ID)` was deduplicated; cross-region
identity and population weights remain unresolved. Do not combine its counts
with the 160-item Stage 1 baseline audit.

After Stage 2 added a punctuation-normalized full-address key, a new
deterministic targeted sample selected six source identities per region for
the new `punctuation_address_variant` method (24 total), deduplicated within
region by `POI_ID`. This UI explicitly showed one primary candidate and asked
whether that presented pair was the same place. It returned 15 `MATCH`, 8
`NO_MATCH`, and 1 `UNCERTAIN`; development (12) was 9 / 2 / 1 and validation
(12) was 6 / 6 / 0. These are observed primary-pair sample outcomes for this
new candidate method only. They are not population precision or confidence
intervals, and the partitions are too small and selection too limited to
validate a production rule or tune a threshold. The targeted audit is separate
from both earlier audits.

The later Stage 2 multi-rule block also created a method/stratum not covered by
the preserved v4 candidate-set audit. A new deterministic sample selected up to
six `(region, POI_ID)` identities per region (24 total), deduplicated by region
and source ID. The independent reviewer was explicitly asked to judge the
single presented primary candidate pair. The aggregate was 2 `MATCH`, 20
`NO_MATCH`, and 2 `UNCERTAIN`; development (12) was 1 / 11 / 0 and validation
(12) was 1 / 9 / 2. These are primary-pair judgments for this sample only.
They are not population precision or confidence intervals, and are not
combined with the 144-candidate-set audit, the 160-item strict baseline audit,
or the separate punctuation-address sample. No threshold was tuned.

#### Enhanced audit2: candidate-set adjudication and A/B/C diagnostics

The completed run `issue4-enhanced-20261016-audit2` is a separate enhanced
candidate-set audit. Its aggregate artifacts record code revision `b5aa7cc`
with a dirty-worktree flag, catalog/sync snapshot IDs and hashes, the
privacy-banded sample support, and the aggregate audit labels. The run selected
items from six populated strata: `strict_matched`,
`stage2_normalized_review`, `stage3_fuzzy_review`,
`multi_candidate_ambiguous`, `still_unmatched`, and `missing_metadata`. The
stratified sample was not weighted by stratum size.

| Candidate method | Reviewed | MATCH / NO_MATCH / UNCERTAIN |
| --- | ---: | ---: |
| `unique_exact_name_address` | 3 | 3 / 0 / 0 |
| `strict_pair_with_signal_conflict` | 24 | 24 / 0 / 0 |
| `exact_name_address_string_variant` | 19 | 15 / 1 / 3 |
| `punctuation_address_variant` | 4 | 2 / 2 / 0 |
| `spacing_name_variant` | 2 | 2 / 0 / 0 |
| `stage3_multi_block_candidates` | 24 | 4 / 19 / 1 |
| `address_piece_block` | 23 | 1 / 22 / 0 |
| `fuzzy_character_trigram_block` | 1 | 0 / 1 / 0 |
| `missing_source_name` | 19 | 0 / 0 / 19 |
| **Total** | **119** | **51 / 45 / 23** |

The UI displays up to five candidates for each source name/road/lot pair group.
An item with conflicting source metadata can therefore have multiple displayed
groups and more than five candidates overall. `MATCH` means a same-place
candidate appeared in any displayed pair group. Thus `51 / 119 = 42.9%` is
only the **adjudicated sample candidate-hit share**: at least one displayed
same-place candidate appeared for that share of reviewed sample items. It is
not precision, recall, top-1 accuracy, or a population estimate, and it does
not establish a candidate beyond the displayed pair groups. A `MATCH` did not
mean the first candidate in a group was correct. The result is separate from
the earlier 160-item strict-baseline audit; labels from the two samples are not
pooled.

The same run's metrics report A/B/C inventory totals of 49,622 / 21,025 /
19,069 catalog records. On the observed-positive comparison, each scenario
uses the same usable positive-event denominator within each of the same eight
source-region × TL/VL cells; shares are privacy-banded and cells are not
weighted together. Across those cells, A/B/C each have `REVIEW` in two cells
at `10–<25%` and six at `25–<50%`, `AMBIGUOUS` in six at `25–<50%` and two
at `50–<75%`, and `UNMATCHED` in two at `10–<25%` and six at `25–<50%`.
Confirmed identity matched inside the type scenario is `0–<10%` in all eight
cells for B/C; A has six cells at `0–<10%` and two suppressed below the
minimum support rule. Matched outside the type scenario is `0–<10%` in all
eight cells for A; B/C have six cells at `0–<10%` and two suppressed. The
metrics therefore do not show a material difference in confirmed identity
status by type scope at this resolution. Review-only displayed candidates
include at least one in-scope record in six A cells at `50–<75%` and two at
`75–<90%`; for B/C, six cells are `50–<75%` and two are `25–<50%`. These
candidate-display shares are retrieval diagnostics, not request-time
eligibility or confirmed links.

The complete run took about 44 minutes 45 seconds from the supplied run
directory birth time, 2026-10-16 14:16:49 KST, to the completed status time,
15:01:34 KST. The exact total was measured from those artifact timestamps.
`run_metadata.json` reports source scan `1–5m`, candidate generation `15m+`,
metrics `<1m`, sample-frame construction `<1m`, and manual audit `5–15m`.
Candidate generation was the dominant phase. Synthetic profiling did not
identify a new optimization target. The earlier audit1 attempt failed for a
different reason: its private TTY was below the supported 80 × 18 size, but
the size check ran only after about 31m43s of source scan, candidate generation,
metrics, and sample-frame computation. The TUI then raised `ValueError` before
aggregate files were written. Cleanup of its temporary raw evidence was
verified. Audit2 completed with the preflight and checkpoint behavior in the
validated implementation.

**Facts:** The aggregate audit labels total 119 and the metrics include the
scenario inventories and common-denominator, privacy-banded A/B/C comparisons.
The run reports no persisted row labels, source IDs, names, addresses, or
coordinates. Audit2 is complete; its recorded phase bands put candidate
generation above 15 minutes and each metrics/sample-frame phase below one
minute.

**Interpretation:** The 42.9% candidate-hit share describes only these
adjudicated sample items: a same-place candidate appeared in at least one
displayed pair group, with up to five candidates per group. The reviewed
outcomes support retaining enhanced candidates for manual review and keeping
all automatic decision boundaries unchanged. The current metrics show little
scenario separation in identity-status bands, while A has broader in-scope
candidate display at these bands.

**Limitations:** The stratified audit is unweighted and is not a population
estimate. Each pair group's display cap can hide additional candidates beyond
the five shown, and `MATCH` does not identify a winning rank. Source-region/TL/VL
cohort metrics do not establish request-area candidate coverage. The official
AI Hub v3.5 purpose-region is a valid offline cohort, but there is no evidence
that a user selected that region at serving time. Purpose-region-scoped trip
coverage remains uncomputed because authoritative membership to KTO
`lDongRegnCd` is unavailable. Inventory totals describe catalog composition,
not the request contract. A/B/C and all product contracts remain open. Earlier
source-readiness bands came from a prior run and their provenance against the
revised code is pending a data-science rerun.

**Next decision:** Obtain authoritative evidence for any purpose-region to
`lDongRegnCd` membership crosswalk before estimating region-scoped trip
coverage. Keep the existing A/B/C, request-area, type-allowlist, and serving
contracts open pending product decisions and representative, appropriately
weighted validation.

The matching implementation and UI are in
[`poi_identity_contract.py`](../../scripts/recommendation/poi_identity_contract.py),
[`analyze_poi_catalog_enhanced.py`](../../scripts/recommendation/analyze_poi_catalog_enhanced.py),
and [`adjudicate_poi_candidate_sample.py`](../../scripts/recommendation/adjudicate_poi_candidate_sample.py).
Only aggregates are durable. Local evidence is held transiently in memory and
a mode-0600 file inside a mode-0700 temporary directory; the alternate-screen
TUI clears each pair before advancing and cleanup is verified. For this
candidate-audit tool, handled `SIGINT` and `SIGTERM` before completion leave no
aggregate and clean the temporary evidence. `SIGKILL` or host/power failure
cannot run process cleanup and may leave the mode-restricted temporary file
until the operating system removes it. The v4 144-label
aggregate was preserved unchanged. The v7 punctuation-address and v8 multi-rule
targeted audits each persist only aggregate labels by method/stratum/partition;
both temporary evidence directories were deleted. No raw values, identifiers,
coordinates, paths, or per-row labels are in repository artifacts.

### Strict-baseline error analysis

The data-science error-analysis phase examined 37,397 distinct `(region,
POI_ID)` identities that remained `UNMATCHED` or `AMBIGUOUS` under the strict
baseline. These are aggregate displayed-candidate evidence flags; categories
overlap and must not be added together.

**Facts:**

| Evidence flag | Count |
| --- | ---: |
| Name-only variation | 505 |
| Address-only variation | 255 |
| Both name and address differ | 13,115 |
| Source POI master missing | 19,321 |
| Multiple catalog candidates | 13,739 |
| No current blocking candidate | 23,658 |

**Interpretation:** The findings support broader name/address blocking and
separate missing-source-metadata handling. Variation or similar-name evidence
covers at most five displayed candidates per source identity; it does not
confirm that any candidate is the same place. No candidate from a blocking
rule means only that the current blocks did not retrieve one. `UNMATCHED` does
not mean the POI is absent from the catalog.

**Limitations:** Administrative wording, road-versus-lot address variation,
and renamed or discontinued places were not measured. Coordinates remain
unusable because AI Hub CRS and axis meaning are unverified and the TourAPI
snapshot has no coordinates. The aggregate counts do not justify fuzzy
thresholds, address aliases, road-number parsing, or administrative
membership rules.

**Next decision:** Re-run the privacy-safe enhanced analysis and purpose-region
scenario diagnostics under the data-science role. Keep A/B/C type scopes,
request-area contract, crosswalk, content allowlist, and all product contracts
open pending evidence and product decisions.

The enhanced reference pipeline keeps candidate generation separate from
identity decisions:

| Stage | Rule and output | Decision boundary |
| --- | --- | --- |
| 1 | Existing unique NFKC/case/whitespace-normalized name plus exact normalized address-string matcher. | Only this established rule may return provisional `MATCHED`; the 160-item baseline audit is a separate initial false-positive check. |
| 2 | Separate collision-preserving NFKC/case/whitespace/punctuation-to-separator and no-spacing name/address keys. Source road and lot values stay typed; KTO `addr1` remains generic and is not relabeled as road or lot. Keep every colliding record, show at most five candidates, and record full candidate counts. | Every recovered candidate remains for review. Multi-candidate sets are `AMBIGUOUS` and require review; conflicts remain `REVIEW`/`AMBIGUOUS`. Address fields of different types can retrieve a candidate but cannot prove equivalence. |
| 3 | Name token and prefix, address-piece and explicitly validated administrative-component blocking, followed by character-trigram name blocking when earlier blocks find nothing. Record each blocking rule and full candidate count; show at most five candidates locally. | Similarity scores only order review evidence. There is no score threshold and no fuzzy automatic match. Admin signals are ignored unless a validated crosswalk is explicitly supplied. |
| 4 | Coordinate matching disabled. | Reconsider only after both coordinate fields' meaning, CRS, value ranges, and same-place distance distribution are validated. |
| 5 | Source classification and KTO type remain auxiliary descriptive metadata. | They do not block candidates or contribute identity decisions; no type equality is assumed without a validated crosswalk. |

Across all stages, `MATCHED`, `REVIEW`, `AMBIGUOUS`, and `UNMATCHED` remain
distinct. A unique Stage 2/3 candidate is not `MATCHED`; `UNMATCHED` means the
implemented blocking rules found no candidate and is not evidence of catalog
absence. No fuzzy threshold, address abbreviation, address-type conversion,
province/district alias, or transliteration is inferred from retrieval evidence.
The ignored analysis records privacy-banded candidate-count distributions
grouped by method and blocking rule; displayed top-five counts do not replace
the full generated-candidate count. For conflicting source metadata, the local
audit displays up to five candidates separately for each observed name/road/lot
tuple, so a larger tuple group cannot hide candidates associated with a
different source metadata tuple.
AI Hub purpose-region is a legitimate offline cohort/conditioning field when
the evaluation is explicitly scoped to observed purpose-region groups; this is
distinct from evidence of a user's serving-time selected region. The
user-provided official AI Hub v3.5 usage guide defines four purpose regions and
describes POI provenance as user-provided; that guide was not checked into this
repository. The [official AI Hub domestic travel-log dataset page](https://www.aihub.or.kr/aihubdata/data/view.do?aihubDataSe=data&currMenu=115&dataSetSn=71776&topMenu=100)
is linked as the public dataset reference. The checked-in
`aihub-71776-capital.md` is a conversion of the data description, not the v3.5
usage guide, and it does not explicitly map purpose-region memberships to KTO
`lDongRegnCd`. Accordingly, no membership is guessed:
`purpose_region_mapping_status` reports `UNMAPPED` for a supported
purpose-region without a versioned authoritative mapping and `UNSUPPORTED` for
an unknown value. Offline purpose-region-scoped KTO candidate coverage remains
uncomputed until an authoritative membership crosswalk is available. The
Stage 1 result remains reproducible alongside enhanced statuses.

The v4 candidate-generation audit and v7 targeted Stage 2 address audit are
reported separately above. Each uses deduplicated `(region, POI_ID)` identities,
deterministic hash selection, and a maximum of six identities per region and
stratum. The v4 UI used an “any displayed candidate” hit label with up to five
items; the v7 targeted UI explicitly judged a single primary pair. Neither
audit tuned or deployed a threshold. These small stratified samples are
descriptive only; no population recall, precision, or confidence interval is
claimed.

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

### Enhanced identity outcomes for the current listing

`issue4-enhanced-20261015-v7` applied the staged candidate generator to the
same approved four-region source roles and the same v1 listing/sync snapshots.
The table uses distinct source identities within each region/role. `Stage 1`
and `Enhanced MATCHED` are the same strict-rule link share; Stage 2/3 outputs
remain review states. `Recovered among review` is the share of enhanced
`REVIEW`/`AMBIGUOUS` identities whose Stage 1 status was `UNMATCHED`; it is a
retrieval diagnostic, not an audited match rate.

| Region | Role | Stage 1 / MATCHED | REVIEW | AMBIGUOUS | UNMATCHED | Recovered among review |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Capital | TL | 0–<10% | 10–<25% | 25–<50% | 50–<75% | 75–<90% |
| Capital | VL | 0–<10% | 10–<25% | 25–<50% | 25–<50% | 75–<90% |
| West | TL | 0–<10% | 10–<25% | 25–<50% | 50–<75% | 75–<90% |
| West | VL | 0–<10% | 10–<25% | 25–<50% | 25–<50% | 50–<75% |
| East | TL | 0–<10% | 10–<25% | 25–<50% | 50–<75% | 75–<90% |
| East | VL | 0–<10% | 10–<25% | 25–<50% | 25–<50% | 75–<90% |
| Jeju/islands | TL | 0–<10% | 10–<25% | 25–<50% | 25–<50% | 75–<90% |
| Jeju/islands | VL | 0–<10% | 10–<25% | 25–<50% | 25–<50% | 75–<90% |

Every row has support of at least ten. The current candidate-count metrics retain
the full count in coarse buckets (`0`, `1`, `2–4`, `5+`) by method and blocking
rule; the local audit UI displays no more than five. The Stage 2 address method
is present in this run and is separately sampled in the v7 targeted audit
above. The method requires manual review even when it returns one candidate.
No address component, administrative alias, or coordinate feature is used.

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
request-area filter. The separately completed independent manual audit judged
all 160 sampled `unique_exact_name_address` pairs as `MATCH` (0 `NO_MATCH`, 0
`UNCERTAIN`); only aggregate labels are retained. The v4 candidate-set review,
v7 punctuation-address primary-pair audit, and v8 multi-rule primary-pair audit
are reported above with distinct label meanings and sample frames. Product
content-type and request-area contract choices remain open.

The current staged analysis is reproduced with the existing ignored snapshot
IDs and a fresh unique run ID. This command performs the targeted primary-pair
audit and therefore requires the local independent reviewer UI:

```bash
python3 scripts/recommendation/poi_run_supervisor.py \
  --snapshot-id issue4-kto-20261014-v1 \
  --sync-id issue4-kto-sync-20261014-v1 \
  --run-id issue4-enhanced-NEW-DATE-vN \
  --audit --audit-method punctuation_address_variant \
  --audit-primary-pair --adjudicator-role independent
```

The supervisor forwards only allowlisted progress and failure markers, deriving
its region allowlist from `evaluate_popularity.REGIONS`. It records the analyzer
exit code or terminating signal independently from any output-sanitizer error.
It reads child pipes in fixed-size chunks, drops lines over 500 bytes, and uses
a bounded queue so unapproved output floods do not accumulate in memory. If the
supervisor receives SIGTERM, it forwards the signal, drains both pipes, waits
for the analyzer checkpoint, restores its prior handler, and exits with 143.
Each run directory has a private, atomically replaced `run_status.json` with
aggregate-only phase, region, and batch fields. Safe failures include exception
type and traceback basenames/line numbers, never messages or local paths. A
`running` state after abrupt termination is incomplete; failed or interrupted
runs remain incomplete even if aggregate files were partially written. Readers
must require `run_status.json` to say `complete` before accepting any aggregate.
Use a fresh run ID for every attempt; the analyzer refuses to reuse an existing
run directory.

The analyzer groups source identities by region once before `_metrics` builds
the four role scopes. This avoids repeatedly filtering the full identity map
without changing scope membership or metric definitions. Candidate support
remains exhaustive; only displayed evidence is bounded to the existing top-five
review cap.

The separate newly introduced multi-rule stratum is reproduced with a fresh
unique `--run-id issue4-enhanced-NEW-DATE-vN --audit-method
normalized_multi_rule_candidates` and the same `--audit-primary-pair
--adjudicator-role independent` options. Its aggregate is separate from v7.

### Validation on the revised worktree

**Current validation after audit2 evidence update (2026-10-16):**

- Focused synthetic/privacy/supervisor suite:
  `python3 -m unittest tests.test_poi_catalog_enhanced tests.test_poi_candidate_adjudication tests.test_poi_catalog_contract tests.test_poi_run_supervisor tests.test_poi_match_adjudication` — 105 tests passed.
- Repository Python suite: `python3 -m unittest discover -s tests` ran 247
  tests and ended with 3 failures and 6 import errors. The import errors are
  missing `matplotlib` for `test_eda_privacy_buckets` and missing `duckdb` for
  `test_eda_safety_smoke`, `test_extract_travel_log_csvs`,
  `test_profile_codebook_only`, `test_recommendation_fit`, and
  `test_travel_log_archive_metadata`. The three
  `test_travel_log_code_domains` failures received `output_path_invalid` from
  the restricted output-path environment before the expected codebook path
  validation error could be observed.
- Direct `pytest -q` was unavailable because the `pytest` executable is not
  installed. No packages were installed.
- `npm test`: TypeScript type-check passed; 10 of 11 Node tests passed. The
  unchanged failure is the TL/VL binding test in
  `tests/data-scientist-skill-docs.test.ts`, which expects “Role validation”
  in the unchanged `.agents/skills/travel-data-scientist/references/domain-review.md`.
- `python3 -m py_compile` on the changed recommendation scripts and focused
  test modules passed. `git diff --check` passed; Git emitted only the existing
  LF-to-CRLF working-copy warnings.

- Four-region source-readiness run `issue4-source-readiness-20261014-rerun1`:
  completed with exit `0`; all eight TL/VL role bindings, four Other master
  roles, required table headers, and region-specific provenance checks passed.
  The ignored artifact contains 72 coarse metric rows and path-free metadata.
- `python3 -m unittest tests.test_poi_catalog_contract -v`: 23 synthetic
  tests passed.
- `python3 -m py_compile` on the six Issue scripts and the synthetic test
  module: passed.
- `git diff --check`: passed.
- Final focused synthetic suite
  `python3 -m unittest tests.test_poi_catalog_contract tests.test_poi_match_adjudication tests.test_poi_candidate_adjudication tests.test_poi_catalog_enhanced`:
  62 tests passed. `py_compile` on the changed identity, analysis, adjudication,
  and focused test modules passed; staged and worktree `git diff --check` passed.
- Broad fallback `python3 -m unittest discover -s tests`: 201 tests, with 3
  failures and 6 errors. The three code-domain tests fail on sandbox
  output-path validation; the six errors are missing `matplotlib` and `duckdb`
  dependencies in EDA/recommendation tests. `pytest` and `ruff` are unavailable
  in the environment, and package installation is blocked by the registry.
- `npm test`: TypeScript compilation passed and 10/11 Node tests passed. The
  unchanged failure is `explicit TL/VL bindings are validated instead of
  re-inferred from path names` in
  `tests/data-scientist-skill-docs.test.ts`; its assertion expects “Role
  validation” in the unchanged `domain-review.md`. This is independent of the
  Python identity diff.
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
  per-pair evidence was persisted. The separate independent manual audit
  returned 160 `MATCH`, 0 `NO_MATCH`, and 0 `UNCERTAIN` for
  `unique_exact_name_address`; these aggregate sample results do not establish
  population precision or confidence intervals.
- Four-region enhanced run `issue4-enhanced-20261015-v7`: completed with exit
  `0`; the punctuation-address primary-pair sample was independently reviewed
  (15 / 8 / 1 MATCH / NO_MATCH / UNCERTAIN). Separate enhanced run
  `issue4-enhanced-20261015-v8` completed its new multi-rule primary-pair
  sample with 24 independent labels (2 / 20 / 2); neither sample is a
  population estimate, and their labels were not combined.
- The `issue4-enhanced-20261015-v6` aggregate is pre-source-spelling-fix
  evidence. Its catalog inventory/type-composition values remain snapshot
  facts, but its source-linked coverage and candidate-generation metrics are
  historical and are not current-code results.
- Post-fix run v9 failed before output creation. Post-fix run v10 reached audit
  reuse but was rejected because its newly generated sample frame was
  incompatible with the preserved v4 aggregate. At that point, no post-fix
  aggregate metrics were available; the v4 audit labels were unchanged. The
  later completed audit2 run and its separate labels are reported above.
  A/B/C scenarios and all product contract choices remain open; the scenarios
  are decision evidence only.
- Coordinate metadata diagnostic scanned the approved four-region AI Hub
  inputs after source-role/provenance validation. The AI Hub schema provides
  no CRS, axis, or unit definition; all complete pairs happened to fit the
  hypothetical longitude/latitude bounds. The KTO snapshot omits coordinate
  fields, so no same-place distances were available or calculated. Stage 4
  remains disabled.

The local pre-fix runs used the then-current working files, so their recorded
Git revisions are the `dev` base plus dirty-worktree flags and script hashes.
The catalog and sync input snapshot IDs and content hashes are recorded
separately; the Git revision alone does not represent the acquired data
version.

**Facts:** The four AI Hub regional inputs and their roles have approved
repository provenance. The official KTO manual v4.4 defines content ID,
type, address, legal-dong codes, and display flag. A bounded current-public
catalog plus display-state snapshot passed pagination and ID validation.
The earlier source-readiness bands remain pre-source-spelling-fix evidence;
their provenance against the revised code is pending a data-science rerun.
The enhanced audit2 run completed and its separate current-code aggregate
results are recorded above. The #59 TL proxy has no exposure guarantee.

**Inference:** The pre-fix Stage 1 strict link share is below ten percent for
every region and TL/VL role. The 160-item independent audit returned 160 `MATCH`
under its single proposed unique exact name-plus-address rule; this is an
initial false-positive check for that sample only. The 144-label candidate
review means “at least one of up to five displayed candidates looked like the
same place,” and the targeted 24-item address and multi-rule audits each
judged one primary pair at a time. None is a population precision estimate.
The punctuation-address audit's 15 / 8 / 1 and the multi-rule audit's 2 / 20 /
2 MATCH / NO_MATCH / UNCERTAIN outcomes support keeping those candidates in
manual review. Coordinate axis-bound counts do not validate CRS or distances.
No threshold was tuned. Current displayed-list membership is a catalog
display-state signal, not operational or historical availability.

**Unresolved:** Product content-type policy; actual request-time region,
district and category input contract; request-to-legal-dong crosswalk;
province/district aliases and road-number/address-component parsing; coordinate
semantics; temporary closure/operational status; future ID stability and
refresh cadence; population-level match precision, confidence intervals, and
alternatives; product candidate coverage and 2023 availability. A
non-displayed item is not necessarily deleted.

**Next decision:** Confirm the product type allowlist and request-time area
field with its validated code crosswalk, decide how the three distinct sample
audits and unresolved population-level evidence should inform a
precision/ambiguity policy, and define freshness/closure handling. Only then
compute product candidate size and positive coverage on a fixed, documented
request cohort. Obtain authoritative mapping evidence before computing
purpose-region-scoped KTO candidate coverage; this offline cohort does not
establish a user's serving-time selected region. The account owner must
separately confirm production rights and traffic for serving.
