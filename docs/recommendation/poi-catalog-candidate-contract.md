# POI catalog and candidate eligibility contract

## Status

**상태: 구현 및 privacy-safe 실제 데이터 실험 완료. 결론: 수정 후 재측정.** Issue #66 승인 계약 v1을 구현했다. 기준 카탈로그는 TourAPI KorService2 v4.4, provider identity는 `(tourapi-korservice2, contentid)`, 추천 지원 type은 `{12,14,28}`이다. 버전 정책은 [`config/recommendation/poi-catalog-policy-v1.json`](../../config/recommendation/poi-catalog-policy-v1.json)에 고정했다. 상세 산출물은 Git-ignored `results/`에 두고, 공유 문서에는 privacy-safe 집계만 기록한다.

AI Hub 네 권역의 공식 metadata는 각 권역을 구성하는 시도 목록을 제공하지 않는다. 사용자가 승인한 공식 광역권 분류를 적용해 deterministic crosswalk를 만들었다. 수도권=서울·인천·경기, 서부=충청권+호남권, 동부=동남권+대경권+강원권, 제주및도서권=제주권이다. 2026년 현행 법정동 상위 시도 코드 16개를 전부 고정 매핑했다. 2026년 전남광주 통합특별시는 `12`, 강원특별자치도는 `51`, 전북특별자치도는 `52`이며, TourAPI가 반환한 세종 코드 `36110`은 공식 법정동 자료와 행정안전부 공지에 따라 충청권에 명시적으로 배정했다. 일괄 prefix 변환은 하지 않는다. AI Hub metadata가 비제주 도서의 소속을 열거하지 않으므로 `jeju-islands`는 공식 제주권 코드 `50`에 매핑하며 다른 도서까지 포함한다고 주장하지 않는다.

## 의미와 평가 경계

`TN_VISIT_AREA_INFO` 관측은 positive observation이다. 방문하지 않은 POI는 unknown/unlabeled이며 negative가 아니다. AI Hub에는 과거 노출 기록이 없으므로 현재 후보군은 요청 시점 정책상 추천 가능했던 가상의 집합이지 과거에 보였거나 선택 가능했던 집합이 아니다.

`SourcePoi.region`은 historical observation/실험 코호트 문맥이고, `CandidateRequest.region`은 독립된 request/experiment 문맥이다. 제품 후보 지표는 `HistoricalRequestProxy`를 입력으로 받지 않는다. 방문 후 만족도, 재방문의향, 추천의향, 방문지의 사후 카테고리·위치 정보를 eligibility에 넣지 않는다.

## TourAPI v4.4 snapshot 계약

어댑터에서 쓰는 API 필드는 다음과 같다. content ID는 문자열로 보존하고 선행 0을 제거하지 않는다.

| API 필드 | v1 의미 |
| --- | --- |
| `contentid` | provider canonical identity component |
| `contenttypeid` | 추천 지원 type `{12 관광지, 14 문화시설, 28 레포츠}`. `{15 행사/공연/축제, 25 여행코스, 32 숙박, 38 쇼핑, 39 음식점}` 제외 |
| `title`, `addr1` | 로컬 identity 증거. 원문을 외부 진단에 내보내지 않음 |
| `lDongRegnCd`, `lDongSignguCd` | 광역/시군구 법정동 코드 |
| `lclsSystm1`, `lclsSystm2`, `lclsSystm3` | taxonomy 관측값. identity가 아니며 암묵적 필터도 아님 |
| `modifiedtime` | 변경 시각 관측. active/inactive 상태로 해석하지 않음 |

고정 snapshot 수집 시 retrieval time, API manual version, endpoint, request/pagination config와 hash, policy version, content hash를 기록한다. API key는 환경 변수에서 프로세스 메모리로만 읽고 URL/error/log/artifact에 기록하지 않는다. snapshot raw payload는 Git-ignored `results/` 아래에만 저장한다.

