# POI catalog and candidate eligibility contract

## Status

**Outcome: incomplete, with a deterministic implementation contract ready for an authorized, verified catalog snapshot.** A one-result GET to the official TourAPI `areaBasedList2` endpoint in a fresh guarded session, using the approved raw environment key, returned HTTP 200 / API code `0000`. Inspected sample response fields were strings; no field values, key, or key-bearing URL were retained. This evidence is limited to that sampled request: it does not establish catalog coverage, complete field semantics, authorization beyond the sample, or retention rights. No catalog snapshot or product-candidate coverage was produced.

No reviewed repository source maps the approved broad AI Hub region labels to TourAPI `areaCode` values. The approved TL/VL role bindings are not an area-code crosswalk. No verified mapping or product-candidate coverage is available, and this current response cannot establish 2023 availability.

The current product authoritative catalog, includable content types, refresh schedule, status semantics, and serving SLA remain unresolved. `TN_POI_MASTER` is a separate historical AI Hub reference table classified by repository documentation as Other, not the serving catalog. Bounded discovery found four candidates, one for each explicit region Other-role binding. The bindings and region/year role markers support the Other role and region/year; current AI Hub usage terms support local read-only AI development with attribution and restrictions. The exact candidate-to-approved filekey/release snapshot association was not independently revalidated. The completed diagnostic proceeded under the user's instruction to treat those exact candidates as approved. `TN_VISIT_AREA_INFO.POI_ID` is an observed field candidate; neither its foreign-key relationship nor value identity with the master is established by the reviewed data dictionary. Any string-level join is diagnostic only.

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

