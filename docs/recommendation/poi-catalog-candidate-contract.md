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

`scripts/recommendation/tourapi_snapshot_adapter.py` maps KorService2 v4.4 fields, reads mapped local CSV, and provides a sequential read-only API collector. `scripts/recommendation/collect_tourapi_v44_snapshot.py` writes snapshot and metadata under ignored `results/`. The actual-data harness reads only approved AI Hub 2023 TL/VL inputs, keeps identities/rows in memory, rejects TL/VL trip overlap, and emits exact non-identifying counts/rates when Issue #4 runs with `--exact-aggregates`; other analyses retain the existing privacy-banded default. Shared reporting must include snapshot size/type distribution, ProductRegion candidate size, TL/VL identity status and method, nonempty request rate and candidate size distribution, observed-positive coverage, outside-candidate/catalog-outside/cold-start shares, and comparison to the #60 TL-observed proxy. Any negative result is reported with a proceed/modify/retire conclusion.

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
- exact aggregate 재실행에서 모든 권역·TL/VL의 후보 요청은 100% non-empty였지만, observed-positive identity resolution은 TL 2,688/87,010 (3.09%), VL 312/10,630 (2.94%)였다. End-to-end coverage는 각각 1,367/87,010 (1.57%), 163/10,630 (1.53%)다. unresolved는 catalog-outside와 다르므로 카탈로그 부재는 판정하지 않았고, 수정 후 재측정한다. 세 분모와 권역별 값은 아래 exact run 표를 참조한다.

## Issue #4 실제 데이터 실험: 정확 집계 재실행 (2026-10-18)

2026-10-18에 고정된 TourAPI KorService2 v4.4 snapshot과 승인된 AI Hub 2023 네 권역 TL/VL 원본을 다시 읽어 `--exact-aggregates`로 재현했다. snapshot 수집은 반복하지 않았고 API 호출도 하지 않았다. 입력 원본은 read-only이며, 상세 집계와 manifest는 Git-ignored `results/experiments/poi-catalog-v1/actual-data-20261018-exact3/`에 저장했다. 아래 수치는 개인·여행·POI ID, raw row, 좌표, 텍스트, 원본 경로를 포함하지 않는 집계다. 작은 집계도 값이 10 미만이라는 이유로 억제하지 않았다.

- run ID: `issue4-actual-20261018-exact3`; aggregation mode: `exact_nonidentifying_aggregates`.
- snapshot: `tourapi-korservice2-v4.4-20261017T164137+0000-37426ba2`; retrieval time `2026-10-17T16:41:37+00:00`; snapshot SHA-256 `37426ba26078ad309738688af2a2bf15291f1e911c99596edfe7ecccb5fa48b8`.
- request config SHA-256 `036c28a846ab49a7e9e1081cca9e62d558cd98048b0d3ba41547c52bdf29a9f4`; policy SHA-256 `e8b0337f04613c353289dfa2ecf0706673b7a52209866da29bb3b7076032d8f3`; experiment config SHA-256 `fefbdff8dc36b11025e270ad9a723425c06474abc3a035449918ed60bc4651ba`.
- 실행 파일 SHA-256: analyzer `cdf318aee151060e4162990fa1d38de2db499f5614ceb74d077f3cdf901c736b`; shared loader `84a9dbe268efbf7237c258c8547a304b1f2eb1882881a1e429092270cce6ae9a`.

### Snapshot과 요청 후보

전체 snapshot은 **48,583개**다. 지원 유형과 제외 유형을 포함한 실제 응답 분포는 다음과 같다.

| `contenttypeid` | 항목 수 |
| --- | ---: |
| 12 | 12,554 |
| 14 | 2,768 |
| 15 | 889 |
| 25 | 52 |
| 28 | 3,737 |
| 32 | 2,909 |
| 38 | 12,271 |
| 39 | 13,403 |

| ProductRegion | eligible candidates | TL non-empty / requests | VL non-empty / requests | 후보 수 min / median / mean / max |
| --- | ---: | ---: | ---: | ---: |
| capital | 5,044 | 2,560/2,560 (100.00%) | 320/320 (100.00%) | 5,044 / 5,044 / 5,044 / 5,044 |
| west | 6,000 | 2,560/2,560 (100.00%) | 320/320 (100.00%) | 6,000 / 6,000 / 6,000 / 6,000 |
| east | 7,224 | 2,560/2,560 (100.00%) | 320/320 (100.00%) | 7,224 / 7,224 / 7,224 / 7,224 |
| jeju-islands | 791 | 2,560/2,560 (100.00%) | 320/320 (100.00%) | 791 / 791 / 791 / 791 |

