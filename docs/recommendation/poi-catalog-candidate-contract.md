# POI catalog and candidate eligibility contract

## Status

**Outcome: incomplete, with a deterministic implementation contract ready for an authorized, verified catalog snapshot.** TourAPI is a credible source candidate, but retention/crawling permission remains unresolved. A boolean check confirmed the environment string used for requests was already a canonical percent-encoded representation; its value was not disclosed. Three user-authorized, one-result, read-only GETs to the official `areaCode2` endpoint on `apis.data.go.kr` establish the encoding chronology: the first two passed the key through another encoding operation and returned HTTP 403 / API code `UNAVAILABLE`; the third used the unchanged key as raw query text and returned HTTP 200 / API `0000`. This verifies a successful response only for `areaCode2`.

The POI endpoint chronology is separate. Two earlier one-result, unfiltered `areaBasedList2` probes using the unchanged key failed at DNS before an HTTP connection. A later ordinary run was blocked by the stale sandbox before execution. After the exact host was added to the existing `herdr-data-science` profile and guarded startup restarted that profile, one one-result `areaBasedList2` request reached the host and returned HTTP 200 / API `0000`. The response envelope was an object. The sample row was discarded after inspecting only field names and types; every observed field was a string: `addr1`, `addr2`, `areacode`, `cat1`, `cat2`, `cat3`, `contentid`, `contenttypeid`, `cpyrhtDivCd`, `createdtime`, `firstimage`, `firstimage2`, `lDongRegnCd`, `lDongSignguCd`, `lclsSystm1`, `lclsSystm2`, `lclsSystm3`, `mapx`, `mapy`, `mlevel`, `modifiedtime`, `sigungucode`, `tel`, `title`, `zipcode`. No row values, response body, credential, or request URL were retained. This single response proves neither uniqueness, complete field semantics, authorization beyond this endpoint, permission for bulk retrieval/retention, nor product coverage. No verified mapping exists from the broad AI Hub region labels to TourAPI `areaCode` values. No catalog snapshot was obtained, and current API access cannot establish 2023 availability.

The current product authoritative catalog, includable content types, refresh schedule, status semantics, and serving SLA remain unresolved. `TN_POI_MASTER` is a separate historical AI Hub reference table, not the serving catalog, and it was not read in this run. `TN_VISIT_AREA_INFO.POI_ID` is an observed field candidate; neither its foreign-key relationship nor value identity with the master is established by the reviewed data dictionary. Any string-level join is diagnostic only.

## Question and evaluation meaning

The product question is whether an observed visit can be linked with defensible identity to an item the product could recommend from a catalog under request-time constraints. `TN_VISIT_AREA_INFO` observations are implicit positives for feasibility checks; unvisited items remain unknown. The travel logs contain no historical impression or exposure record, so a current eligible set describes what the product could recommend under a contract, not what a traveler saw or could choose historically.

Recommendation-time eligibility may use an explicit request region, an explicitly selected district, catalog fields available at that request, and a product-owned supported-type policy. It must not use observed visit category/location, post-event satisfaction, revisit intention, recommendation intention, or other information learned after the request. Style, motive, and inferred preference remain ranking inputs unless the user explicitly selects a filter.

## Catalog record and snapshot contract

For any future verified snapshot, store only fields needed for candidate construction and identity diagnostics. Names below are normalized internal adapter fields, not claims about literal TourAPI response property names; map them only after reviewing the current official endpoint guide:

| Field | Contract |
| --- | --- |
| `catalog_source` | Provider and API family; required namespace. |
| `content_id` | Provider item identifier, preserved as a string. Do not strip leading zeroes. |
| `content_type_id` | Provider classification identifier; retain separately and require an approved type policy. |
| `title` | Identity signal; normalize Unicode and whitespace only. |
| `area_code`, `sigungu_code` / legal-dong codes | Region/district evidence only after a reviewed mapping to the product's administrative codes. |
| `addr1`, `addr2` | Identity evidence; keep local and out of shared diagnostics. |
| `mapx`, `mapy` | Coordinates; preserve the provider's documented coordinate encoding and CRS. Do not use until converted and validated. |
| `cat1`, `cat2`, `cat3` and new taxonomy fields | Taxonomy evidence; mappings are versioned policy, not identity. |
| `modifiedtime`, sync/deletion state | Refresh evidence. Absence from one response does not itself prove deletion. |
| `snapshot_at`, `snapshot_version`, `request parameters`, `policy version` | Required for reproducible candidate construction. Do not persist credentials. |