The [official data.go.kr KorService2 listing](https://www.data.go.kr/data/15101578/openapi.do) identifies the KorService2 family and GET `areaBasedList2` for regional tourism information, with response model `areaBasedList2_response` and REST JSON/XML formats. It lists free use, unrestricted reuse metadata, automatic development approval, operational review approval, and a development quota of 1,000. The [official Korean Tourism Organization portal](https://api.visitkorea.or.kr/?loginFlag=sso) FAQ says its OpenAPI guide requests/responses are for service planning and request/response debugging, and warns against unauthorized caching or crawling. These current official sources do not settle whether this product may retain or bulk snapshot the catalog; this remains unresolved. In the successful one-result `areaBasedList2` response, inspected sample response fields were strings. This does not establish complete field meanings, unique identifiers, authorization beyond the sampled request, or retention permission. Before adapter approval, review the current official field definitions for provider ID/type ID, title, administrative codes, address, coordinate encoding/CRS, category taxonomy, update/deletion semantics, attribution, pagination, and endpoint-specific availability. Neither current metadata nor this response establishes catalog availability in 2023, that returned records are open or bookable, or that they suit every product request.

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

Use the approved AI Hub Domestic Travel Log 2023 region labels and role bindings only: capital TL/VL, west TL/VL, east TL/VL, and jeju-islands TL/VL. TL is historical proxy construction; VL is validation. These broad AI Hub region labels and TL/VL bindings are not a TourAPI `areaCode` crosswalk; no reviewed repository source maps them, so do not infer or assume one. The POI endpoint evidence is one successful one-result `areaBasedList2` request (HTTP 200 / API `0000`) in a fresh guarded session using the approved raw environment key; inspected sample response fields were strings. This sample does not validate uniqueness, full field semantics, authorization beyond the sampled request, bulk retention rights, or coverage. Evaluate whole trips, reject TL/VL trip overlap, keep `(region, source POI_ID)` namespaced, exclude post-event fields, and report candidate coverage and observed-positive coverage separately. Keep all item identities and rows in memory; share only coarse aggregates with suppression. No missing visit is a negative and no candidate set is described as historical exposure.

### POI Master descriptive link diagnostic

At source revision `4e82615`, a dedicated user-authorized data-science run treated the four bounded regional Other candidates as approved inputs. All four candidates and all eight region/split visit inputs passed the documented layout and header checks. This was an explicit user-approval assumption; the exact candidate-to-approved filekey/release snapshot association was not independently revalidated.

The run read CSV in PyArrow batches and selected only `POI_ID` and `POI_NM`. Nonblank `POI_ID` strings were compared exactly; trimming was used only to identify blank IDs. Fallback matching ran only for blank or unmatched visit IDs and used exact equality on nonempty `POI_NM` text because no documented normalization rule was found.

In every region/split cell, privacy buckets were: master blank IDs `0`; duplicate master ID groups `0`; visit blank IDs `10+`; exact ID matches `10+`; nonblank visit IDs missing from the master `10+`; fallback records `10+`; and fallback records with zero, one, or multiple matching master rows `10+` in each bucket. These are coarse descriptive counts, not identity certification.

This establishes descriptive within-region link evidence only. It does not establish a declared foreign key or canonical identity, and metadata conflict comparison was not performed. No cross-region identity, exposure, or negative-label conclusion follows. `TN_POI_MASTER` remains a historical Other reference, not an authoritative serving catalog.

Because a verified authoritative catalog snapshot was unavailable, product-catalog candidate size, request-level nonempty rate, matched canonical identity coverage, and out-of-product-candidate positive share are **not measured**. Existing TL-observed candidate proxy results remain a separate reference and must not be relabeled as product coverage.

The approved TL/VL proxy reproduction ran on 2026-10-16 using all four regions, TL-only candidates, VL observed positives, whole-trip units, K=5/10/20, and no sampled negatives. Results are in the Git-ignored `results/experiments/candidate-choice-feasibility/issue4-tl-proxy-reference-20261016/` directory. `TRAVEL_ID` overlap was `0` in every region. In each region, candidate count was `10+`, trip candidate coverage was `90–100%`, and candidate size per trip was `500+`. Positive event coverage was `25–<50%` in capital and `50–<75%` in west/east/jeju-islands; cold-start positive event share was `50–<75%` in capital and `25–<50%` in the other three regions. These are historical TL-catalog proxy results, not evidence of a product catalog, exposure, negative labels, or TourAPI identity.

## Facts, inference, and unresolved decisions

### Facts

- The AI Hub 2023 data dictionary lists `TN_POI_MASTER` as a POI information table and separately lists `TN_VISIT_AREA_INFO` as visit records with an optional `POI_ID` field.
- The data dictionary does not state that the visit-table `POI_ID` is a foreign key to the master or guaranteed to contain identical identifiers.
- The earlier approved context-POI analysis reports a region-scoped exact-string candidate join between visits and the historical master in `50–<75%` bands for capital, west, and east and `75–<90%` for jeju-islands, across TL and VL. Issue #4 did not re-read that separate table, and the earlier join was explicitly diagnostic rather than canonical identity evidence.
- The [official data.go.kr listing](https://www.data.go.kr/data/15101578/openapi.do) identifies the KorService2 API family, GET `areaBasedList2` as regional tourism information, model `areaBasedList2_response`, REST JSON/XML, free/unrestricted reuse metadata, development auto approval, operational review approval, and development quota 1,000. The rendered schema does not expose endpoint field names/types.
- The [official Korean Tourism Organization portal FAQ](https://api.visitkorea.or.kr/?loginFlag=sso) describes the OpenAPI guide's request/response examples as planning and debugging aids and warns against unauthorized caching/crawling. These sources do not settle retained or bulk catalog snapshot permissions.
- A one-result GET to the official `areaBasedList2` endpoint in a fresh guarded session, using the approved raw environment key, returned HTTP 200 / API `0000`. Inspected sample response fields were strings. No row values, key, or key-bearing URL were retained. This confirms only the sampled request; complete schema semantics, authorization beyond the sample, catalog retention rights, uniqueness, 2023 availability, and product coverage remain unverified.
- Issue #4 and the AI Hub workflow approve region labels and TL/VL bindings for capital, west, east, and jeju-islands. Candidate-feasibility documentation uses TL for historical proxy construction and VL for validation. No reviewed repository source maps those broad region labels to TourAPI `areaCode` values; the TL/VL bindings are not such a crosswalk.
- Bounded discovery found four `TN_POI_MASTER` candidates, one per explicit region Other-role binding. Repository documentation classifies the table as Other; the bindings and region/year role markers support the Other role and region/year. Current AI Hub usage terms support local read-only AI development with attribution and restrictions. Under the user's instruction to treat those exact candidates as approved, a dedicated diagnostic read selected columns and the eight bound visit inputs after layout/header checks. The exact candidate-to-approved filekey/release snapshot association was not independently revalidated. The resulting link counts are descriptive within-region evidence only, not a declared foreign key or canonical identity; metadata conflicts were not compared.

### Inference

- TourAPI is a promising candidate catalog source because its official product offers current tourism metadata and region/type/category endpoints. Public metadata does not establish that its full contents match the product's intended POI domain.
- Provider item IDs and observed AI Hub IDs may be linkable for some records, but field-name similarity or a string join alone does not prove canonical identity.
- Ranking metrics require a fixed, versioned candidate contract; metrics from the TL-observed proxy are not directly comparable with any future product-catalog candidate metrics.

### Unresolved

- Map each approved AI Hub region label to an appropriate TourAPI `areaCode` using a reviewed source; no mapping is currently established.
- Review the current official guide for complete `areaBasedList2` field meanings, attribution obligations, and pagination behavior. The one-row sample gives names/types only, not semantics or completeness.
- Establish applicable terms and approval for retaining, caching, or bulk snapshotting a catalog; free/unrestricted metadata and the OpenAPI guide do not settle this use. This remains unresolved; no catalog pages or snapshot were retained.
- Pin and review the current official API guide, response-field definitions, code lists, coordinate semantics, content-type eligibility, update/deletion behavior, rate limits, pagination behavior, and attribution obligations.
- Decide which types are product-recommendable; define active/inactive status and the district mapping; define canonical-key uniqueness and snapshot refresh policy.
- The exact candidate-to-approved filekey/release snapshot association was not independently revalidated; the diagnostic used the four candidates under the user's explicit approval assumption. Keep `TN_POI_MASTER` as a separate historical Other reference, never an assumed FK target. Candidate identity remains uncanonicalized and metadata conflicts were not compared.
- Product candidate/identity coverage remains incomplete and unmeasured. Build or acquire an authorized, verified catalog snapshot and run four-region identity and candidate coverage diagnostics before the follow-up ranking experiment; current API access cannot establish 2023 availability.

## Synthetic validation and use

Run `python3 -m unittest discover -s tests -p 'test_poi_catalog_candidate_contract.py' -v`. Tests cover deterministic exact-signal matching, ambiguity, conflict handling, diagnostic-only fuzzy/coordinate signals, fail-closed eligibility, privacy-bucketed summaries, and the five domain-review smoke cases. The contract helper does not issue TourAPI requests. Its candidate eligibility function must not receive observed category or post-event feedback.

Follow-up context-aware ranking work must use a versioned product catalog and this candidate contract, keep observed positives and unknowns distinct, and compare ranking metrics only within the same candidate definition.