후보 수 순서는 min / median / mean / max이며, 각 권역의 TL·VL 요청은 같은 고정 ProductRegion 후보 집합을 사용한다. 따라서 해당 권역의 모든 요청에서 후보 크기가 동일하다. TL 요청은 권역마다 2,560개, VL 요청은 320개였고 **8개 권역·split 모두 non-empty 요청률 100%**였다.

### identity 단위와 세 분모

관측 양성은 서로 다른 비어 있지 않은 `(TRAVEL_ID, POI_ID)` 쌍으로 센다. 다음 세 분모를 분리한다.

```text
전체 observed positives
         ↓ identity resolution
identity-resolved positives (MATCHED)
         ↓ 후보 포함 여부
candidate-contained resolved positives
```

- `identity resolution rate = resolved / all observed positives`
- `end-to-end positive candidate coverage = candidate-contained / all observed positives`
- `conditional candidate coverage = candidate-contained / resolved positives`

### Source POI identity별 결과

먼저 `(region, POI_ID)` 고유 source identity를 한 번씩 판정한 결과다. 각 셀은 `count / 고유 source POI_ID 수 (rate)`다.

| 권역 / split | 고유 source POI_ID | MATCHED | AMBIGUOUS | UNMATCHED |
| --- | ---: | ---: | ---: | ---: |
| capital / TL | 8,655 | 1/8,655 (0.01%) | 1,425/8,655 (16.46%) | 7,229/8,655 (83.52%) |
| capital / VL | 1,545 | 1/1,545 (0.06%) | 322/1,545 (20.84%) | 1,222/1,545 (79.09%) |
| west / TL | 9,429 | 15/9,429 (0.16%) | 1,723/9,429 (18.27%) | 7,691/9,429 (81.57%) |
| west / VL | 1,784 | 4/1,784 (0.22%) | 385/1,784 (21.58%) | 1,395/1,784 (78.20%) |
| east / TL | 10,381 | 133/10,381 (1.28%) | 2,185/10,381 (21.05%) | 8,063/10,381 (77.67%) |
| east / VL | 1,938 | 26/1,938 (1.34%) | 430/1,938 (22.19%) | 1,482/1,938 (76.47%) |
| jeju-islands / TL | 13,152 | 343/13,152 (2.61%) | 793/13,152 (6.03%) | 12,016/13,152 (91.36%) |
| jeju-islands / VL | 2,677 | 143/2,677 (5.34%) | 218/2,677 (8.14%) | 2,316/2,677 (86.51%) |

### Observed-positive status와 후보 funnel

각 status/method의 분모는 해당 권역·split 전체 distinct observed-positive 쌍이다. `MATCHED` 수는 identity-resolved positives와 같다. 각 셀은 `count / 전체 observed positives (rate)`다.

| 권역 / split | 전체 observed positives | MATCHED | AMBIGUOUS | UNMATCHED | identity unresolved | candidate-contained | end-to-end coverage | conditional coverage | outside candidate / resolved |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| capital / TL | 13,660 | 3/13,660 (0.02%) | 3,966/13,660 (29.03%) | 9,691/13,660 (70.94%) | 13,657/13,660 (99.98%) | 3/13,660 (0.02%) | 3/13,660 (0.02%) | 3/3 (100.00%) | 0/3 (0.00%) |
| capital / VL | 1,811 | 2/1,811 (0.11%) | 464/1,811 (25.62%) | 1,345/1,811 (74.27%) | 1,809/1,811 (99.89%) | 2/1,811 (0.11%) | 2/1,811 (0.11%) | 2/2 (100.00%) | 0/2 (0.00%) |
| west / TL | 19,584 | 28/19,584 (0.14%) | 6,414/19,584 (32.75%) | 13,142/19,584 (67.11%) | 19,556/19,584 (99.86%) | 16/19,584 (0.08%) | 16/19,584 (0.08%) | 16/28 (57.14%) | 12/28 (42.86%) |
| west / VL | 2,357 | 4/2,357 (0.17%) | 652/2,357 (27.66%) | 1,701/2,357 (72.17%) | 2,353/2,357 (99.83%) | 2/2,357 (0.08%) | 2/2,357 (0.08%) | 2/4 (50.00%) | 2/4 (50.00%) |
| east / TL | 20,456 | 198/20,456 (0.97%) | 8,616/20,456 (42.12%) | 11,642/20,456 (56.91%) | 20,258/20,456 (99.03%) | 72/20,456 (0.35%) | 72/20,456 (0.35%) | 72/198 (36.36%) | 126/198 (63.64%) |
| east / VL | 2,468 | 29/2,468 (1.18%) | 756/2,468 (30.63%) | 1,683/2,468 (68.19%) | 2,439/2,468 (98.82%) | 8/2,468 (0.32%) | 8/2,468 (0.32%) | 8/29 (27.59%) | 21/29 (72.41%) |
| jeju-islands / TL | 33,310 | 2,459/33,310 (7.38%) | 7,698/33,310 (23.11%) | 23,153/33,310 (69.51%) | 30,851/33,310 (92.62%) | 1,276/33,310 (3.83%) | 1,276/33,310 (3.83%) | 1,276/2,459 (51.89%) | 1,183/2,459 (48.11%) |
| jeju-islands / VL | 3,994 | 277/3,994 (6.94%) | 583/3,994 (14.60%) | 3,134/3,994 (78.47%) | 3,717/3,994 (93.06%) | 151/3,994 (3.78%) | 151/3,994 (3.78%) | 151/277 (54.51%) | 126/277 (45.49%) |