The [official data.go.kr KorService2 listing](https://www.data.go.kr/data/15101578/openapi.do) identifies the KorService2 family and GET `areaBasedList2` for regional tourism information, with response model `areaBasedList2_response` and REST JSON/XML formats. It lists free use, unrestricted reuse metadata, automatic development approval, operational review approval, and a development quota of 1,000. The [official Korean Tourism Organization portal](https://api.visitkorea.or.kr/?loginFlag=sso) FAQ says its OpenAPI guide requests/responses are for service planning and request/response debugging, and warns against unauthorized caching or crawling. These current official sources do not settle whether this product may retain or bulk snapshot the catalog; this remains unresolved. The successful one-result `areaBasedList2` response established an object envelope and the field names/types recorded above, but did not establish full field meanings, unique identifiers, complete authorization scope, or retention permission. Before adapter approval, review the current official field definitions for provider ID/type ID, title, administrative codes, address, coordinate encoding/CRS, category taxonomy, update/deletion semantics, attribution, pagination, and endpoint-specific availability. Neither current metadata nor this response establishes catalog availability in 2023, that returned records are open or bookable, or that they suit every product request. No further POI calls or catalog-page retrieval is authorized while retention/crawling terms remain unresolved.

### Canonical identity

No canonical key has been approved from observed values alone. A proposed provider key is `(catalog_source, content_id)` with `content_type_id` retained as a consistency attribute; confirm provider uniqueness rules before production use. AI Hub source identity remains `(region, nonblank observed POI_ID)`. Do not remove the region namespace or equate either AI Hub field with TourAPI `content_id` until validation establishes that contract.

## Identity mapping rules

The reusable matcher is deterministic and fail-closed:

1. Normalize text with Unicode NFKC, casefolding, and whitespace collapse; do not strip punctuation, transliterate, or use edit-distance as identity.
2. A unique exact normalized name plus exact nonblank address, or exact normalized name plus reviewed administrative area, can return `MATCHED` if all other available exact signals agree. An explicitly supplied category/type crosswalk may veto a match when it shows a conflict; a missing or unmapped type is unresolved evidence, not a contradiction.
3. Exact name alone, coordinate coincidence, fuzzy-name similarity, and distance are discovery evidence only; they return `AMBIGUOUS` when candidates exist.
4. Multiple equally strong candidates, contradictory exact signals, duplicate catalog keys in a snapshot, explicit taxonomy conflicts, or missing identity evidence never silently resolve to one item.
5. No qualifying candidate returns `UNMATCHED`. The matcher returns status, method, and candidate count with in-memory source/catalog keys. Any future persisted mapping record must additionally store source identity, catalog snapshot/version, and validation state. Confidence scores and thresholds are not implemented or enabled by default.

The data dictionary describes `TN_POI_MASTER.POI_ID`, name, administrative code, addresses, categories, and coordinates as table fields. It does not provide coordinate reference semantics or declare a relationship constraint from `TN_VISIT_AREA_INFO.POI_ID`. The same rules therefore apply only as candidate-match diagnostics until field semantics and table linkage are independently established.

## Request-time eligibility

`eligibility_reason` is a pure function over a catalog record and explicit policy. It applies hard constraints in this order: request-region mapping, catalog active status, supported content type, catalog membership in the requested region, and (only when explicitly supplied) request district. Unknown status, unmapped request region, missing type, and missing region mapping fail closed. Category and theme are not hard filters unless a request explicitly includes them and the product contract defines their meaning.

The current helper is policy plumbing only. It does not declare a set of TourAPI content types as supported, derive a live/closed state from descriptive fields, or treat an AI Hub table as eligible catalog records.

## Analysis protocol and evidence boundary

Use the approved AI Hub Domestic Travel Log 2023 region labels and role bindings only: capital TL/VL, west TL/VL, east TL/VL, and jeju-islands TL/VL. TL is historical proxy construction; VL is validation. These broad AI Hub region labels and TL/VL bindings are not a TourAPI `areaCode` crosswalk; no reviewed repository source maps them, so do not infer or assume one. The POI endpoint evidence is one successful one-result `areaBasedList2` request (HTTP 200 / API `0000`) after two earlier DNS failures and one stale-sandbox execution block; no pagination or snapshot retrieval occurred. The response shape sample is schema evidence only and does not validate uniqueness, meanings, bulk authorization, or coverage. Evaluate whole trips, reject TL/VL trip overlap, keep `(region, source POI_ID)` namespaced, exclude post-event fields, and report candidate coverage and observed-positive coverage separately. Keep all item identities and rows in memory; share only coarse aggregates with suppression. No missing visit is a negative and no candidate set is described as historical exposure.

Because a verified authoritative catalog snapshot was unavailable, product-catalog candidate size, request-level nonempty rate, matched canonical identity coverage, and out-of-product-candidate positive share are **not measured**. Existing TL-observed candidate proxy results remain a separate reference and must not be relabeled as product coverage.

The approved TL/VL proxy reproduction ran on 2026-10-16 using all four regions, TL-only candidates, VL observed positives, whole-trip units, K=5/10/20, and no sampled negatives. Results are in the Git-ignored `results/experiments/candidate-choice-feasibility/issue4-tl-proxy-reference-20261016/` directory. `TRAVEL_ID` overlap was `0` in every region. In each region, candidate count was `10+`, trip candidate coverage was `90–100%`, and candidate size per trip was `500+`. Positive event coverage was `25–<50%` in capital and `50–<75%` in west/east/jeju-islands; cold-start positive event share was `50–<75%` in capital and `25–<50%` in the other three regions. These are historical TL-catalog proxy results, not evidence of a product catalog, exposure, negative labels, or TourAPI identity.

## Facts, inference, and unresolved decisions

### Facts

- The AI Hub 2023 data dictionary lists `TN_POI_MASTER` as a POI information table and separately lists `TN_VISIT_AREA_INFO` as visit records with an optional `POI_ID` field.
- The data dictionary does not state that the visit-table `POI_ID` is a foreign key to the master or guaranteed to contain identical identifiers.
- The earlier approved context-POI analysis reports a region-scoped exact-string candidate join between visits and the historical master in `50–<75%` bands for capital, west, and east and `75–<90%` for jeju-islands, across TL and VL. Issue #4 did not re-read that separate table, and the earlier join was explicitly diagnostic rather than canonical identity evidence.
- The [official data.go.kr listing](https://www.data.go.kr/data/15101578/openapi.do) identifies the KorService2 API family, GET `areaBasedList2` as regional tourism information, model `areaBasedList2_response`, REST JSON/XML, free/unrestricted reuse metadata, development auto approval, operational review approval, and development quota 1,000. The rendered schema does not expose endpoint field names/types.
- The [official Korean Tourism Organization portal FAQ](https://api.visitkorea.or.kr/?loginFlag=sso) describes the OpenAPI guide's request/response examples as planning and debugging aids and warns against unauthorized caching/crawling. These sources do not settle retained or bulk catalog snapshot permissions.
- `areaBasedList2` chronology: two earlier one-result probes failed at DNS; a later ordinary run was blocked by the stale sandbox before execution; after the exact host was added to the existing `herdr-data-science` profile and guarded startup restarted it, one one-result request returned HTTP 200 / API `0000`. The envelope was an object. The sample row was discarded after inspecting only field names/types; all were strings: `addr1`, `addr2`, `areacode`, `cat1`, `cat2`, `cat3`, `contentid`, `contenttypeid`, `cpyrhtDivCd`, `createdtime`, `firstimage`, `firstimage2`, `lDongRegnCd`, `lDongSignguCd`, `lclsSystm1`, `lclsSystm2`, `lclsSystm3`, `mapx`, `mapy`, `mlevel`, `modifiedtime`, `sigungucode`, `tel`, `title`, `zipcode`. No row values were retained. This does not prove uniqueness, complete semantics, authorization beyond this endpoint, bulk terms, or product coverage.
- Issue #4 and the AI Hub workflow approve region labels and TL/VL bindings for capital, west, east, and jeju-islands. Candidate-feasibility documentation uses TL for historical proxy construction and VL for validation. No reviewed repository source maps those broad region labels to TourAPI `areaCode` values; the TL/VL bindings are not such a crosswalk.
- Two earlier user-authorized, unfiltered, one-result `areaBasedList2` GET probes using the unchanged key failed at DNS before HTTP connection. A later ordinary run was blocked by a stale sandbox before execution. After the exact host was added to the existing `herdr-data-science` profile and guarded startup restarted that profile, one one-result request succeeded with HTTP 200 / API `0000`. The envelope was an object; all observed sample-row fields were strings, as listed above. The row was discarded without retaining values. No additional request or catalog retrieval followed.
- Three user-authorized, one-result, read-only GETs reached only the official `areaCode2` endpoint on `apis.data.go.kr`. A boolean check confirmed the environment string was already a canonical percent-encoded representation; its value was not disclosed. The first request manually applied `urllib.parse.urlencode(params)` to a params dictionary containing that string as `serviceKey`; the second passed the same string via the HTTP client's `requests` `params` argument. Both applied another encoding pass and returned HTTP 403 / API code `UNAVAILABLE`. The third inserted the unchanged environment string as the `serviceKey` query value without another encoding pass and returned HTTP 200, `resultCode=0000`, `resultMsg=OK`. This verifies successful authorization/response only for this `areaCode2` request. Only status/result fields and, for `areaBasedList2`, field names/types were inspected in memory; no catalog rows or values were retained. The credential value is not included in output, logs, or artifacts. The single POI endpoint response does not establish complete field semantics, authorization beyond that endpoint, uniqueness, or product-catalog coverage; no catalog snapshot exists.

### Inference

- TourAPI is a promising candidate catalog source because its official product offers current tourism metadata and region/type/category endpoints. Public metadata does not establish that its full contents match the product's intended POI domain.
- Provider item IDs and observed AI Hub IDs may be linkable for some records, but field-name similarity or a string join alone does not prove canonical identity.
- Ranking metrics require a fixed, versioned candidate contract; metrics from the TL-observed proxy are not directly comparable with any future product-catalog candidate metrics.

### Unresolved

- Map each approved AI Hub region label to an appropriate TourAPI `areaCode` using a reviewed source; no mapping is currently established.
- Review the current official guide for complete `areaBasedList2` field meanings, attribution obligations, and pagination behavior. The one-row sample gives names/types only, not semantics or completeness.
- Establish applicable terms and approval for retaining, caching, or bulk snapshotting a catalog; free/unrestricted metadata and the OpenAPI guide do not settle this use. This remains unresolved; no catalog pages or snapshot were retained, and no further POI calls should occur until resolved.
- Pin and review the current official API guide, response-field definitions, code lists, coordinate semantics, content-type eligibility, update/deletion behavior, rate limits, pagination behavior, and attribution obligations.
- Decide which types are product-recommendable; define active/inactive status and the district mapping; define canonical-key uniqueness and snapshot refresh policy.
- Load the separately role-bound AI Hub `TN_POI_MASTER` reference only after its approved source provenance/role is established, then report it as a historical reference diagnostic, never an FK assumption. The current preflight did not establish an unambiguous approved source/role, so this table was not opened and no Issue #4 identity diagnostic was run.
- Product candidate/identity coverage remains incomplete and unmeasured. Build or acquire an authorized, verified catalog snapshot and run four-region identity and candidate coverage diagnostics before the follow-up ranking experiment; current API access cannot establish 2023 availability.

## Synthetic validation and use

Run `python3 -m unittest discover -s tests -p 'test_poi_catalog_candidate_contract.py' -v`. Tests cover deterministic exact-signal matching, ambiguity, conflict handling, diagnostic-only fuzzy/coordinate signals, fail-closed eligibility, privacy-bucketed summaries, and the five domain-review smoke cases. The contract helper does not issue TourAPI requests. Its candidate eligibility function must not receive observed category or post-event feedback.

Follow-up context-aware ranking work must use a versioned product catalog and this candidate contract, keep observed positives and unknowns distinct, and compare ranking metrics only within the same candidate definition.