공식 참고: [TourAPI KorService2 listing](https://www.data.go.kr/data/15101578/openapi.do), [행정표준코드관리시스템 법정동 코드](https://www.code.go.kr/stdcode/regCodeL.do), [국토교통부 전국 법정동 2026-06-30 자료](https://www.data.go.kr/data/15063424/fileData.do?recommendDataYn=Y), [행정안전부 2026 전남광주 통합특별시 코드 변경](https://www.mois.go.kr/frt/bbs/type001/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000052&nttId=127039), [행정안전부 세종 법정동 코드 공지](https://www.mois.go.kr/frt/bbs/type001/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000052&nttId=127979), [AI Hub 2023 국내 여행로그](https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71778), [NABO 2025 권역별 GRDP 분류](https://korea.nabo.go.kr/board/file/down.do?fid=33318639). KorService2 공식 v4.4 manual의 `ldongCode2`는 `lDongListYn=Y`에서 전체 법정동 목록을 돌려주며 `totalCount/pageNo` 기준 페이지 처리가 필요하다. data.go.kr listing은 실시간 제공과 개발계정 1,000회 quota를 표시한다. 이용 가능성만으로 장기 대량 보관 권한이나 2023년 당시 카탈로그 상태를 추론하지 않는다.

## Identity 계약

AI Hub source key는 `(region, nonblank POI_ID)`, provider key는 `(tourapi-korservice2, contentid)`로 분리한다. 문자열 매칭은 실험상의 진단 결과이며 원천 FK 관계를 증명하지 않는다. identity matching은 명시된 권역 매핑 안에서 exact normalized name + exact address 또는 exact reviewed district 신호가 유일하고 다른 exact signal과 모순이 없을 때만 `MATCHED`다. 이름 단독 및 fuzzy 유사도는 `AMBIGUOUS` 진단에만 쓴다. 여러 동률 후보, 충돌, taxonomy veto는 확정하지 않는다. 좌표/거리 matching은 AI Hub와 TourAPI 좌표계 및 encoding 동일성이 검증될 때까지 비활성이다.

## Eligibility와 지역 crosswalk

`eligibility_reason`은 고정 snapshot의 membership, 필수 필드 유효성, 지원 type, versioned region policy, 그리고 request에 명시된 경우의 district filter만 적용한다. provider가 보장하지 않는 active/inactive status는 만들지 않는다. AI Hub 네 region과 현행 16개 법정동 지역코드 전체 대응은 정책 JSON을 단일 source of truth로 쓴다.

| AI Hub/ProductRegion | 공식 광역권 | `lDongRegnCd` |
| --- | --- | --- |
| `capital` | 수도권 | `11, 28, 41` |
| `west` | 충청권 + 호남권 | `12, 30, 43, 44, 52, 36110` |
| `east` | 동남권 + 대경권 + 강원권 | `26, 27, 31, 47, 48, 51` |
| `jeju-islands` | 제주권 | `50` |

## 구현 및 재현

`scripts/recommendation/tourapi_snapshot_adapter.py` maps KorService2 v4.4 fields, reads mapped local CSV, and provides a sequential read-only API collector. `scripts/recommendation/collect_tourapi_v44_snapshot.py` writes snapshot and metadata under ignored `results/`. The actual-data harness reads only approved AI Hub 2023 TL/VL inputs, keeps identities/rows in memory, rejects TL/VL trip overlap, and emits privacy-suppressed aggregates. Shared reporting must include snapshot size/type distribution, ProductRegion candidate size, TL/VL identity status and method, nonempty request rate and candidate size distribution, observed-positive coverage, outside-candidate/catalog-outside/cold-start shares, and comparison to the #60 TL-observed proxy. Any negative result is reported with a proceed/modify/retire conclusion.

### POI Master descriptive link diagnostic

At source revision `4e82615`, a dedicated user-authorized data-science run treated the four bounded regional Other candidates as approved inputs. The user has now explicitly confirmed those four candidates are the approved files. All four candidates and all eight region/split visit inputs passed the documented layout and header checks. Filekey/release metadata was not independently inspected; source approval for this diagnostic rests on the user's explicit confirmation.

The run read CSV in PyArrow batches and selected only `POI_ID` and `POI_NM`. Nonblank `POI_ID` strings were compared exactly; trimming was used only to identify blank IDs. Fallback matching ran only for blank or unmatched visit IDs and used exact equality on nonempty `POI_NM` text because no documented normalization rule was found.

In every region/split cell, privacy buckets were: master blank IDs `0`; duplicate master ID groups `0`; visit blank IDs `10+`; exact ID matches `10+`; nonblank visit IDs missing from the master `10+`; fallback records `10+`; and fallback records with zero, one, or multiple matching master rows `10+` in each bucket. These are coarse descriptive counts, not identity certification.

This establishes descriptive within-region link evidence only. It does not establish a declared foreign key or canonical identity, and metadata conflict comparison was not performed. No cross-region identity, exposure, or negative-label conclusion follows. `TN_POI_MASTER` remains a historical Other reference, not an authoritative serving catalog.

The historical `TN_POI_MASTER` link diagnostic above is not a serving-catalog identity result. The v1 TourAPI snapshot experiment is recorded separately below; it must not be conflated with the historical TL-observed candidate proxy.

The approved TL/VL proxy reproduction ran on 2026-10-16 using all four regions, TL-only candidates, VL observed positives, whole-trip units, K=5/10/20, and no sampled negatives. Results are in the Git-ignored `results/experiments/candidate-choice-feasibility/issue4-tl-proxy-reference-20261016/` directory. `TRAVEL_ID` overlap was `0` in every region. In each region, candidate count was `10+`, trip candidate coverage was `90–100%`, and candidate size per trip was `500+`. Positive event coverage was `25–<50%` in capital and `50–<75%` in west/east/jeju-islands; cold-start positive event share was `50–<75%` in capital and `25–<50%` in the other three regions. These are historical TL-catalog proxy results, not evidence of a product catalog, exposure, negative labels, or TourAPI identity.

## Facts, inference, and unresolved decisions

### Facts

- The AI Hub 2023 data dictionary lists `TN_POI_MASTER` as a POI information table and separately lists `TN_VISIT_AREA_INFO` as visit records with an optional `POI_ID` field.
- The data dictionary does not state that the visit-table `POI_ID` is a foreign key to the master or guaranteed to contain identical identifiers.
- The earlier approved context-POI analysis reports a region-scoped exact-string candidate join between visits and the historical master in `50–<75%` bands for capital, west, and east and `75–<90%` for jeju-islands, across TL and VL. Issue #4 did not re-read that separate table, and the earlier join was explicitly diagnostic rather than canonical identity evidence.
- 초기 one-result GET은 HTTP 200 / API `0000`와 string response type만 확인한 탐색이었다. 이후 v4.4 전체 법정동 코드 집합을 요청하는 고정 snapshot 수집을 수행했고 실제 후보 규모/커버리지는 아래에 별도 기록했다. 수집 성공은 장기 payload 보관 권한, provider identity의 의미, 2023년 당시 제공 여부를 증명하지 않는다.
- Issue #66 approves the v1 contract. The AI Hub region labels and TL/VL bindings are used as source cohorts; the product crosswalk is separately versioned in `config/recommendation/poi-catalog-policy-v1.json`.
- Bounded discovery found four `TN_POI_MASTER` candidates, one per explicit region Other-role binding. Repository documentation classifies the table as Other; the bindings and region/year role markers support the Other role and region/year. Current AI Hub usage terms support local read-only AI development with attribution and restrictions. The user explicitly confirmed these four candidates are the approved files for this diagnostic. A dedicated diagnostic read selected columns and the eight bound visit inputs after layout/header checks. The resulting link counts are descriptive within-region evidence only, not a declared foreign key or canonical identity; metadata conflicts were not compared.

#### Official source verification

- The [official data.go.kr listing](https://www.data.go.kr/data/15101578/openapi.do) identifies KorService2, `areaBasedList2`, its response model and formats, free/unrestricted reuse metadata, development auto approval, operational review, and quota 1,000. Its rendered schema does not expose endpoint field names/types.
- The v4.4 manual documents `ldongCode2` full-list mode and paginated totals; the adapter requests the complete legal-dong set and deduplicates its province codes. The product crosswalk and type policy are fixed by the approved v1 contract, not inferred from API code lists.
- AI Hub 2023 metadata defines the four region labels but not their province membership. User-approved official seven-region classification supplies the complete deterministic v1 crosswalk; non-Jeju island coverage is not asserted.
- The [official Korean Tourism Organization FAQ](https://api.visitkorea.or.kr/?loginFlag=sso) discusses guide-preview usage. The user authorized one read-only API snapshot run. That authorization does not settle long-term payload retention terms; keep detailed payloads local and ignored.

### Inference

- TourAPI is a promising candidate catalog source because its official product offers current tourism metadata and region/type/category endpoints. Public metadata does not establish that its full contents match the product's intended POI domain.
- Provider item IDs and observed AI Hub IDs may be linkable for some records, but field-name similarity or a string join alone does not prove canonical identity.
- Ranking metrics require a fixed, versioned candidate contract; metrics from the TL-observed proxy are not directly comparable with any future product-catalog candidate metrics.

### Remaining limitations

- Current TourAPI membership does not establish historical 2023 availability, open/bookable status, exposure, or user consideration.
- The legal meaning of long-term bulk payload retention is not expanded beyond the official listing; retain the collected snapshot only in the approved ignored local results area.
- Identity match rates depend on the v1 exact-field rule and are not proof of a provider-declared foreign key. Coordinate matching remains disabled.
- 실험에서 모든 권역·TL/VL의 후보 요청 non-empty 비율은 90–100%, 요청당 후보 크기는 500+였다. 반면 VL observed positive의 90–100%는 identity 미해결이고, 확정 positive 후보 coverage 하한은 권역별 <10% 구간 또는 privacy suppression이다. 미해결 positive를 카탈로그 밖으로 간주하지 않았으므로 실제 catalog-outside share는 추정할 수 없다. 이에 따라 v1 후보 생성기는 수정 후 재측정 대상으로 판단한다.

## Issue #4 실제 데이터 실험 (2026-10-18)

TourAPI KorService2 v4.4의 `areaBasedList2` read-only 수집 snapshot과 승인된 AI Hub 2023 네 권역 TL/VL 원본을 사용했다. 원본은 read-only로 처리했고, 상세 산출물은 Git-ignored `results/experiments/poi-catalog-v1/actual-data-20261018-final4/`에 저장했다. 공유 결과에는 raw row/ID/좌표/자유 텍스트/경로/secret을 포함하지 않는다.

- 고정 snapshot: `tourapi-korservice2-v4.4-20261017T164137+0000-37426ba2`; retrieval time `2026-10-17T16:41:37+00:00`; snapshot SHA-256 `37426ba26078ad309738688af2a2bf15291f1e911c99596edfe7ecccb5fa48b8`.
- 요청 설정 SHA-256 `036c28a846ab49a7e9e1081cca9e62d558cd98048b0d3ba41547c52bdf29a9f4`; policy SHA-256 `e8b0337f04613c353289dfa2ecf0706673b7a52209866da29bb3b7076032d8f3`; 실험 설정 SHA-256 `e2af746541e1cd762abed8abd68fa0623e3c8d0b4660e021af451c13f46c2e20`; CLI/source loader SHA-256 `7138ada3079e7f5d99bcbe10b39fb1815093a818713c205ea5079783838a204f` / `84a9dbe268efbf7237c258c8547a304b1f2eb1882881a1e429092270cce6ae9a`.
- snapshot item 48,583개. content type별 수: 12=12,554; 14=2,768; 15=889; 25=52; 28=3,737; 32=2,909; 38=12,271; 39=13,403.
- 지역별 eligible candidates: capital 5,044; west 6,000; east 7,224; jeju-islands 791.
- 각 권역 TL/VL에서 identity status MATCHED/AMBIGUOUS/UNMATCHED를 따로 집계했다. 매칭 신호는 exact normalized name+address뿐이며, district crosswalk 미검증과 좌표계 미검증으로 district/좌표 신호는 비활성이다. fuzzy name은 진단 전용이다. 네 권역 모두 각 split에서 AMBIGUOUS와 UNMATCHED가 각각 10+였다. MATCHED는 capital TL/VL 및 west VL에서 <10으로 억제되었고, 나머지 셀은 10+였다. 충돌 신호는 확정 매칭을 억제했다.
- 모든 권역 TL/VL의 virtual request non-empty 비율은 90–100%, 후보 size는 500+였다. VL observed-positive 중 90–100%는 identity unresolved다. 확인된 positive candidate coverage 하한은 전 권역 <10% 구간 또는 privacy suppression, unresolved를 포함한 상한은 90–100%다. 이는 identity 불확실성 때문에 상한이 넓으며 높은 실제 coverage의 증거가 아니다.
- identity가 확인된 positive 중 outside-candidate share는 0–<10% 구간 또는 privacy-suppressed였다. identity unresolved가 많아 catalog-outside share는 추정 불가다. cold-start share는 매칭 가능한 positive에 한해 집계되어 대부분 <10%/suppressed이며 jeju-islands는 10–<25%다.
- 별도로 재현한 #60 TL-observed proxy는 네 권역 모두 TL/VL trip ID overlap 0, VL trip candidate coverage 90–100%, trip당 후보 500+였다. VL positive event coverage는 capital 25–<50%, 나머지 권역 50–<75%; cold-start positive event share는 capital 50–<75%, 나머지 권역 25–<50%였다. 이는 과거 관측 proxy 기준이며 TourAPI 제품 후보 지표와 직접 비교할 수 없다.
- **결론: 수정 후 재측정.** snapshot 기반 후보 생성·eligibility는 동작하지만 현재 필드만으로는 observed-positive identity coverage를 지지하기 어렵다. 다음 단계는 권위 있는 AI Hub/TourAPI ID crosswalk 또는 추가 검증된 identity 신호 확보이며, 그 전까지 ranker 평가 및 catalog-outside 결론은 보류한다. unvisited POI는 unknown/unlabeled로 유지한다.

재현은 같은 승인된 입력 환경에서 실행한다. 입력 경로나 자격 증명은 명령행·로그·공유 문서에 기록하지 않는다.

```bash
python3 -m scripts.recommendation.collect_tourapi_v44_snapshot \
  --output results/experiments/poi-catalog-v1/tourapi-korservice2-v44-items.csv
python3 -m scripts.recommendation.analyze_poi_catalog_candidate_coverage \
  --raw-root "$RAW_ROOT" --snapshot "$TOURAPI_SNAPSHOT" \
  --output results/experiments/poi-catalog-v1/actual-data-20261018-final4 \
  --run-id issue4-actual-20261018-final4 \
  --confirm-approved --confirm-terms --confirm-poi-candidate
```

실험 metadata는 run ID, input role binding, code/config fingerprints, retrieval/request/policy/snapshot version 및 hash를 Git-ignored 산출물에 기록한다.

## Synthetic validation and use

Run `python3 -m unittest discover -s tests -p 'test_poi_catalog_candidate_contract.py' -v`, plus the TourAPI snapshot adapter and experiment-design audit test modules. Tests cover deterministic exact-signal matching, ambiguity, conflict handling, coordinate exclusion, fail-closed eligibility, normalized code handling, independent request-region coverage, proxy rejection from product coverage, explicit CSV field maps, and domain-review checks. The adapter also includes a credential-safe read-only collector; the collection CLI persists only under ignored `results/`. `derive_proxy_requests_from_observations` returns a distinct `HistoricalRequestProxy` for historical-feasibility analysis only, requires one explicit region per request, and does not infer district selection. Product candidate coverage uses independently supplied `CandidateRequest` contexts. The candidate eligibility function must not receive observed category or post-event feedback.

Follow-up context-aware ranking work must use a versioned product catalog and this candidate contract, keep observed positives and unknowns distinct, and compare ranking metrics only within the same candidate definition.