`catalog-outside`는 모든 권역/split에서 **판정 불가**다. `UNMATCHED`나 `AMBIGUOUS`를 실제 카탈로그 부재로 치환하지 않았다. 위 표에는 identity unresolved의 정확한 count/rate가 별도로 있고, outside-candidate는 MATCHED positives 중 v1 eligibility를 통과하지 못한 건만 센다. visit row에 trip ID가 없는 양성 수와 request universe 밖 trip ID 양성 수는 8개 split 모두 0이었다.

### 현재 코드가 구별하는 positive match method

아래 값은 전체 distinct observed-positive 쌍 대비 count/rate다. `no_exact_signal`, `fuzzy_name_candidate`, `source_signal_conflict`, `name_address`, `conflicting_source_address_signals`는 현재 코드가 기록하는 구분만 그대로 집계했다. 다른 method인 `name_district`, `conflicting_exact_signals`, `category_type_conflict`, `region_unmapped`는 모든 셀에서 0이다. 코드는 `no_exact_signal`을 이름 미발견과 주소 결측으로 세분하지 않으므로 새 원인 분류를 추정해 추가하지 않았다.

| 권역 / split | `no_exact_signal` | `fuzzy_name_candidate` | `source_signal_conflict` | `name_address` | `conflicting_source_address_signals` |
| --- | ---: | ---: | ---: | ---: | ---: |
| capital / TL | 9,691/13,660 (70.94%) | 2,592/13,660 (18.98%) | 1,374/13,660 (10.06%) | 3/13,660 (0.02%) | 0/13,660 (0.00%) |
| capital / VL | 1,345/1,811 (74.27%) | 385/1,811 (21.26%) | 79/1,811 (4.36%) | 2/1,811 (0.11%) | 0/1,811 (0.00%) |
| west / TL | 13,142/19,584 (67.11%) | 3,962/19,584 (20.23%) | 2,452/19,584 (12.52%) | 28/19,584 (0.14%) | 0/19,584 (0.00%) |
| west / VL | 1,701/2,357 (72.17%) | 515/2,357 (21.85%) | 137/2,357 (5.81%) | 4/2,357 (0.17%) | 0/2,357 (0.00%) |
| east / TL | 11,642/20,456 (56.91%) | 3,174/20,456 (15.52%) | 5,442/20,456 (26.60%) | 198/20,456 (0.97%) | 0/20,456 (0.00%) |
| east / VL | 1,683/2,468 (68.19%) | 452/2,468 (18.31%) | 304/2,468 (12.32%) | 29/2,468 (1.18%) | 0/2,468 (0.00%) |
| jeju-islands / TL | 23,153/33,310 (69.51%) | 2,970/33,310 (8.92%) | 4,668/33,310 (14.01%) | 2,459/33,310 (7.38%) | 60/33,310 (0.18%) |
| jeju-islands / VL | 3,134/3,994 (78.47%) | 405/3,994 (10.14%) | 175/3,994 (4.38%) | 277/3,994 (6.94%) | 3/3,994 (0.08%) |

가중 합계로 보면 TL은 **2,688 / 87,010 (3.09%)**가 MATCHED, **84,322 / 87,010 (96.91%)**가 unresolved다. VL은 **312 / 10,630 (2.94%)**가 MATCHED, **10,318 / 10,630 (97.06%)**가 unresolved다. End-to-end candidate coverage는 TL **1,367 / 87,010 (1.57%)**, VL **163 / 10,630 (1.53%)**다. Conditional coverage는 TL **1,367 / 2,688 (50.86%)**, VL **163 / 312 (52.24%)**다. MATCHED positives 중 outside-candidate는 TL **1,321 / 2,688 (49.14%)**, VL **149 / 312 (47.76%)**다. Conditional coverage만 보면 후보 포함률은 절반가량이지만, identity resolution이 약 3%여서 전체 계약 성능이 충분하다는 근거는 아니다.

### #60 TL-observed proxy와 비교

아래는 같은 실행에서 기존 #60 proxy 함수를 exact mode로 재실행한 별도 결과다. proxy positive denominator는 기존 #60의 VL observed visit-event 단위이고, TourAPI 표의 denominator는 distinct `(TRAVEL_ID, POI_ID)` 쌍이므로 두 positive coverage를 동일한 분모로 취급하지 않는다. 둘 다 후보 universe가 다르며 과거 exposure를 뜻하지 않는다.

| 권역 | TL-observed 후보 수 | VL 요청 / non-empty | VL positive events | proxy positive coverage | cold-start positive events | cold-start share | TL/VL trip ID overlap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| capital | 8,655 | 320/320 (100.00%) | 1,942 | 956/1,942 (49.23%) | 986/1,942 | 50.77% | 0 |
| west | 9,429 | 320/320 (100.00%) | 2,596 | 1655/2,596 (63.75%) | 941/2,596 | 36.25% | 0 |
| east | 10,381 | 320/320 (100.00%) | 2,715 | 1668/2,715 (61.44%) | 1047/2,715 | 38.56% | 0 |
| jeju-islands | 13,152 | 320/320 (100.00%) | 4,621 | 3449/4,621 (74.64%) | 1172/4,621 | 25.36% | 0 |

권역별 proxy 후보 수는 capital 8,655, west 9,429, east 10,381, jeju-islands 13,152다. 각 권역 320개 VL trip request가 모두 non-empty이며 TL/VL trip ID overlap과 traveler overlap은 각각 0이다. region-level proxy candidate set을 모든 요청에 사용했으므로 요청당 후보 수도 해당 후보 수와 같다.

### 결론: 수정

정확 집계에서는 catalog snapshot과 지역 eligibility가 실제 non-empty 요청을 100% 만들지만, AI Hub observed positives와 TourAPI canonical identity 연결은 TL 3.09%, VL 2.94%에 그쳤다. End-to-end positive coverage도 TL 1.57%, VL 1.53%이며, MATCHED positives 중에서도 절반가량만 eligible 후보에 포함됐다. `no_exact_signal`이 unmatched를 대부분 설명하고, fuzzy-name candidate와 source-signal conflict가 큰 ambiguous 집계를 차지한다. 따라서 현재 identity/coverage 계약으로 ranker 평가를 진행하기에는 근거가 부족하다. 다만 unresolved는 TourAPI catalog 부재를 뜻하지 않으며, 수치만으로 TourAPI source 자체를 폐기할 수는 없다. **공식 ID crosswalk 또는 검증된 추가 identity 신호를 확보하고 outside-candidate 원인을 구분한 뒤 재측정**하는 결론으로 수정한다. 그때까지 `catalog-outside`는 판정 불가, unvisited는 unknown/unlabeled로 둔다.

재현 명령은 승인된 환경에서 `RAW_ROOT`, 권역별 `*_TL`/`*_VL`, 고정 snapshot의 `TOURAPI_SNAPSHOT`을 환경 변수로 설정한 뒤 실행한다. API key는 설정하지 않고 읽지 않는다. 입력 경로나 비밀값은 로그·문서·PR에 출력하지 않는다.

```bash
python3 scripts/recommendation/analyze_poi_catalog_candidate_coverage.py --raw-root "$RAW_ROOT" --snapshot "$TOURAPI_SNAPSHOT" --output results/experiments/poi-catalog-v1/actual-data-20261018-exact3 --run-id issue4-actual-20261018-exact3 --exact-aggregates --confirm-approved --confirm-terms --confirm-poi-candidate
```

상세 `metrics.csv`와 `run_metadata.json`은 Git-ignored 결과 경로에 남아 있다. manifest에는 run/config/code fingerprints, snapshot version/hash, retrieval time, role labels, field allowlist 및 privacy flags가 있고 raw path/ID/row/coordinate/text/secret은 없다.

## Synthetic validation and use

Run `python3 -m unittest discover -s tests -p 'test_poi_catalog_candidate_contract.py' -v`, plus the TourAPI snapshot adapter and experiment-design audit test modules. Tests cover deterministic exact-signal matching, ambiguity, conflict handling, coordinate exclusion, fail-closed eligibility, normalized code handling, independent request-region coverage, proxy rejection from product coverage, explicit CSV field maps, and domain-review checks. The adapter also includes a credential-safe read-only collector; the collection CLI persists only under ignored `results/`. `derive_proxy_requests_from_observations` returns a distinct `HistoricalRequestProxy` for historical-feasibility analysis only, requires one explicit region per request, and does not infer district selection. Product candidate coverage uses independently supplied `CandidateRequest` contexts. The candidate eligibility function must not receive observed category or post-event feedback.

Follow-up context-aware ranking work must use a versioned product catalog and this candidate contract, keep observed positives and unknowns distinct, and compare ranking metrics only within the same candidate definition.
