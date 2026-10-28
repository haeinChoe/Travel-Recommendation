# POI 카탈로그와 후보 자격 계약

> **문서 상태 (2026-10-28):** 이 문서는 TourAPI 제품 카탈로그와 #69의 개선된 identity bridge 근거를 설명한다. 최신 Stage 5 수치와 해당 분모를 과거 #4 baseline으로 대체하지 않는다. v2 오프라인 추천 문제와 AI Hub candidate eligibility는 [problem-definition-v2.md](problem-definition-v2.md)에서 우선 확인하며, 정적 POI Master 전체를 추천 가능 목록으로 간주하지 않는다.


## 질문과 현재 상태

이 문서는 **제품 서비스에서 어떤 POI를 추천 후보로 인정할지**, 그리고 **AI Hub 오프라인 추천 실험과 TourAPI 제품 카탈로그를 어떤 식별자 경계로 분리할지** 정한다.

**현재 상태: Issue #69 다단계 매칭 파이프라인(v2) 검증 완료 및 브리지 정책 확정.**

### 한눈에 보는 결론

- **초기 서비스 콜드스타트 브리지 확보**: AI Hub ↔ TourAPI POI 식별자 매칭에 5대 비퍼지(증거 기반) 다단계 파이프라인(Stage 2 veto 로직, Stage 5 엄격 200m 반경 및 최근접 50m 마진 게이팅 적용)을 적용하여, 권역 제약이 적용된 기준선(Baseline D) 4,279건(4.38%) 대비 **Stage 5 기준 26,454건(27.09%)**으로 약 6.2배 매칭 양성을 확보했다.
- **추천 지원 카탈로그 후보 집합 포함(candidate-contained)**: 2,097건(2.15%)에서 **14,933건(15.29%)**으로 약 7.1배 증가했다.
- **TourAPI Catalog Seed Coverage**: 적격 관광 후보(19,051개) 중 최소 1회 이상 매칭된 시드 POI가 Stage 0 **383개(2.01%)**에서 Stage 5 **2,753개(14.45%)**로 **+12.44%p** 순증했다. (시드 POI당 방문 관측 수 중앙값 2회, 평균 5.42회, p90 11회).
- **Anchor 일치율 100.00% 유지**: 기존 Stage 0 MATCHED 4,279건(고유 POI 1,013개)과 비교 시 누적 파이프라인에서 **충돌 0건(일치율 100.00%)**을 기록했다. 또한 Stage 0의 전체 주소 일치를 배제한 **독립(Non-short-circuited) 규칙별 검증**에서도 구조화 주소 키(372개), 시군구 일치(539개), 좌표 근접성(967개), 방문 행 신호(361개) 모두 **일치율 100.00%**, 위치 조건부 이름 정규화(973개) **99.79%**를 달성했다.
- **신규 승격 건(Newly Promoted) 물리 신호 사후 정합성 진단 및 층화 감사**: Stage 1~5 신규 승격 건의 WGS84 좌표 거리 중앙값 p50이 **6.2m ~ 25.7m**, 200m 이내 일치율이 **94.0% ~ 100.0%**를 기록했으며, 4개 권역 비례 층화 100건 표본 감사(seed=42) 및 전수 감사 결과 다중 물리 증거 무충돌률(Multi-Evidence Non-Conflict Rate)이 Stage 1 **표본 94.00% / 전수 95.17%**, Stage 2 **표본 97.00% / 전수 97.80%**, Stage 3 **표본 85.00% / 전수 84.94%**, Stage 4 **표본 94.00% / 전수 93.70%**, Stage 5 **표본 98.00% / 전수 96.24%**로 고신뢰성을 입증했다.
- **마스터 결측 코호트(26,884건, 고유 POI 19,321개) 신호 복원 및 전환**: 방문 행(`TN_VISIT_AREA_INFO`) 다중 신호 통합을 통해 신호 결측 상태(`identity_source_missing`)를 100% 해소(0건)하여 평가 가능 상태로 전환하였으며, 이 중 Stage 4에서 **3,327건(12.38%)**, Stage 5에서 **4,131건(15.37%)**이 실제로 `MATCHED`로 전환되었다. (나머지 22,570건은 현재 5단계 규칙으로 매칭되지 않은 `UNMATCHED` 상태로 유지되며, `UNMATCHED != catalog-outside` 원칙을 준수함).
- **관광 대상 코호트 분리 분석**: 순수 관광지(자연 48.74%, 역사 50.25%, 문화예술 50.21%, 휴양림/공원 41.49%, 테마파크 39.96%, 체험 35.58%)에서는 **매칭률 35~50%**, **후보 포함률 34~49%**로 실효 커버리지를 달성했다. 전체 평균 매칭률이 27% 수준인 원인은 식음료(33.5%), 쇼핑(10.4%), 단순 이동(환승) 등 비관광 방문지가 전체의 50% 이상을 차지하기 때문임을 과학적으로 규명했다.

아래 표는 이 결론의 근거가 된 canonical D(권역 제약 적용)의 핵심 집계를 보여준다.

| canonical D 최종 집계 | 건수 |
| --- | ---: |
| 전체 관측 양성 | 97,640 |
| 식별 정보 사용 가능 | 70,756 |
| `identity_source_missing` | 26,884 |
| MATCHED | 4,279 |
| AMBIGUOUS | 12,935 |
| UNMATCHED (식별 정보 사용 가능) | 53,542 |
| 후보 집합 포함 | 2,097 |
| 전체 대비 후보 포함 비율 | 2.15% |

### 결정

문자열 기반 진단은 종료한다. Name N1/N2는 50,933건 중 69건에서 추가 진단 후보를 만들었고, address A1은 이름 후보가 하나인 14,698건 중 12건만 정규화 후 주소가 일치했다. 이름 후보가 여러 개인 429건에서는 주소 정규화로 후보 하나를 고른 사례가 0건이었다.

이 값들은 장소 식별이 확인된 수가 아니다. 따라서 **단순 문자열 정규화로 얻을 수 있는 추가 근거는 충분하지 않다**고 판단한다. 공식 원천-제공자 식별자 연결 정보, 검증된 좌표 호환성, 신뢰할 수 있는 외부 주소·장소 식별자가 생기기 전까지 fuzzy threshold, title regex, address heuristic, token overlap을 이용해 `MATCHED`를 늘리지 않는다.

Issue #66에서 승인한 v1의 제품 서비스용 카탈로그는 TourAPI KorService2 v4.4이며, 제공자 식별자는 `(tourapi-korservice2, contentid)`, 추천 지원 유형은 `{12,14,28}`이다. 버전 정책은 [`config/recommendation/poi-catalog-policy-v1.json`](../../config/recommendation/poi-catalog-policy-v1.json)에 고정한다. 상세 산출물은 Git에서 제외된 `results/`에 두고, 공유 문서에는 개인을 식별하지 않는 집계만 기록한다.

AI Hub 네 권역의 공식 메타데이터는 각 권역을 구성하는 시도 목록을 제공하지 않는다. 사용자가 승인한 공식 광역권 분류를 사용해 **지역 코드 매핑**을 고정했다. 수도권=서울·인천·경기, 서부=충청권+호남권, 동부=동남권+대경권+강원권, 제주및도서권=제주권이다. 2026년 현행 법정동 상위 시도 코드 16개를 모두 매핑했다. 2026년 전남광주 통합특별시는 `12`, 강원특별자치도는 `51`, 전북특별자치도는 `52`이며, TourAPI가 반환한 세종 코드 `36110`은 공식 법정동 자료와 행정안전부 공지에 따라 충청권에 배정했다. 일괄 prefix 변환은 하지 않는다. AI Hub 메타데이터가 비제주 도서의 소속을 열거하지 않으므로 `jeju-islands`는 공식 제주권 코드 `50`에 매핑하며 다른 도서까지 포함한다고 주장하지 않는다.
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

## 식별 계약

AI Hub source key는 `(region, nonblank POI_ID)`, provider key는 `(tourapi-korservice2, contentid)`로 분리한다. 문자열 매칭은 실험상의 진단 결과이며 원천 FK 관계를 증명하지 않는다. identity matching은 명시된 권역 매핑 안에서 exact normalized name + exact address 또는 exact reviewed district 신호가 유일하고 다른 exact signal과 모순이 없을 때만 `MATCHED`다. 이름 단독 및 fuzzy 유사도는 `AMBIGUOUS` 진단에만 쓴다. 여러 동률 후보, 충돌, taxonomy veto는 확정하지 않는다. 좌표/거리 matching은 AI Hub와 TourAPI 좌표계 및 encoding 동일성이 검증될 때까지 비활성이다.

## 후보 자격과 지역 코드 매핑

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

## 확인된 사실, 해석, 미결정 사항

### Facts

- The AI Hub 2023 data dictionary lists `TN_POI_MASTER` as a POI information table and separately lists `TN_VISIT_AREA_INFO` as visit records with an optional `POI_ID` field.
- The data dictionary does not state that the visit-table `POI_ID` is a foreign key to the master or guaranteed to contain identical identifiers.
- The earlier approved context-POI analysis reports a region-scoped exact-string candidate join between visits and the historical master in `50–<75%` bands for capital, west, and east and `75–<90%` for jeju-islands, across TL and VL. Issue #4 did not re-read that separate table, and the earlier join was explicitly diagnostic rather than canonical identity evidence.
- 초기 one-result GET은 HTTP 200 / API `0000`와 string response type만 확인한 탐색이었다. 이후 v4.4 전체 법정동 코드 집합을 요청하는 고정 snapshot 수집을 수행했고 실제 후보 규모/커버리지는 아래에 별도 기록했다. 수집 성공은 장기 payload 보관 권한, provider identity의 의미, 2023년 당시 제공 여부를 증명하지 않는다.
- Issue #66에서 v1 계약을 승인했다. AI Hub 권역 라벨과 TL/VL 바인딩은 원천 데이터 집단으로 사용하며, 제품 지역 코드 매핑은 `config/recommendation/poi-catalog-policy-v1.json`에서 별도로 버전 관리한다.
- Bounded discovery found four `TN_POI_MASTER` candidates, one per explicit region Other-role binding. Repository documentation classifies the table as Other; the bindings and region/year role markers support the Other role and region/year. Current AI Hub usage terms support local read-only AI development with attribution and restrictions. The user explicitly confirmed these four candidates are the approved files for this diagnostic. A dedicated diagnostic read selected columns and the eight bound visit inputs after layout/header checks. The resulting link counts are descriptive within-region evidence only, not a declared foreign key or canonical identity; metadata conflicts were not compared.

#### Official source verification

- The [official data.go.kr listing](https://www.data.go.kr/data/15101578/openapi.do) identifies KorService2, `areaBasedList2`, its response model and formats, free/unrestricted reuse metadata, development auto approval, operational review, and quota 1,000. Its rendered schema does not expose endpoint field names/types.
- v4.4 매뉴얼은 `ldongCode2`의 전체 목록 조회와 페이지 단위 총건수 처리를 설명한다. 어댑터는 전체 법정동 집합을 요청하고 시도 코드를 중복 제거한다. 제품 지역 코드 매핑과 콘텐츠 유형 정책은 API 코드 목록에서 추론하지 않고 승인된 v1 계약으로 고정한다.
- AI Hub 2023 메타데이터는 네 권역 라벨을 정의하지만 각 권역에 포함되는 시도 목록은 제공하지 않는다. 사용자가 승인한 공식 7권역 분류를 사용해 v1 지역 코드 매핑을 완성하며, 제주가 아닌 도서 지역까지 포함한다고 주장하지 않는다.
- The [official Korean Tourism Organization FAQ](https://api.visitkorea.or.kr/?loginFlag=sso) discusses guide-preview usage. The user authorized one read-only API snapshot run. That authorization does not settle long-term payload retention terms; keep detailed payloads local and ignored.

### Inference

- TourAPI is a promising candidate catalog source because its official product offers current tourism metadata and region/type/category endpoints. Public metadata does not establish that its full contents match the product's intended POI domain.
- Provider item IDs and observed AI Hub IDs may be linkable for some records, but field-name similarity or a string join alone does not prove canonical identity.
- Ranking metrics require a fixed, versioned candidate contract; metrics from the TL-observed proxy are not directly comparable with any future product-catalog candidate metrics.

### Remaining limitations

- Current TourAPI membership does not establish historical 2023 availability, open/bookable status, exposure, or user consideration.
- The legal meaning of long-term bulk payload retention is not expanded beyond the official listing; retain the collected snapshot only in the approved ignored local results area.
- Identity match rates depend on the v1 exact-field rule and are not proof of a provider-declared foreign key. Coordinate matching remains disabled.
- exact aggregate 재실행에서 후보 요청은 모든 권역·TL/VL에서 100% non-empty였지만, 이 결과는 식별자 연결 방식을 통한 positive coverage 추정치를 신뢰 가능하게 만들지 않는다. unresolved는 catalog-outside와 다르므로 TourAPI catalog 부재나 부적합을 입증하지 않는다. 위 canonical 요약이 최종 판정이며, identity heuristic은 종료했다.

## Issue #4 실제 데이터 실험: 정확 집계 재실행 (2026-10-18)

2026-10-18에 고정된 TourAPI KorService2 v4.4 snapshot과 승인된 AI Hub 2023 네 권역 TL/VL 원본을 다시 읽어 `--exact-aggregates`로 재현했다. snapshot 수집은 반복하지 않았고 API 호출도 하지 않았다. 입력 원본은 read-only이며, 상세 집계와 manifest는 Git-ignored `results/experiments/poi-catalog-v1/actual-data-20261018-diagnostics6/`에 저장했다. 아래 수치는 개인·여행·POI ID, raw row, 좌표, 텍스트, 원본 경로를 포함하지 않는 집계다. 작은 집계도 값이 10 미만이라는 이유로 억제하지 않았다.

- run ID: `actual-data-20261018-diagnostics6`; aggregation mode: `exact_nonidentifying_aggregates`.
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

### 고유 source POI별 match method

분모는 고유 (region, POI_ID) 수다. exact_name_only_candidate는 exact normalized title만 찾았지만 주소/행정 신호로 identity를 확정하지 못한 상태다. 실제 fuzzy threshold는 이 경로에서 사용하지 않았다.

| 권역 / split | no_exact_signal | exact_name_only_candidate | source_signal_conflict | conflicting_source_address_signals | name_address | name_district | conflicting_exact_signals | category_type_conflict | fuzzy_name_candidate | region_unmapped | unmatched |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| capital / TL | 7,229/8,655 (83.52%) | 1,160/8,655 (13.40%) | 265/8,655 (3.06%) | 0/8,655 (0.00%) | 1/8,655 (0.01%) | 0/8,655 (0.00%) | 0/8,655 (0.00%) | 0/8,655 (0.00%) | 0/8,655 (0.00%) | 0/8,655 (0.00%) | 0 |
| capital / VL | 1,222/1,545 (79.09%) | 298/1,545 (19.29%) | 24/1,545 (1.55%) | 0/1,545 (0.00%) | 1/1,545 (0.06%) | 0/1,545 (0.00%) | 0/1,545 (0.00%) | 0/1,545 (0.00%) | 0/1,545 (0.00%) | 0/1,545 (0.00%) | 0 |
| west / TL | 7,691/9,429 (81.57%) | 1,366/9,429 (14.49%) | 357/9,429 (3.79%) | 0/9,429 (0.00%) | 15/9,429 (0.16%) | 0/9,429 (0.00%) | 0/9,429 (0.00%) | 0/9,429 (0.00%) | 0/9,429 (0.00%) | 0/9,429 (0.00%) | 0 |
| west / VL | 1,395/1,784 (78.20%) | 352/1,784 (19.73%) | 33/1,784 (1.85%) | 0/1,784 (0.00%) | 4/1,784 (0.22%) | 0/1,784 (0.00%) | 0/1,784 (0.00%) | 0/1,784 (0.00%) | 0/1,784 (0.00%) | 0/1,784 (0.00%) | 0 |
| east / TL | 8,063/10,381 (77.67%) | 1,385/10,381 (13.34%) | 800/10,381 (7.71%) | 0/10,381 (0.00%) | 133/10,381 (1.28%) | 0/10,381 (0.00%) | 0/10,381 (0.00%) | 0/10,381 (0.00%) | 0/10,381 (0.00%) | 0/10,381 (0.00%) | 0 |
| east / VL | 1,482/1,938 (76.47%) | 345/1,938 (17.80%) | 85/1,938 (4.39%) | 0/1,938 (0.00%) | 26/1,938 (1.34%) | 0/1,938 (0.00%) | 0/1,938 (0.00%) | 0/1,938 (0.00%) | 0/1,938 (0.00%) | 0/1,938 (0.00%) | 0 |
| jeju-islands / TL | 12,016/13,152 (91.36%) | 339/13,152 (2.58%) | 452/13,152 (3.44%) | 2/13,152 (0.02%) | 343/13,152 (2.61%) | 0/13,152 (0.00%) | 0/13,152 (0.00%) | 0/13,152 (0.00%) | 0/13,152 (0.00%) | 0/13,152 (0.00%) | 0 |
| jeju-islands / VL | 2,316/2,677 (86.51%) | 171/2,677 (6.39%) | 46/2,677 (1.72%) | 1/2,677 (0.04%) | 143/2,677 (5.34%) | 0/2,677 (0.00%) | 0/2,677 (0.00%) | 0/2,677 (0.00%) | 0/2,677 (0.00%) | 0/2,677 (0.00%) | 0 |

### Observed-positive별 match method

분모는 권역/split 전체 distinct observed-positive 쌍이다. no_exact_signal은 같은 제품 권역에서 exact normalized title 후보를 찾지 못했다는 뜻이며 TourAPI catalog 부재를 뜻하지 않는다. 기존 fuzzy_name_candidate 라벨은 exact_name_only_candidate로 수정했다.

| 권역 / split | no_exact_signal | exact_name_only_candidate | source_signal_conflict | conflicting_source_address_signals | name_address | name_district | conflicting_exact_signals | category_type_conflict | fuzzy_name_candidate | region_unmapped | unmatched |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| capital / TL | 9,691/13,660 (70.94%) | 2,592/13,660 (18.98%) | 1,374/13,660 (10.06%) | 0/13,660 (0.00%) | 3/13,660 (0.02%) | 0/13,660 (0.00%) | 0/13,660 (0.00%) | 0/13,660 (0.00%) | 0/13,660 (0.00%) | 0/13,660 (0.00%) | 0 |
| capital / VL | 1,345/1,811 (74.27%) | 385/1,811 (21.26%) | 79/1,811 (4.36%) | 0/1,811 (0.00%) | 2/1,811 (0.11%) | 0/1,811 (0.00%) | 0/1,811 (0.00%) | 0/1,811 (0.00%) | 0/1,811 (0.00%) | 0/1,811 (0.00%) | 0 |
| west / TL | 13,142/19,584 (67.11%) | 3,962/19,584 (20.23%) | 2,452/19,584 (12.52%) | 0/19,584 (0.00%) | 28/19,584 (0.14%) | 0/19,584 (0.00%) | 0/19,584 (0.00%) | 0/19,584 (0.00%) | 0/19,584 (0.00%) | 0/19,584 (0.00%) | 0 |
| west / VL | 1,701/2,357 (72.17%) | 515/2,357 (21.85%) | 137/2,357 (5.81%) | 0/2,357 (0.00%) | 4/2,357 (0.17%) | 0/2,357 (0.00%) | 0/2,357 (0.00%) | 0/2,357 (0.00%) | 0/2,357 (0.00%) | 0/2,357 (0.00%) | 0 |
| east / TL | 11,642/20,456 (56.91%) | 3,174/20,456 (15.52%) | 5,442/20,456 (26.60%) | 0/20,456 (0.00%) | 198/20,456 (0.97%) | 0/20,456 (0.00%) | 0/20,456 (0.00%) | 0/20,456 (0.00%) | 0/20,456 (0.00%) | 0/20,456 (0.00%) | 0 |
| east / VL | 1,683/2,468 (68.19%) | 452/2,468 (18.31%) | 304/2,468 (12.32%) | 0/2,468 (0.00%) | 29/2,468 (1.18%) | 0/2,468 (0.00%) | 0/2,468 (0.00%) | 0/2,468 (0.00%) | 0/2,468 (0.00%) | 0/2,468 (0.00%) | 0 |
| jeju-islands / TL | 23,153/33,310 (69.51%) | 2,970/33,310 (8.92%) | 4,668/33,310 (14.01%) | 60/33,310 (0.18%) | 2,459/33,310 (7.38%) | 0/33,310 (0.00%) | 0/33,310 (0.00%) | 0/33,310 (0.00%) | 0/33,310 (0.00%) | 0/33,310 (0.00%) | 0 |
| jeju-islands / VL | 3,134/3,994 (78.47%) | 405/3,994 (10.14%) | 175/3,994 (4.38%) | 3/3,994 (0.08%) | 277/3,994 (6.94%) | 0/3,994 (0.00%) | 0/3,994 (0.00%) | 0/3,994 (0.00%) | 0/3,994 (0.00%) | 0/3,994 (0.00%) | 0 |

### Identity 진단 funnel (2026-10-18 재실행)

동일한 고정 TourAPI KorService2 v4.4 snapshot과 승인된 2023 AI Hub TL/VL split을 재사용했다. TourAPI API를 새로 호출하지 않았다. Identity 탐색은 content type eligibility 전의 전체 snapshot으로 수행했고, {12,14,28} 지원 정책은 MATCHED 이후 candidate eligibility 판정에만 적용했다. 각 값은 exact count / 해당 단계 분모 (rate)다. 고유 source POI와 observed-positive 쌍은 별도 단위다.

exact-title 후보 0은 동일 제품 권역에서 normalize_text(POI_NM)과 exact normalized TourAPI title이 일치하는 항목이 없다는 뜻이다. TourAPI catalog 부재를 뜻하지 않으며, 후보 탐색은 모든 content type을 포함한다.

동일 source POI가 여러 row에서 이름 signal을 달리 가지면 후보 수는 각 distinct normalized name에서 찾은 catalog contentid의 합집합을 중복 제거해 센다. 임의의 대표 row/name을 고르지 않으며, name variation은 별도 분류로 보고한다.

#### Exact-title 후보 수

| 권역 / split | 고유 source POI | source 후보 0 | source 후보 1 | source 후보 2+ | observed positives | positive 후보 0 | positive 후보 1 | positive 후보 2+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| capital / TL | 8,655 | 7,408/8,655 (85.59%) | 1,211/8,655 (13.99%) | 36/8,655 (0.42%) | 13,660 | 10,336/13,660 (75.67%) | 3,150/13,660 (23.06%) | 174/13,660 (1.27%) |
| capital / VL | 1,545 | 1,233/1,545 (79.81%) | 299/1,545 (19.35%) | 13/1,545 (0.84%) | 1,811 | 1,376/1,811 (75.98%) | 405/1,811 (22.36%) | 30/1,811 (1.66%) |
| west / TL | 9,429 | 7,954/9,429 (84.36%) | 1,435/9,429 (15.22%) | 40/9,429 (0.42%) | 19,584 | 14,870/19,584 (75.93%) | 4,611/19,584 (23.54%) | 103/19,584 (0.53%) |
| west / VL | 1,784 | 1,421/1,784 (79.65%) | 359/1,784 (20.12%) | 4/1,784 (0.22%) | 2,357 | 1,814/2,357 (76.96%) | 535/2,357 (22.70%) | 8/2,357 (0.34%) |
| east / TL | 10,381 | 8,611/10,381 (82.95%) | 1,739/10,381 (16.75%) | 31/10,381 (0.30%) | 20,456 | 15,235/20,456 (74.48%) | 5,105/20,456 (24.96%) | 116/20,456 (0.57%) |
| east / VL | 1,938 | 1,530/1,938 (78.95%) | 400/1,938 (20.64%) | 8/1,938 (0.41%) | 2,468 | 1,860/2,468 (75.36%) | 591/2,468 (23.95%) | 17/2,468 (0.69%) |
| jeju-islands / TL | 13,152 | 12,416/13,152 (94.40%) | 734/13,152 (5.58%) | 2/13,152 (0.02%) | 33,310 | 26,793/33,310 (80.44%) | 6,457/33,310 (19.38%) | 60/33,310 (0.18%) |
| jeju-islands / VL | 2,677 | 2,352/2,677 (87.86%) | 323/2,677 (12.07%) | 2/2,677 (0.07%) | 3,994 | 3,246/3,994 (81.27%) | 738/3,994 (18.48%) | 10/3,994 (0.25%) |

#### Source 이름·주소 신호 존재 여부

ROAD_NM_ADDR / LOTNO_ADDR 존재는 해당 POI의 여러 source row 중 공백이 아닌 값이 하나라도 있으면 존재로 셌다. exact-title catalog address의 분모는 exact-title 후보가 하나 이상인 source POI 또는 positive다. candidate address mixed는 같은 source의 exact-title 후보 중 주소가 있는 항목과 없는 항목이 함께 있는 경우다. 이름 blank/nonblank와 주소 존재/부재를 고유 source POI 및 positive 단위로 모두 표시한다.

| 권역 / split | source name nonblank | source name blank | source road 존재 | source road 부재 | source lot 존재 | source lot 부재 | source 주소 중 하나 존재 | source 주소 모두 부재 | source 후보 catalog 주소 있음 | source 후보 catalog 주소 없음 | source 후보 catalog 주소 혼합 | positive name nonblank | positive name blank | positive road 존재 | positive road 부재 | positive lot 존재 | positive lot 부재 | positive 주소 중 하나 존재 | positive 주소 모두 부재 | positive 후보 catalog 주소 있음 | positive 후보 catalog 주소 없음 | positive 후보 catalog 주소 혼합 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| capital / TL | 8,655/8,655 (100.00%) | 0/8,655 (0.00%) | 7,940/8,655 (91.74%) | 715/8,655 (8.26%) | 8,594/8,655 (99.30%) | 61/8,655 (0.70%) | 8,645/8,655 (99.88%) | 10/8,655 (0.12%) | 1,247/1,247 (100.00%) | 0/1,247 (0.00%) | 0/1,247 (0.00%) | 13,660/13,660 (100.00%) | 0/13,660 (0.00%) | 12,146/13,660 (88.92%) | 1,514/13,660 (11.08%) | 13,598/13,660 (99.55%) | 62/13,660 (0.45%) | 13,650/13,660 (99.93%) | 10/13,660 (0.07%) | 3,324/3,324 (100.00%) | 0/3,324 (0.00%) | 0/3,324 (0.00%) |
| capital / VL | 1,545/1,545 (100.00%) | 0/1,545 (0.00%) | 1,389/1,545 (89.90%) | 156/1,545 (10.10%) | 1,538/1,545 (99.55%) | 7/1,545 (0.45%) | 1,544/1,545 (99.94%) | 1/1,545 (0.06%) | 312/312 (100.00%) | 0/312 (0.00%) | 0/312 (0.00%) | 1,811/1,811 (100.00%) | 0/1,811 (0.00%) | 1,602/1,811 (88.46%) | 209/1,811 (11.54%) | 1,804/1,811 (99.61%) | 7/1,811 (0.39%) | 1,810/1,811 (99.94%) | 1/1,811 (0.06%) | 435/435 (100.00%) | 0/435 (0.00%) | 0/435 (0.00%) |
| west / TL | 9,429/9,429 (100.00%) | 0/9,429 (0.00%) | 8,413/9,429 (89.22%) | 1,016/9,429 (10.78%) | 9,270/9,429 (98.31%) | 159/9,429 (1.69%) | 9,383/9,429 (99.51%) | 46/9,429 (0.49%) | 1,475/1,475 (100.00%) | 0/1,475 (0.00%) | 0/1,475 (0.00%) | 19,584/19,584 (100.00%) | 0/19,584 (0.00%) | 17,074/19,584 (87.18%) | 2,510/19,584 (12.82%) | 19,425/19,584 (99.19%) | 159/19,584 (0.81%) | 19,538/19,584 (99.77%) | 46/19,584 (0.23%) | 4,714/4,714 (100.00%) | 0/4,714 (0.00%) | 0/4,714 (0.00%) |
| west / VL | 1,784/1,784 (100.00%) | 0/1,784 (0.00%) | 1,574/1,784 (88.23%) | 210/1,784 (11.77%) | 1,753/1,784 (98.26%) | 31/1,784 (1.74%) | 1,779/1,784 (99.72%) | 5/1,784 (0.28%) | 363/363 (100.00%) | 0/363 (0.00%) | 0/363 (0.00%) | 2,357/2,357 (100.00%) | 0/2,357 (0.00%) | 2,050/2,357 (86.97%) | 307/2,357 (13.03%) | 2,326/2,357 (98.68%) | 31/2,357 (1.32%) | 2,352/2,357 (99.79%) | 5/2,357 (0.21%) | 543/543 (100.00%) | 0/543 (0.00%) | 0/543 (0.00%) |
| east / TL | 10,381/10,381 (100.00%) | 0/10,381 (0.00%) | 9,241/10,381 (89.02%) | 1,140/10,381 (10.98%) | 10,214/10,381 (98.39%) | 167/10,381 (1.61%) | 10,337/10,381 (99.58%) | 44/10,381 (0.42%) | 1,770/1,770 (100.00%) | 0/1,770 (0.00%) | 0/1,770 (0.00%) | 20,456/20,456 (100.00%) | 0/20,456 (0.00%) | 17,582/20,456 (85.95%) | 2,874/20,456 (14.05%) | 20,287/20,456 (99.17%) | 169/20,456 (0.83%) | 20,411/20,456 (99.78%) | 45/20,456 (0.22%) | 5,221/5,221 (100.00%) | 0/5,221 (0.00%) | 0/5,221 (0.00%) |
| east / VL | 1,938/1,938 (100.00%) | 0/1,938 (0.00%) | 1,692/1,938 (87.31%) | 246/1,938 (12.69%) | 1,883/1,938 (97.16%) | 55/1,938 (2.84%) | 1,912/1,938 (98.66%) | 26/1,938 (1.34%) | 408/408 (100.00%) | 0/408 (0.00%) | 0/408 (0.00%) | 2,468/2,468 (100.00%) | 0/2,468 (0.00%) | 2,137/2,468 (86.59%) | 331/2,468 (13.41%) | 2,413/2,468 (97.77%) | 55/2,468 (2.23%) | 2,442/2,468 (98.95%) | 26/2,468 (1.05%) | 608/608 (100.00%) | 0/608 (0.00%) | 0/608 (0.00%) |
| jeju-islands / TL | 13,152/13,152 (100.00%) | 0/13,152 (0.00%) | 11,702/13,152 (88.98%) | 1,450/13,152 (11.02%) | 12,980/13,152 (98.69%) | 172/13,152 (1.31%) | 13,094/13,152 (99.56%) | 58/13,152 (0.44%) | 736/736 (100.00%) | 0/736 (0.00%) | 0/736 (0.00%) | 33,310/33,310 (100.00%) | 0/33,310 (0.00%) | 28,333/33,310 (85.06%) | 4,977/33,310 (14.94%) | 33,136/33,310 (99.48%) | 174/33,310 (0.52%) | 33,252/33,310 (99.83%) | 58/33,310 (0.17%) | 6,517/6,517 (100.00%) | 0/6,517 (0.00%) | 0/6,517 (0.00%) |
| jeju-islands / VL | 2,677/2,677 (100.00%) | 0/2,677 (0.00%) | 2,327/2,677 (86.93%) | 350/2,677 (13.07%) | 2,664/2,677 (99.51%) | 13/2,677 (0.49%) | 2,670/2,677 (99.74%) | 7/2,677 (0.26%) | 325/325 (100.00%) | 0/325 (0.00%) | 0/325 (0.00%) | 3,994/3,994 (100.00%) | 0/3,994 (0.00%) | 3,369/3,994 (84.35%) | 625/3,994 (15.65%) | 3,981/3,994 (99.67%) | 13/3,994 (0.33%) | 3,987/3,994 (99.82%) | 7/3,994 (0.18%) | 748/748 (100.00%) | 0/748 (0.00%) | 0/748 (0.00%) |

#### Exact-title 후보가 1개인 경우의 주소 검증

주소 match는 현재 NFKC + casefold + whitespace normalization 뒤 exact equality만 센다. mismatch는 주소체계/표기 차이일 수도 있으며, 서로 다른 장소라는 판정은 아니다. 도로명과 지번 exact match는 서로 겹칠 수 있다.

| 권역 / split | source road exact | source lot exact | source 주소 mismatch | source 주소 없음 | catalog 주소 없음 | positive road exact | positive lot exact | positive 주소 mismatch | positive 주소 없음 | catalog 주소 없음 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| capital / TL | 0/1,211 (0.00%) | 1/1,211 (0.08%) | 1,209/1,211 (99.83%) | 1/1,211 (0.08%) | 0/1,211 (0.00%) | 0/3,150 (0.00%) | 3/3,150 (0.10%) | 3,146/3,150 (99.87%) | 1/3,150 (0.03%) | 0/3,150 (0.00%) |
| capital / VL | 0/299 (0.00%) | 1/299 (0.33%) | 298/299 (99.67%) | 0/299 (0.00%) | 0/299 (0.00%) | 0/405 (0.00%) | 2/405 (0.49%) | 403/405 (99.51%) | 0/405 (0.00%) | 0/405 (0.00%) |
| west / TL | 14/1,435 (0.98%) | 1/1,435 (0.07%) | 1,418/1,435 (98.82%) | 2/1,435 (0.14%) | 0/1,435 (0.00%) | 27/4,611 (0.59%) | 1/4,611 (0.02%) | 4,581/4,611 (99.35%) | 2/4,611 (0.04%) | 0/4,611 (0.00%) |
| west / VL | 4/359 (1.11%) | 0/359 (0.00%) | 355/359 (98.89%) | 0/359 (0.00%) | 0/359 (0.00%) | 4/535 (0.75%) | 0/535 (0.00%) | 531/535 (99.25%) | 0/535 (0.00%) | 0/535 (0.00%) |
| east / TL | 201/1,739 (11.56%) | 14/1,739 (0.81%) | 1,521/1,739 (87.46%) | 3/1,739 (0.17%) | 0/1,739 (0.00%) | 680/5,105 (13.32%) | 50/5,105 (0.98%) | 4,372/5,105 (85.64%) | 3/5,105 (0.06%) | 0/5,105 (0.00%) |
| east / VL | 32/400 (8.00%) | 4/400 (1.00%) | 358/400 (89.50%) | 6/400 (1.50%) | 0/400 (0.00%) | 52/591 (8.80%) | 6/591 (1.02%) | 527/591 (89.17%) | 6/591 (1.02%) | 0/591 (0.00%) |
| jeju-islands / TL | 344/734 (46.87%) | 23/734 (3.13%) | 363/734 (49.46%) | 4/734 (0.54%) | 0/734 (0.00%) | 2,616/6,457 (40.51%) | 334/6,457 (5.17%) | 3,503/6,457 (54.25%) | 4/6,457 (0.06%) | 0/6,457 (0.00%) |
| jeju-islands / VL | 141/323 (43.65%) | 8/323 (2.48%) | 171/323 (52.94%) | 3/323 (0.93%) | 0/323 (0.00%) | 283/738 (38.35%) | 31/738 (4.20%) | 421/738 (57.05%) | 3/738 (0.41%) | 0/738 (0.00%) |

#### 동일 POI_ID의 source row signal variation

각 source POI는 서로 배타적인 한 분류에 든다. multiple_meaningful_fields_differ는 이름·주소·시군구 중 둘 이상의 normalized signal이 다름을 뜻한다. positive 수는 해당 POI를 관측한 distinct (TRAVEL_ID, POI_ID) 쌍으로 가중했다. 이 분류는 source row 차이를 설명할 뿐 identity 승격에 쓰지 않는다.

**고유 source POI 단위**

| 권역 / split | 차이 없음 | 공백 차이만 있음 | 이름 다름 | 주소 값 다름 | 한 row에만 주소 존재 | 도로명/지번 칸만 다름 | SGG_CD만 다름 | 둘 이상 의미 필드 다름 | 기타 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| capital / TL | 8,390/8,655 (96.94%) | 1/8,655 (0.01%) | 135/8,655 (1.56%) | 40/8,655 (0.46%) | 0/8,655 (0.00%) | 0/8,655 (0.00%) | 11/8,655 (0.13%) | 78/8,655 (0.90%) | 0/8,655 (0.00%) |
| capital / VL | 1,521/1,545 (98.45%) | 0/1,545 (0.00%) | 12/1,545 (0.78%) | 7/1,545 (0.45%) | 0/1,545 (0.00%) | 0/1,545 (0.00%) | 0/1,545 (0.00%) | 5/1,545 (0.32%) | 0/1,545 (0.00%) |
| west / TL | 9,072/9,429 (96.21%) | 0/9,429 (0.00%) | 188/9,429 (1.99%) | 35/9,429 (0.37%) | 1/9,429 (0.01%) | 0/9,429 (0.00%) | 12/9,429 (0.13%) | 121/9,429 (1.28%) | 0/9,429 (0.00%) |
| west / VL | 1,751/1,784 (98.15%) | 0/1,784 (0.00%) | 15/1,784 (0.84%) | 2/1,784 (0.11%) | 1/1,784 (0.06%) | 0/1,784 (0.00%) | 1/1,784 (0.06%) | 14/1,784 (0.78%) | 0/1,784 (0.00%) |
| east / TL | 9,581/10,381 (92.29%) | 1/10,381 (0.01%) | 92/10,381 (0.89%) | 493/10,381 (4.75%) | 2/10,381 (0.02%) | 0/10,381 (0.00%) | 15/10,381 (0.14%) | 197/10,381 (1.90%) | 0/10,381 (0.00%) |
| east / VL | 1,853/1,938 (95.61%) | 1/1,938 (0.05%) | 9/1,938 (0.46%) | 53/1,938 (2.73%) | 0/1,938 (0.00%) | 0/1,938 (0.00%) | 3/1,938 (0.15%) | 19/1,938 (0.98%) | 0/1,938 (0.00%) |
| jeju-islands / TL | 12,700/13,152 (96.56%) | 1/13,152 (0.01%) | 193/13,152 (1.47%) | 106/13,152 (0.81%) | 0/13,152 (0.00%) | 0/13,152 (0.00%) | 7/13,152 (0.05%) | 145/13,152 (1.10%) | 0/13,152 (0.00%) |
| jeju-islands / VL | 2,631/2,677 (98.28%) | 0/2,677 (0.00%) | 15/2,677 (0.56%) | 13/2,677 (0.49%) | 0/2,677 (0.00%) | 0/2,677 (0.00%) | 3/2,677 (0.11%) | 15/2,677 (0.56%) | 0/2,677 (0.00%) |

**observed-positive 쌍 단위**

| 권역 / split | 차이 없음 | 공백 차이만 있음 | 이름 다름 | 주소 값 다름 | 한 row에만 주소 존재 | 도로명/지번 칸만 다름 | SGG_CD만 다름 | 둘 이상 의미 필드 다름 | 기타 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| capital / TL | 12,286/13,660 (89.94%) | 2/13,660 (0.01%) | 478/13,660 (3.50%) | 185/13,660 (1.35%) | 0/13,660 (0.00%) | 0/13,660 (0.00%) | 88/13,660 (0.64%) | 621/13,660 (4.55%) | 0/13,660 (0.00%) |
| capital / VL | 1,732/1,811 (95.64%) | 0/1,811 (0.00%) | 33/1,811 (1.82%) | 22/1,811 (1.21%) | 0/1,811 (0.00%) | 0/1,811 (0.00%) | 0/1,811 (0.00%) | 24/1,811 (1.33%) | 0/1,811 (0.00%) |
| west / TL | 17,132/19,584 (87.48%) | 0/19,584 (0.00%) | 910/19,584 (4.65%) | 210/19,584 (1.07%) | 29/19,584 (0.15%) | 0/19,584 (0.00%) | 70/19,584 (0.36%) | 1,233/19,584 (6.30%) | 0/19,584 (0.00%) |
| west / VL | 2,220/2,357 (94.19%) | 0/2,357 (0.00%) | 58/2,357 (2.46%) | 5/2,357 (0.21%) | 25/2,357 (1.06%) | 0/2,357 (0.00%) | 2/2,357 (0.08%) | 47/2,357 (1.99%) | 0/2,357 (0.00%) |
| east / TL | 15,014/20,456 (73.40%) | 36/20,456 (0.18%) | 279/20,456 (1.36%) | 2,964/20,456 (14.49%) | 58/20,456 (0.28%) | 0/20,456 (0.00%) | 85/20,456 (0.42%) | 2,020/20,456 (9.87%) | 0/20,456 (0.00%) |
| east / VL | 2,164/2,468 (87.68%) | 5/2,468 (0.20%) | 28/2,468 (1.13%) | 203/2,468 (8.23%) | 0/2,468 (0.00%) | 0/2,468 (0.00%) | 6/2,468 (0.24%) | 62/2,468 (2.51%) | 0/2,468 (0.00%) |
| jeju-islands / TL | 28,642/33,310 (85.99%) | 6/33,310 (0.02%) | 903/33,310 (2.71%) | 550/33,310 (1.65%) | 0/33,310 (0.00%) | 0/33,310 (0.00%) | 39/33,310 (0.12%) | 3,170/33,310 (9.52%) | 0/33,310 (0.00%) |
| jeju-islands / VL | 3,819/3,994 (95.62%) | 0/3,994 (0.00%) | 50/3,994 (1.25%) | 60/3,994 (1.50%) | 0/3,994 (0.00%) | 0/3,994 (0.00%) | 21/3,994 (0.53%) | 44/3,994 (1.10%) | 0/3,994 (0.00%) |

#### MATCHED observed positives의 TourAPI contenttypeid

각 type 셀은 해당 권역/split의 MATCHED positive 총수 대비 count/rate다. 모든 type을 identity 전에 제거하지 않았다.

| 권역 / split | MATCHED positives | 12 | 14 | 15 | 25 | 28 | 32 | 38 | 39 | blank |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| capital / TL | 3 | 3/3 (100.00%) | 0/3 (0.00%) | 0/3 (0.00%) | 0/3 (0.00%) | 0/3 (0.00%) | 0/3 (0.00%) | 0/3 (0.00%) | 0/3 (0.00%) | 0 |
| capital / VL | 2 | 2/2 (100.00%) | 0/2 (0.00%) | 0/2 (0.00%) | 0/2 (0.00%) | 0/2 (0.00%) | 0/2 (0.00%) | 0/2 (0.00%) | 0/2 (0.00%) | 0 |
| west / TL | 28 | 13/28 (46.43%) | 3/28 (10.71%) | 0/28 (0.00%) | 0/28 (0.00%) | 0/28 (0.00%) | 0/28 (0.00%) | 0/28 (0.00%) | 12/28 (42.86%) | 0 |
| west / VL | 4 | 2/4 (50.00%) | 0/4 (0.00%) | 0/4 (0.00%) | 0/4 (0.00%) | 0/4 (0.00%) | 0/4 (0.00%) | 0/4 (0.00%) | 2/4 (50.00%) | 0 |
| east / TL | 198 | 43/198 (21.72%) | 26/198 (13.13%) | 1/198 (0.51%) | 0/198 (0.00%) | 3/198 (1.52%) | 8/198 (4.04%) | 2/198 (1.01%) | 115/198 (58.08%) | 0 |
| east / VL | 29 | 7/29 (24.14%) | 1/29 (3.45%) | 0/29 (0.00%) | 0/29 (0.00%) | 0/29 (0.00%) | 1/29 (3.45%) | 1/29 (3.45%) | 19/29 (65.52%) | 0 |
| jeju-islands / TL | 2,459 | 1,012/2,459 (41.15%) | 225/2,459 (9.15%) | 0/2,459 (0.00%) | 0/2,459 (0.00%) | 39/2,459 (1.59%) | 132/2,459 (5.37%) | 74/2,459 (3.01%) | 977/2,459 (39.73%) | 0 |
| jeju-islands / VL | 277 | 117/277 (42.24%) | 28/277 (10.11%) | 0/277 (0.00%) | 0/277 (0.00%) | 6/277 (2.17%) | 11/277 (3.97%) | 4/277 (1.44%) | 111/277 (40.07%) | 0 |

#### MATCHED-but-ineligible observed positives

분모는 MATCHED positives다. 현재 실험에서 실제 발생한 reason은 unsupported_content_type 하나이며 나머지는 0이다. 지원하지 않는 유형도 identity MATCHED로 남는다.

| 권역 / split | MATCHED positives | unsupported_content_type | outside_request_region | outside_request_district | required_field_invalid | request_region_unmapped | request_district_invalid |
| --- | --- | --- | --- | --- | --- | --- | --- |
| capital / TL | 3 | 0/3 (0.00%) | 0/3 (0.00%) | 0/3 (0.00%) | 0/3 (0.00%) | 0/3 (0.00%) | 0/3 (0.00%) |
| capital / VL | 2 | 0/2 (0.00%) | 0/2 (0.00%) | 0/2 (0.00%) | 0/2 (0.00%) | 0/2 (0.00%) | 0/2 (0.00%) |
| west / TL | 28 | 12/28 (42.86%) | 0/28 (0.00%) | 0/28 (0.00%) | 0/28 (0.00%) | 0/28 (0.00%) | 0/28 (0.00%) |
| west / VL | 4 | 2/4 (50.00%) | 0/4 (0.00%) | 0/4 (0.00%) | 0/4 (0.00%) | 0/4 (0.00%) | 0/4 (0.00%) |
| east / TL | 198 | 126/198 (63.64%) | 0/198 (0.00%) | 0/198 (0.00%) | 0/198 (0.00%) | 0/198 (0.00%) | 0/198 (0.00%) |
| east / VL | 29 | 21/29 (72.41%) | 0/29 (0.00%) | 0/29 (0.00%) | 0/29 (0.00%) | 0/29 (0.00%) | 0/29 (0.00%) |
| jeju-islands / TL | 2,459 | 1,183/2,459 (48.11%) | 0/2,459 (0.00%) | 0/2,459 (0.00%) | 0/2,459 (0.00%) | 0/2,459 (0.00%) | 0/2,459 (0.00%) |
| jeju-islands / VL | 277 | 126/277 (45.49%) | 0/277 (0.00%) | 0/277 (0.00%) | 0/277 (0.00%) | 0/277 (0.00%) | 0/277 (0.00%) |

#### 진단 해석과 남은 부분

- TL observed positives 중 exact-title 후보가 0인 값은 67,234/87,010 (77.27%), VL은 8,296/10,630 (78.04%)다. 이는 현재 no_exact_signal의 주된 관찰 가능한 단계지만 catalog 부재 / 표기 차이 / 권역 분류 문제를 구분하지 못한다.
- exact-title 후보가 1개인 positive 중 주소가 존재하지만 exact match하지 않은 경우는 TL 15,602/19,323 (80.74%), VL 1,882/2,269 (82.94%)다. source 이름 blank는 0건, source 주소 둘 다 없음은 TL 159/87,010 (0.18%), VL 39/10,630 (0.37%)다. exact-title 후보 측 TourAPI 주소 부재는 0건이다.
- exact-title 후보가 2개 이상인 positives는 TL 453/87,010 (0.52%), VL 65/10,630 (0.61%)다.
- source signal variation은 TL positive 13,936/87,010 (16.02%), VL 695/10,630 (6.54%)에서 관찰됐다. 위 표의 field별 분류는 기존 source_signal_conflict method와 완전히 같지 않다. 기존 판정은 원본 tuple의 distinctness를 사용하고 진단은 필드별 normalization으로 설명한다. whitespace-only도 분리했다.
- 이 진단으로 미해결의 대부분은 같은 권역 exact-title 후보가 없고, 후보 하나가 있어도 exact-address 검증에서 막힌다는 단계까지 수치화했다. 그러나 title miss가 catalog 부재인지 표기 차이인지 판별할 수 없고, address mismatch도 주소체계/상세주소/실제 장소 차이를 분리하지 못한다. 진단 지표들은 서로 겹치므로 더해 unresolved를 분해하지 않는다. 따라서 97% unresolved의 원인을 전부 설명하지 못하며 나머지는 판정 불가다.
- 이후 수행한 N1/N2 및 A1/A2 진단을 반영한 종료 판정은 아래에 기록했다. 문자열 heuristic 실험은 종료했으며 다음 식별 작업은 공식 원천-제공자 식별자 연결 정보, 검증된 좌표 호환성 또는 신뢰 가능한 외부 주소/장소 식별자가 확보될 때만 진행한다.

#### Name candidate recovery shadow diagnostic

Arm D에서 `global_exact_title_absent`인 **50,933 observed positives**를 대상으로 문자열 진단을 추가했다. canonical matcher와 A/B/C/D/E 결과는 변경하지 않았다. baseline N0는 기존 `normalize_text()`(NFKC + casefold + whitespace)이며, N1은 구두점을 공백으로 치환한 뒤 공백을 정리한 후보 키다. N2는 기존 제목과 괄호 내용을 제거한 제목을 각각 조회한다. N3는 suffix/토큰의 존재만 태그하며 문자열을 제거하지 않는다. N4는 exact miss에 한해 character-bigram overlap 상위 250개 title을 사전 후보로 고른 뒤 `SequenceMatcher` 상위 5개 normalized title을 진단 후보로 조회한다. N4의 contentid 후보 수는 여러 POI가 같은 title을 공유할 수 있어 5보다 클 수 있다. 모든 N1/N2/N4 후보는 shadow 결과이며 MATCHED 판정에 전달되지 않는다.

| 분모 | 단계 | candidate 0 | candidate 1 | candidate 2+ |
| --- | --- | ---: | ---: | ---: |
| observed positives 50,933 | N0 exact miss | 50,933 (100.00%) | 0 (0.00%) | 0 (0.00%) |
| observed positives 50,933 | N1 구두점 | 50,922 (99.98%) | 11 (0.02%) | 0 (0.00%) |
| observed positives 50,933 | N2 괄호 포함 | 50,864 (99.86%) | 68 (0.13%) | 1 (0.00%) |
| observed positives 50,933 | N4 fuzzy retrieval | 627 (1.23%) | 414 (0.81%) | 49,892 (97.96%) |
| 고유 `(region, POI_ID)` 20,856 | N0 exact miss | 20,856 (100.00%) | 0 (0.00%) | 0 (0.00%) |
| 고유 `(region, POI_ID)` 20,856 | N1 구두점 | 20,851 (99.98%) | 5 (0.02%) | 0 (0.00%) |
| 고유 `(region, POI_ID)` 20,856 | N2 괄호 포함 | 20,814 (99.80%) | 41 (0.20%) | 1 (0.00%) |
| 고유 `(region, POI_ID)` 20,856 | N4 fuzzy retrieval | 354 (1.70%) | 200 (0.96%) | 20,302 (97.34%) |

N1에서 새로 나온 observed-positive 후보 11건 중 source 주소 exact match는 1/11 (9.09%), 주소 mismatch 10/11 (90.91%), source 주소 부재 0/11이다. N2에서 추가로 생긴 58건은 exact match 9/58 (15.52%), mismatch 49/58 (84.48%), source 주소 부재 0/58이다. 고유 POI 기준으로 N1 후보 5건 중 exact match 1, mismatch 4건이고, N2 추가 37건 중 exact match 8, mismatch 29건이다. TourAPI 후보 주소 부재는 두 분모에서 모두 0건이다. 주소 exact match도 여기서는 shadow corroboration일 뿐이며 identity 승격 기준으로 사용하지 않았다.

| 겹치는 문자열 특성 tag | observed positives 50,933 | 고유 POI 20,856 |
| --- | ---: | ---: |
| `punctuation_difference_candidate` | 11 (0.02%) | 5 (0.02%) |
| `parenthetical_candidate` | 58 (0.11%) | 37 (0.18%) |
| `branch_suffix_present` | 5,958 (11.70%) | 2,343 (11.23%) |
| `facility_subpoi_suffix_present` | 838 (1.65%) | 517 (2.48%) |
| `numeric_token_present` | 2,653 (5.21%) | 1,573 (7.54%) |
| `latin_token_present` | 2,167 (4.25%) | 1,171 (5.61%) |
| `other` | 40,731 (79.97%) | 16,109 (77.24%) |

`other`는 위 문자열 특성이나 N1/N2 recovery tag가 없는 경우이며, 나머지 tag는 서로 겹칠 수 있으므로 합계를 100%로 해석하지 않는다. 권역/TL/VL 상세 count는 ignored aggregate의 `name_candidate_recovery_by_region_split_positive`와 `name_candidate_recovery_by_region_unique_source_poi`에 저장했다. 50,933건의 약 0.14%만 N2까지 exact normalized-title 후보가 생겼고, 그 중 대부분은 source 주소와 exact하게 확인되지 않았다. 따라서 punctuation/parenthetical normalization을 canonical 기준으로 바로 승격할 근거는 부족하다. 지점·시설 suffix tag도 존재 여부 진단일 뿐, 제거 후 identity를 확정하지 않는다. N4는 넓은 fuzzy 후보가 대부분에서 만들어졌다는 사실만 보이며 catalog 부재나 identity를 설명하지 않는다. 나머지 원인은 여전히 판정 불가이며, `UNMATCHED != catalog-outside`를 유지한다.

| 권역 / split | N0 exact miss | N1 recovered | N2 candidate 있는 positive | N1 address exact | N2 추가 address exact |
| --- | ---: | ---: | ---: | ---: | ---: |
| capital / TL | 6,231 | 0 (0.00%) | 3 (0.05%) | 0/0 (해당 없음) | 1/3 (33.33%) |
| capital / VL | 864 | 0 (0.00%) | 1 (0.12%) | 0/0 (해당 없음) | 0/1 (0.00%) |
| west / TL | 10,642 | 1 (0.01%) | 27 (0.25%) | 0/1 (0.00%) | 4/26 (15.38%) |
| west / VL | 1,233 | 0 (0.00%) | 4 (0.32%) | 0/0 (해당 없음) | 0/4 (0.00%) |
| east / TL | 10,111 | 2 (0.02%) | 11 (0.11%) | 0/2 (0.00%) | 3/9 (33.33%) |
| east / VL | 1,191 | 0 (0.00%) | 2 (0.17%) | 0/0 (해당 없음) | 0/2 (0.00%) |
| jeju-islands / TL | 18,476 | 8 (0.04%) | 17 (0.09%) | 1/8 (12.50%) | 1/9 (11.11%) |
| jeju-islands / VL | 2,185 | 0 (0.00%) | 4 (0.18%) | 0/0 (해당 없음) | 0/4 (0.00%) |

주소 열은 해당 단계에서 새로 후보가 생긴 positive 중 exact address match 수다. N2 candidate 있는 positive는 N1 candidate도 포함하는 누적 값이며, 전역 요약의 N2 incremental 주소 분모는 N2에서 새로 추가된 58건이다.

#### Arm D ambiguous address-resolution shadow diagnostic

같은 재실행에서 D의 **15,127 AMBIGUOUS observed positives**를 대상으로 exact-title 후보와 주소 resolution을 교차 집계했다. 이는 canonical matcher 내부 결과를 설명하는 shadow 집계이며 status나 exact match 기준을 수정하지 않는다.

```text
D AMBIGUOUS = 15,127
├─ exact-title candidate = 1: 14,698 (97.16%)
└─ exact-title candidate = 2+: 429 (2.84%)
```

분해 결과는 다음과 같다.

| exact-title 후보 수 | positives | 기존 ambiguous method | source address 없음 | 주소 mismatch | exact address가 여러 후보와 일치 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 14,698 | `exact_name_only_candidate` 14,698 | 460 (3.13%) | 14,238 (96.87%) | 0 |
| 2+ | 429 | `exact_name_only_candidate` 363, `conflicting_source_address_signals` 66 | 0 | 363 (84.62%) | 66 (15.38%) |
| 전체 | 15,127 | `exact_name_only_candidate` 15,061, `conflicting_source_address_signals` 66 | 460 (3.04%) | 14,601 (96.52%) | 66 (0.44%) |

source address는 전체에서 road only 2,203 (14.56%), lot only 3,904 (25.81%), road+lot 8,560 (56.61%), 둘 다 없음 460 (3.04%)이다. exact-title 후보의 TourAPI address는 전체 후보군에서 모두 존재했다 (15,127/15,127). 하지만 source의 road/lot 어느 값도 candidate address와 exact normalized match하지 않은 positive가 14,601 (96.52%)였다. 66건은 source address와 exact하게 일치하는 TourAPI 후보가 복수여서 기존 `conflicting_source_address_signals`로 남았다. unique exact-address candidate는 0건이다.

따라서 이 funnel에서는 exact-title 후보 1개인 모호성의 대부분이 source address mismatch 또는 source address missing으로 설명되고, 후보가 여러 개인 경우에는 66건에서 동일 exact address를 가진 복수 POI가 관찰됐다. 주소 mismatch의 원인이 표기 차이인지 실제 장소 차이인지는 판정하지 않는다. 기존 `MATCHED` 결과와 D의 4,696 MATCHED / 15,127 AMBIGUOUS / 50,933 UNMATCHED는 그대로다.

#### A1 conservative address normalization / A2 token-relation shadow diagnostic

같은 A0 15,127건과 같은 후보 집합에 두 개의 diagnostic-only 단계를 적용했다. **canonical matcher, A0 결과, MATCHED/AMBIGUOUS/UNMATCHED, 후보 포함 결과는 바꾸지 않았다.** A1은 NFKC, casefold, whitespace 정리 후 Unicode punctuation 문자를 separator로 정리한다. 행정구역 이름 변환, 도로명 alias, 숫자 변환, token 삭제는 없다. A1 exact도 identity 확정이나 `MATCHED`가 아니다.

A1 결과는 observed-positive 단위에서 다음과 같다.

| A0 exact-title 후보 수 | 분모 | A1 결과 | 정확 건수 (분모 대비 비율) |
| --- | ---: | --- | ---: |
| 1 | 14,698 | A1 normalized exact | 12 (0.08%) |
| 1 | 14,698 | 여전히 mismatch | 14,226 (96.79%) |
| 1 | 14,698 | source address 없음 | 460 (3.13%) |
| 2+ | 429 | A1으로 후보 하나만 선택 | **0 (0.00%)** |
| 2+ | 429 | A1으로 복수 후보 선택 | 66 (15.38%) |
| 2+ | 429 | A1 후보 없음 | 363 (84.62%) |

따라서 다수 title 후보 중 A1 주소 일치가 유일 후보로 좁혀진 경우는 0건이다. 단일 title 후보에서 A1 exact 12건이 추가 진단됐지만 canonical 상태는 계속 AMBIGUOUS다.

A1 이후에도 해결되지 않은 observed positives는 **15,115/15,127 (99.92%)**다. A2는 이 분모에서 source `ROAD_NM_ADDR`와 `LOTNO_ADDR` 각각을 각 TourAPI candidate address와 비교한 token-set 관계를 진단한다. 한 positive에 비교 가능한 조합이 여러 개면 가장 강한 관계 하나를 보존하고, 우선순위는 `normalized_exact` > `source_tokens_subset_of_catalog` > `catalog_tokens_subset_of_source` > `partial_overlap` > `no_meaningful_overlap`이다. 모든 source address가 비었으면 `source_address_missing`, 모든 catalog candidate address가 비었으면 `catalog_address_missing`으로 분류한다. 이 우선순위는 분석 편의를 위한 것이며 token containment/overlap은 MATCHED 판정에 사용하지 않는다.

| A2 관계 (A1 미해결 분모 15,115) | positives | rate |
| --- | ---: | ---: |
| `normalized_exact` | 66 | 0.44% |
| `source_tokens_subset_of_catalog` | 2,448 | 16.20% |
| `catalog_tokens_subset_of_source` | 966 | 6.39% |
| `partial_overlap` | 8,491 | 56.18% |
| `no_meaningful_overlap` | 2,684 | 17.76% |
| `source_address_missing` | 460 | 3.04% |
| `catalog_address_missing` | 0 | 0.00% |

unique `(region, POI_ID)` 단위에서는 D AMBIGUOUS POI가 3,927개다. exact-title 후보 1개는 3,751/3,927 (95.52%), 2+는 176/3,927 (4.48%)다. 후보 1개에서 A1 normalized exact 5 (0.13%), mismatch 3,708 (98.85%), source address 없음 38 (1.01%)이다. 후보 2+에서 A1 유일 선택은 **0**, 복수 선택 5 (2.84%), 선택 없음 171 (97.16%)이다. A1 이후 unique unresolved 3,922개에서 A2는 `normalized_exact` 5 (0.13%), source token subset 645 (16.45%), catalog token subset 295 (7.52%), partial overlap 2,232 (56.91%), no overlap 707 (18.03%), source missing 38 (0.97%), catalog missing 0이다.

권역 × TL/VL의 exact positive-weighted counts는 다음과 같다. A1 title-1 tuple의 순서는 `exact / mismatch / source-missing`, title-2+ tuple은 `unique / multiple / none`이다. A2 tuple은 A1 unresolved 분모에서 `normalized-exact / source-subset / catalog-subset / partial / no-overlap / source-missing` 순서다. 모든 행의 `catalog_address_missing`은 0이다. unique POI 상세는 동일 fixed artifact의 `address_resolution_shadow_by_region_unique_source_poi`에 있다.

| Region / split | AMBIGUOUS | title 1 / 2+ | A1 title 1 exact / mismatch / source missing | A1 title 2+ unique / multiple / none | A2 exact / source-subset / catalog-subset / partial / no-overlap / source missing |
| --- | ---: | ---: | ---: | ---: | ---: |
| capital / TL | 1,917 | 1,822 / 95 | 0 / 1,816 / 6 | 0 / 0 / 95 | 0 / 482 / 48 / 1,061 / 320 / 6 |
| capital / VL | 255 | 239 / 16 | 0 / 238 / 1 | 0 / 0 / 16 | 0 / 62 / 10 / 137 / 45 / 1 |
| west / TL | 3,090 | 2,983 / 107 | 6 / 2,957 / 20 | 0 / 10 / 97 | 10 / 322 / 90 / 2,110 / 532 / 20 |
| west / VL | 381 | 370 / 11 | 0 / 367 / 3 | 0 / 2 / 9 | 2 / 28 / 11 / 264 / 73 / 3 |
| east / TL | 3,319 | 3,239 / 80 | 0 / 3,210 / 29 | 0 / 2 / 78 | 2 / 505 / 134 / 2,168 / 481 / 29 |
| east / VL | 387 | 375 / 12 | 0 / 375 / 0 | 0 / 3 / 9 | 3 / 65 / 10 / 259 / 50 / 0 |
| jeju-islands / TL | 5,123 | 5,031 / 92 | 4 / 4,668 / 359 | 0 / 41 / 51 | 41 / 864 / 582 / 2,207 / 1,066 / 359 |
| jeju-islands / VL | 655 | 639 / 16 | 2 / 595 / 42 | 0 / 8 / 8 | 8 / 120 / 81 / 285 / 117 / 42 |

weighted 결과와 unique 결과의 차이는 반복 observed positives의 가중 때문이다. 예를 들어 A1 normalized exact는 weighted 12건이지만 unique POI는 5개다. A2의 최대 범주는 양쪽 단위에서 `partial_overlap`이며, 이는 문자열 token 일부가 겹친다는 진단일 뿐 같은 장소라는 확인이 아니다. A0 funnel, A/B/C/D/E, N0–N4는 이전 집계 artifact와 필드별 비교해 모든 기존 필드 값이 같음을 확인했다.

**식별 추정 규칙 결론:** Name N1/N2 후보 생성은 69/50,933에 그쳤고, address A1은 후보가 하나인 경우 12/14,698 normalized exact, 후보가 2+인 경우 유일 선택 0/429였다. 이 결과로 단순 문자열 정규화 실험을 종료한다. 추가 fuzzy threshold, title regex, address heuristic, token overlap 기반 MATCHED 승격은 구현하지 않는다. 다음 단계는 공식 원천-제공자 식별자 연결 정보, 검증된 좌표 호환성 또는 신뢰 가능한 외부 주소/장소 식별자가 확보될 때만 별도 검토한다.

#### Branch suffix tag boundary correction

`branch_suffix_present`는 기존 bare `점`의 임의 위치 검색 대신 문자열 끝의 `지점`, `본점`, `DT점`, 또는 terminal `점`만 인식한다. 이를 통해 문자열 중간의 `점`이 branch suffix tag를 발생시키지 않는다. exact matcher에는 이 tag가 전달되지 않는다. D exact-title miss의 branch tag는 observed-positive 기준 5,958/50,933 (11.70%), 고유 POI 기준 2,343/20,856 (11.23%)으로 다시 집계했다. 이전보다 적어진 tag 수는 boundary correction에 따른 것이며 A/B/C/D/E의 status와 candidate coverage는 변경되지 않았다.

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

### 이전 baseline 결론의 범위

이전 단일-arm 수치는 Arm A (visit row metadata + source-region identity scope)에 대한 결과다. 아래 A/B/C/D 재실험은 같은 positives와 snapshot으로 비교했으며, 최신 identity path 결정과 결론은 새 A/B/C/D 섹션을 따른다.

재현 명령은 승인된 환경에서 `RAW_ROOT`, 권역별 `*_TL`/`*_VL`, 고정 snapshot의 `TOURAPI_SNAPSHOT`을 환경 변수로 설정한 뒤 실행한다. API key는 설정하지 않고 읽지 않는다. 입력 경로나 비밀값은 로그·문서·PR에 출력하지 않는다.

```bash
python3 scripts/recommendation/analyze_poi_catalog_candidate_coverage.py --raw-root "$RAW_ROOT" --snapshot "$TOURAPI_SNAPSHOT" --output results/experiments/poi-catalog-v1/actual-data-20261018-diagnostics6 --run-id actual-data-20261018-diagnostics6 --exact-aggregates --confirm-approved --confirm-terms --confirm-poi-candidate
```

상세 `metrics.csv`와 `run_metadata.json`은 Git-ignored 결과 경로에 남아 있다. manifest에는 run/config/code fingerprints, snapshot version/hash, retrieval time, role labels, field allowlist 및 privacy flags가 있고 raw path/ID/row/coordinate/text/secret은 없다.

### POI identity source와 region scope A/B/C/D 후속 비교

2026-10-18 후속 실험은 같은 AI Hub 2023 TL/VL positive, 같은 고정 TourAPI snapshot, 같은 exact-name/address 판정 규칙으로 네 경로를 비교한다.

| Arm | Identity metadata | TourAPI identity 검색 범위 |
| --- | --- | --- |
| A | visit row | 기존 source region 제한 |
| B | `TN_POI_MASTER` | 기존 source region 제한 |
| C | visit row | 전체 snapshot |
| D | `TN_POI_MASTER` | 전체 snapshot |

`SourcePoi.region`은 dataset/historical provenance로 유지한다. Global arm에서는 이 값으로 identity 후보를 제한하지 않지만, `CandidateRequest.region`은 기존처럼 후보 eligibility hard filter로 적용한다. Master에 `POI_ID`가 없으면 `identity_source_missing`으로만 기록하고 visit metadata로 fallback하지 않으며, title candidate funnel의 분모·0건·전역 title 부재 진단에서 제외한다. 따라서 B/D는 `identity_source_available`, `identity_source_missing`, 전체 positive 분모 identity rate와 Master metadata가 있는 positive 분모 identity rate를 각각 출력한다. Title 진단의 분모는 `positives_with_identity_source`로 명시한다. `A→B`, `A→C`, `C→D`는 동일 입력을 바꾼 controlled pipeline comparison이며 엄밀한 인과효과로 해석하지 않는다. Global exact title은 진단만 수행하고 title 존재만으로 `MATCHED`를 만들지 않는다. `MATCHED` 이후 `unsupported_content_type`, `outside_request_region` 등을 별도로 센다.

고정 TourAPI snapshot은 `contentid, contenttypeid, title, addr1, lDongRegnCd, lDongSignguCd, lclsSystm1/2/3, modifiedtime` 필드로 되어 있어 `mapx/mapy`가 없다. 따라서 해당 snapshot의 exact match로 거리분포를 계산할 수 없었다. TourAPI v4.4 매뉴얼은 `mapX`를 WGS84 경도, `mapY`를 WGS84 위도로 정의하지만, AI Hub `TN_POI_MASTER.X_COORD/Y_COORD`의 CRS·축 의미를 설명하는 제공 문서는 확인되지 않았다. 당시 그 비교 arm은 `coordinates_for_identity=false`로 유지했다. **이후 아래 Issue #69 분석은 좌표가 포함된 별도 TourAPI 자료와 matched anchors로 경험적 호환성을 검증했다.** 그 결과는 anchor subset에서의 경험적 검증이며 전체 Master inventory의 공식 CRS/source contract 또는 좌표 coverage를 확립하지 않는다. 거리 검증을 재현하려면 좌표 필드를 포함한 승인 자료가 필요하다.

실험 artifact는 Git-ignored `results/experiments/poi-catalog-v1/identity-arms-20261018.json`에 저장한다. 재현 스크립트는 `scripts/recommendation/compare_poi_identity_arms.py`이며 raw rows와 identifier를 출력하지 않는다. Snapshot metadata의 policy JSON SHA-256은 현재 versioned policy와 달라 manifest에 불일치를 표시한다. 실행 시 canonical snapshot SHA-256, TourAPI provider/manual, legal-code universe, supported type set을 검증하고 현재 저장소의 versioned policy를 명시적으로 적용한다. Arm A weighted status와 candidate coverage는 기존 exact baseline과 동일함을 재현했다.

재현 명령은 기존 승인 입력의 환경 변수를 연결한다. 변수 값이나 원본 경로는 stdout/manifest에 기록하지 않는다.

```bash
python3 scripts/recommendation/compare_poi_identity_arms.py \
  --raw-root "$RAW_ROOT" \
  --snapshot "$TOURAPI_SNAPSHOT" \
  --master capital="$CAPITAL_OTHER" \
  --master west="$WEST_OTHER" \
  --master east="$EAST_OTHER" \
  --master jeju-islands="$JEJU_OTHER" \
  --output "$PWD/results/experiments/poi-catalog-v1/identity-arms-20261018.json"
```

### A/B/C/D 실제 데이터 비교 (2026-10-18)

양성 관계는 모든 arm에서 동일한 distinct `(TRAVEL_ID, POI_ID)` 집합이다. A/B는 `SourcePoi.region`의 기존 제품 권역 제한을 identity 탐색에도 적용하고, C/D는 전체 snapshot에서 탐색한다. B/D는 `TN_POI_MASTER` metadata만 사용하며 master 미존재는 `identity_source_missing`으로만 기록하고 visit row 값으로 대체하지 않았다. 각 차이는 controlled pipeline comparison이고 인과 효과로 해석하지 않는다.

| Arm | all positives | MATCHED | AMBIGUOUS | UNMATCHED | identity_source_missing | identity rate all / source-available | candidate-contained | end-to-end coverage | conditional coverage | outside candidate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 97,640 | 3,000 (3.07%) | 29,149 (29.85%) | 65,491 (67.07%) | 0 | 3.07% / 3.07% | 1,530 | 1.57% | 51.00% | 1,470 |
| B | 97,640 | 4,289 (4.39%) | 12,924 (13.24%) | 53,543 (54.84%) | 26,884 (27.53%) | 4.39% / 6.06% | 2,097 | 2.15% | 48.89% | 2,192 |
| C | 97,640 | 3,044 (3.12%) | 32,062 (32.84%) | 62,534 (64.05%) | 0 | 3.12% / 3.12% | 1,530 | 1.57% | 50.26% | 1,514 |
| D | 97,640 | 4,696 (4.81%) | 15,127 (15.49%) | 50,933 (52.16%) | 26,884 (27.53%) | 4.81% / 6.64% | 2,097 | 2.15% | 44.66% | 2,599 |

A→B는 POI Master로 바꾼 경우 MATCHED **3,000→4,289 (+1,289; 3.07%→4.39%, +1.32%p)**, A→C는 source-region hard filter 제거만으로 **3,000→3,044 (+44; 3.07%→3.12%, +0.05%p)**, C→D는 두 변경을 결합해 **3,044→4,696 (+1,652; 3.12%→4.81%, +1.69%p)**다. source-region hard filter 제거 효과는 작고, POI Master 사용 효과가 상대적으로 컸다. 이 controlled comparison은 TourAPI catalog 적합성을 평가하지 않는다. 현재 AI Hub→TourAPI bridge가 offline coverage 측정에 충분하지 않다는 위 최종 결론을 따른다. 제품 `CandidateRequest.region` hard eligibility와 `{12,14,28}` 정책은 그대로 유지한다.

#### 권역/split별 arm 비교

| 권역 / split | Arm | positives | MATCHED (rate/all positives) | AMBIGUOUS (rate/all positives) | UNMATCHED (count; rate/all positives) | identity_source_missing | candidate-contained (end-to-end) | conditional |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| capital / TL | A | 13,660 | 3 (0.02%) | 3,966 (29.03%) | 9,691 (70.94%) | 0 (0.00%) | 3 (0.02%) | 100.00% |
| capital / TL | B | 13,660 | 487 (3.57%) | 1,858 (13.60%) | 6,292 (46.06%) | 5,023 (36.77%) | 220 (1.61%) | 45.17% |
| capital / TL | C | 13,660 | 5 (0.04%) | 4,042 (29.59%) | 9,613 (70.37%) | 0 (0.00%) | 3 (0.02%) | 60.00% |
| capital / TL | D | 13,660 | 489 (3.58%) | 1,917 (14.03%) | 6,231 (45.61%) | 5,023 (36.77%) | 220 (1.61%) | 44.99% |
| capital / VL | A | 1,811 | 2 (0.11%) | 464 (25.62%) | 1,345 (74.27%) | 0 (0.00%) | 2 (0.11%) | 100.00% |
| capital / VL | B | 1,811 | 60 (3.31%) | 248 (13.69%) | 871 (48.09%) | 632 (34.90%) | 32 (1.77%) | 53.33% |
| capital / VL | C | 1,811 | 3 (0.17%) | 470 (25.95%) | 1,338 (73.88%) | 0 (0.00%) | 2 (0.11%) | 66.67% |
| capital / VL | D | 1,811 | 60 (3.31%) | 255 (14.08%) | 864 (47.71%) | 632 (34.90%) | 32 (1.77%) | 53.33% |
| west / TL | A | 19,584 | 28 (0.14%) | 6,414 (32.75%) | 13,142 (67.11%) | 0 (0.00%) | 16 (0.08%) | 57.14% |
| west / TL | B | 19,584 | 633 (3.23%) | 2,964 (15.13%) | 10,779 (55.04%) | 5,208 (26.59%) | 370 (1.89%) | 58.45% |
| west / TL | C | 19,584 | 30 (0.15%) | 6,591 (33.66%) | 12,963 (66.19%) | 0 (0.00%) | 16 (0.08%) | 53.33% |
| west / TL | D | 19,584 | 644 (3.29%) | 3,090 (15.78%) | 10,642 (54.34%) | 5,208 (26.59%) | 370 (1.89%) | 57.45% |
| west / VL | A | 2,357 | 4 (0.17%) | 652 (27.66%) | 1,701 (72.17%) | 0 (0.00%) | 2 (0.08%) | 50.00% |
| west / VL | B | 2,357 | 65 (2.76%) | 364 (15.44%) | 1,250 (53.03%) | 678 (28.77%) | 40 (1.70%) | 61.54% |
| west / VL | C | 2,357 | 4 (0.17%) | 670 (28.43%) | 1,683 (71.40%) | 0 (0.00%) | 2 (0.08%) | 50.00% |
| west / VL | D | 2,357 | 65 (2.76%) | 381 (16.16%) | 1,233 (52.31%) | 678 (28.77%) | 40 (1.70%) | 61.54% |
| east / TL | A | 20,456 | 198 (0.97%) | 8,616 (42.12%) | 11,642 (56.91%) | 0 (0.00%) | 72 (0.35%) | 36.36% |
| east / TL | B | 20,456 | 841 (4.11%) | 3,219 (15.74%) | 10,223 (49.98%) | 6,173 (30.18%) | 397 (1.94%) | 47.21% |
| east / TL | C | 20,456 | 199 (0.97%) | 8,755 (42.80%) | 11,502 (56.23%) | 0 (0.00%) | 72 (0.35%) | 36.18% |
| east / TL | D | 20,456 | 853 (4.17%) | 3,319 (16.23%) | 10,111 (49.43%) | 6,173 (30.18%) | 397 (1.94%) | 46.54% |
| east / VL | A | 2,468 | 29 (1.18%) | 756 (30.63%) | 1,683 (68.19%) | 0 (0.00%) | 8 (0.32%) | 27.59% |
| east / VL | B | 2,468 | 100 (4.05%) | 374 (15.15%) | 1,208 (48.95%) | 786 (31.85%) | 56 (2.27%) | 56.00% |
| east / VL | C | 2,468 | 29 (1.18%) | 776 (31.44%) | 1,663 (67.38%) | 0 (0.00%) | 8 (0.32%) | 27.59% |
| east / VL | D | 2,468 | 104 (4.21%) | 387 (15.68%) | 1,191 (48.26%) | 786 (31.85%) | 56 (2.27%) | 53.85% |
| jeju-islands / TL | A | 33,310 | 2,459 (7.38%) | 7,698 (23.11%) | 23,153 (69.51%) | 0 (0.00%) | 1,276 (3.83%) | 51.89% |
| jeju-islands / TL | B | 33,310 | 1,891 (5.68%) | 3,482 (10.45%) | 20,448 (61.39%) | 7,489 (22.48%) | 884 (2.65%) | 46.75% |
| jeju-islands / TL | C | 33,310 | 2,492 (7.48%) | 9,834 (29.52%) | 20,984 (63.00%) | 0 (0.00%) | 1,276 (3.83%) | 51.20% |
| jeju-islands / TL | D | 33,310 | 2,222 (6.67%) | 5,123 (15.38%) | 18,476 (55.47%) | 7,489 (22.48%) | 884 (2.65%) | 39.78% |
| jeju-islands / VL | A | 3,994 | 277 (6.94%) | 583 (14.60%) | 3,134 (78.47%) | 0 (0.00%) | 151 (3.78%) | 54.51% |
| jeju-islands / VL | B | 3,994 | 212 (5.31%) | 415 (10.39%) | 2,472 (61.89%) | 895 (22.41%) | 98 (2.45%) | 46.23% |
| jeju-islands / VL | C | 3,994 | 282 (7.06%) | 924 (23.13%) | 2,788 (69.80%) | 0 (0.00%) | 151 (3.78%) | 53.55% |
| jeju-islands / VL | D | 3,994 | 259 (6.48%) | 655 (16.40%) | 2,185 (54.71%) | 895 (22.41%) | 98 (2.45%) | 37.84% |
#### Exact-title 후보 funnel과 global title 진단

B/D의 `identity_source_missing` positives는 title funnel에서 제외한다. 분모는 A/C에서 전체 positives 97,640, B/D에서 `positives_with_identity_source` 70,756이다.

| Arm | title 후보 0 (rate/source denominator) | 후보 1 | 후보 2+ | title denominator |
| --- | ---: | ---: | ---: | ---: |
| A | 75,530 (77.36%) | 21,592 (22.11%) | 518 (0.53%) | 97,640 |
| B | 53,543 (75.67%) | 16,909 (23.90%) | 304 (0.43%) | 70,756 |
| C | 72,103 (73.85%) | 24,552 (25.15%) | 985 (1.01%) | 97,640 |
| D | 50,933 (71.98%) | 19,227 (27.17%) | 596 (0.84%) | 70,756 |

Global title 진단은 같은 권역 title 후보가 0인 경우만 해당 category count에 기록한다. category rate의 분모는 아래와 같이 모든 identity-source-available positives이며, category count 합은 same-region no-hit positives 수다.

| Arm | global exact title 없음 | 다른 권역 단일 후보 | 다른 권역 다중 후보 | positives_with_identity_source |
| --- | ---: | ---: | ---: | ---: |
| A | 72,103 (73.85%) | 3,265 (3.34%) | 162 (0.17%) | 97,640 |
| B | 50,933 (71.98%) | 2,499 (3.53%) | 111 (0.16%) | 70,756 |
| C | 72,103 (73.85%) | 3,265 (3.34%) | 162 (0.17%) | 97,640 |
| D | 50,933 (71.98%) | 2,499 (3.53%) | 111 (0.16%) | 70,756 |

B/D는 각각 26,884건을 `identity_source_missing`으로 별도 기록하고 title 후보 0이나 `global_exact_title_absent`에 넣지 않았다. `identity_resolution_rate_all`은 B 4,289/97,640 (4.39%), D 4,696/97,640 (4.81%)이고, source-available rate는 B 4,289/70,756 (6.06%), D 4,696/70,756 (6.64%)다. A/C의 source-available 분모는 전체 97,640이다. `UNMATCHED != catalog-outside`이며 catalog 부재는 여전히 **판정 불가**다.

#### Cross-region TN_POI_MASTER lookup 진단

same-region Master에 없는 ID만 네 권역 Master union에서 진단했다. metadata 동일성은 `POI_NM`, `SGG_CD`, `LOTNO_ADDR`, `ROAD_NM_ADDR`의 원문 tuple equality로 확인했다. 이 진단은 D identity resolution에 편입되지 않는다.

| 권역 / split | source POI same-region missing → absent from all | observed positive same-region missing → absent from all |
| --- | ---: | ---: |
| capital / TL | 4,203: 4,203 (100.00%) | 5,023: 5,023 (100.00%) |
| capital / VL | 592: 592 (100.00%) | 632: 632 (100.00%) |
| west / TL | 4,042: 4,042 (100.00%) | 5,208: 5,208 (100.00%) |
| west / VL | 620: 620 (100.00%) | 678: 678 (100.00%) |
| east / TL | 4,513: 4,513 (100.00%) | 6,173: 6,173 (100.00%) |
| east / VL | 720: 720 (100.00%) | 786: 786 (100.00%) |
| jeju-islands / TL | 4,692: 4,692 (100.00%) | 7,489: 7,489 (100.00%) |
| jeju-islands / VL | 726: 726 (100.00%) | 895: 895 (100.00%) |

모든 split에서 `found_in_one_other_master`, `found_in_multiple_masters_same_metadata`, `found_in_multiple_masters_conflicting_metadata`는 source POI와 positive 단위 모두 0건 (각 same-region-missing 분모 대비 0.00%)이다. TL/VL positive 합계는 same-region missing 26,884/97,640이며 전부 네 권역 Master union에도 없었다. 교차 조회가 복구하는 positive가 0건이므로 지금은 D2를 추가하지 않고, canonical D를 유지한다.

이번 follow-up에서는 기존 v4.4 fixed snapshot을 찾아 provider/manual/version/content hash metadata를 검증한 뒤 전체 comparator CLI를 다시 실행했다. API는 재호출하지 않았으며 승인된 TL/VL·Master 원본은 read-only로 사용했다. Git-ignored aggregate artifact를 full run 결과로 갱신했다.

#### Arm E: Master-first + explicit visit fallback (후속 탐색 arm)

Arm E는 canonical D를 대체하지 않는 별도 진단 경로다. `POI_ID`가 same-region `TN_POI_MASTER`에 있으면 Master signal을 사용하고, 없을 때만 visit-row signal로 fallback한다. 각 positive의 provenance를 `identity_metadata_source` (`master` / `visit_fallback`)로 집계해 artifact에 기록한다. TourAPI title/address identity search는 global snapshot을 사용하며 D와 같은 exact matching만 적용한다. Fuzzy, 좌표, 주소 유사도 matching은 추가하지 않았다.

| 비교 지표 | D: Master + global | E: Master-first + visit fallback | E−D |
| --- | ---: | ---: | ---: |
| 전체 observed positives | 97,640 | 97,640 | — |
| MATCHED | 4,696 (4.81%) | 5,195 (5.32%) | +499 |
| AMBIGUOUS | 15,127 | 20,297 | +5,170 |
| UNMATCHED | 50,933 | 72,148 | +21,215 |
| candidate-contained | 2,097 (2.15%) | 2,423 (2.48%) | +326 |
| conditional coverage | 44.66% | 46.64% | — |

D의 세 status는 Master metadata를 가진 70,756 positives를 분모로 하며, 나머지 26,884건은 `identity_source_missing`이었다. E에서는 이 26,884건이 모두 `visit_fallback`으로 처리되어 전체 status 분포가 positives 전체를 포함한다. E status rate는 MATCHED 5,195/97,640 (5.32%), AMBIGUOUS 20,297/97,640 (20.79%), UNMATCHED 72,148/97,640 (73.89%)이다. E provenance는 positive 단위 `master` 70,756건 (72.47%), `visit_fallback` 26,884건 (27.53%)이다.

Fallback subset의 exact 진단은 다음과 같다.

| 지표 | count / denominator | 비율 |
| --- | ---: | ---: |
| fallback positives | 26,884 / 26,884 | 100.00% |
| MATCHED | 499 / 26,884 | 1.86% |
| AMBIGUOUS | 5,170 / 26,884 | 19.23% |
| UNMATCHED | 21,215 / 26,884 | 78.91% |
| global exact-title 후보 0 | 22,777 / 26,884 | 84.72% |
| global exact-title 후보 1 | 3,894 / 26,884 | 14.48% |
| global exact-title 후보 2+ | 213 / 26,884 | 0.79% |
| candidate-contained | 326 / 26,884 | 1.21% |

Fallback MATCHED 499건의 eligibility는 `eligible` 326 (65.33%), `unsupported_content_type` 173 (34.67%)다. Fallback의 identity resolution은 1.86%로 낮고, 5,170건은 source signal conflict 또는 exact matching ambiguity로 남았다. E가 D 대비 identity MATCHED를 499건, candidate-contained를 326건 늘렸지만, 이 fallback 결과만으로 source metadata의 품질이나 serving suitability를 확정할 수 없으므로 **E는 연구 arm으로 유지하고 canonical identity arm은 D로 유지한다.** `UNMATCHED`/`AMBIGUOUS`는 TourAPI catalog absence를 뜻하지 않으며 `catalog-outside = 판정 불가`를 유지한다.

전체 비교와 fallback subset의 exact aggregate는 Git-ignored `results/experiments/poi-catalog-v1/identity-arms-20261018.json`에 기록했다. A/B/C/D 재계산 값은 이번에도 앞선 실행과 동일했다.

#### Master / visit shadow validation

동일 positive에 대해 same-region Master와 visit metadata를 각각 같은 global TourAPI snapshot 및 D와 동일한 exact matching rule로 평가했다. 분모는 두 metadata source가 모두 있는 70,756 positives다. 이 결과는 visit-row matching의 precision proxy이며 Arm E 499건을 canonical MATCHED로 승격하거나 독립 정답으로 취급하지 않는다.

| Master 결과 / visit 결과 | 정확 건수 | overlap 분모 대비 |
| --- | ---: | ---: |
| MATCHED / MATCHED | 1,927 | 2.72% |
| MATCHED / AMBIGUOUS | 2,712 | 3.83% |
| MATCHED / UNMATCHED | 57 | 0.08% |
| AMBIGUOUS / MATCHED | 583 | 0.82% |
| UNMATCHED / MATCHED | 35 | 0.05% |
| AMBIGUOUS / AMBIGUOUS | 14,400 | 20.35% |
| UNMATCHED / UNMATCHED | 41,118 | 58.11% |
| AMBIGUOUS / UNMATCHED | 144 | 0.20% |
| UNMATCHED / AMBIGUOUS | 9,780 | 13.82% |

두 source가 모두 MATCHED인 1,927건은 같은 `contentid` 1,927, 다른 `contentid` 0이었다. 따라서 요청한 canonical `contentid` agreement는 **1,927 / 1,927 (100.00%)**다. visit MATCHED 전체 2,545건 중 Master도 MATCHED인 비율은 1,927/2,545 (75.72%)이며, 나머지는 Master AMBIGUOUS 583건 및 Master UNMATCHED 35건이다. 이 agreement는 양쪽이 모두 exact rule로 resolve된 subset에 조건부인 proxy이지 전체 visit MATCHED의 독립 precision 추정치는 아니다.

| visit signal 구분 | overlap positives | visit MATCHED | Master·visit 모두 MATCHED | 같은 / 다른 `contentid` | agreement |
| --- | ---: | ---: | ---: | ---: | ---: |
| 단일 metadata | 58,092 | 2,545 | 1,927 | 1,927 / 0 | 1,927/1,927 (100.00%) |
| `source_signal_conflict` | 12,664 | 0 | 0 | 0 / 0 | 분모 0 (해당 없음) |

단일 metadata subset의 Master MATCHED / visit AMBIGUOUS는 2,218건, MATCHED / UNMATCHED는 57건이다. `source_signal_conflict` subset은 visit AMBIGUOUS 12,664/12,664 (100.00%)였으며, 그중 Master MATCHED 494, AMBIGUOUS 3,245, UNMATCHED 8,925건이다. conflict signal을 해결하거나 완화하지 않았다. 결과는 `master_visit_identity_shadow_validation_weighted_TL_VL` 및 권역/TL/VL breakdown으로 ignored aggregate에 저장했다.
#### Match method 및 eligibility reason

B/D match method 비율 분모는 `identity_source_available`이며 `identity_source_missing`은 match method 집계에서 제외한다. Eligibility reason 분모는 각 arm의 MATCHED다.

| Arm | method / reason | count | rate denominator | rate |
| --- | --- | ---: | ---: | ---: |
| A | `conflicting_source_address_signals` | 63 | 97,640 | 0.06% |
| A | `exact_name_only_candidate` | 14,455 | 97,640 | 14.80% |
| A | `name_address` | 3,000 | 97,640 | 3.07% |
| A | `no_exact_signal` | 65,491 | 97,640 | 67.07% |
| A | `source_signal_conflict` | 14,631 | 97,640 | 14.98% |
| A | `eligible` | 1,530 | 3,000 | 51.00% |
| A | `unsupported_content_type` | 1,470 | 3,000 | 49.00% |
| B | `conflicting_source_address_signals` | 61 | 70,756 | 0.09% |
| B | `exact_name_only_candidate` | 12,863 | 70,756 | 18.18% |
| B | `name_address` | 4,289 | 70,756 | 6.06% |
| B | `no_exact_signal` | 53,543 | 70,756 | 75.67% |
| B | `eligible` | 2,097 | 4,289 | 48.89% |
| B | `unsupported_content_type` | 2,192 | 4,289 | 51.11% |
| C | `conflicting_source_address_signals` | 63 | 97,640 | 0.06% |
| C | `exact_name_only_candidate` | 17,368 | 97,640 | 17.79% |
| C | `name_address` | 3,044 | 97,640 | 3.12% |
| C | `no_exact_signal` | 62,534 | 97,640 | 64.05% |
| C | `source_signal_conflict` | 14,631 | 97,640 | 14.98% |
| C | `eligible` | 1,530 | 3,044 | 50.26% |
| C | `outside_request_region` | 4 | 3,044 | 0.13% |
| C | `unsupported_content_type` | 1,510 | 3,044 | 49.61% |
| D | `conflicting_source_address_signals` | 66 | 70,756 | 0.09% |
| D | `exact_name_only_candidate` | 15,061 | 70,756 | 21.29% |
| D | `name_address` | 4,696 | 70,756 | 6.64% |
| D | `no_exact_signal` | 50,933 | 70,756 | 71.98% |
| D | `eligible` | 2,097 | 4,696 | 44.66% |
| D | `outside_request_region` | 173 | 4,696 | 3.68% |
| D | `unsupported_content_type` | 2,426 | 4,696 | 51.66% |

D의 global MATCHED **4,696** 중 eligible **2,097 (44.66%)**, `unsupported_content_type` **2,426 (51.66%)**, `outside_request_region` **173 (3.68%)**다. identity와 eligibility를 분리했으며 D의 unmatched/ambiguous를 catalog 부재로 해석하지 않는다.

#### POI Master와 visit metadata 일치도

분모는 권역별 합산 고유 source POI_ID이며 필드 mismatch는 master가 존재하고 안정적인 POI_ID 26,032개 기준이다. 한 POI_ID에 여러 visit row가 있으면 하나 이상의 row가 master 값과 다를 때 해당 필드를 mismatch로 센다. 지표는 중첩될 수 있다.

| 항목 | count | denominator | rate |
| --- | ---: | ---: | ---: |
| 고유 (region, POI_ID) 쌍 수 | 45,353 | — | — |
| master 없음 | 19,321 | 45,353 | 42.60% |
| master metadata 안정적으로 존재 | 26,032 | 45,353 | 57.40% |
| visit row 내부 signal 불일치 | 2,149 | 45,353 | 4.74% |
| 기존 visit conflict 중 master가 안정된 경우 | 1,629 | 2,149 | 75.80% |
| visit/master POI_NM 차이 | 3,258 | 26,032 | 12.52% |
| visit/master SGG_CD 차이 | 25,991 | 26,032 | 99.84% |
| visit/master LOTNO_ADDR 차이 | 26,032 | 26,032 | 100.00% |
| visit/master ROAD_NM_ADDR 차이 | 19,270 | 26,032 | 74.02% |

Positive-weighted `identity_source_missing`은 **26,884/97,640 (27.53%)**다. Visit row의 내부 signal 불일치는 고유 `(region, POI_ID)` 쌍 **2,149/45,353 (4.74%)**에서 관찰됐고 이 중 master 단일 metadata로 안정된 ID는 **1,629/2,149 (75.80%)**다. exact 필드 차이 비율은 의미/ontology 차이와 표기 차이를 구분하지 않는다.


**Metadata 차이 권역별 breakdown (고유 POI_ID 단위)**

| 권역 / split | visit POI_ID | master missing | master stable | visit rows inconsistent | inconsistent 중 master stable | POI_NM differs | SGG_CD differs | LOTNO_ADDR differs | ROAD_NM_ADDR differs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| capital / TL | 8,655 | 4,203 (48.56%) | 4,452 (51.44%) | 265 (3.06%) | 190 (71.70%) | 682 (15.32%) | 4,446 (99.87%) | 4,452 (100.00%) | 3,664 (82.30%) |
| capital / VL | 1,545 | 592 (38.32%) | 953 (61.68%) | 24 (1.55%) | 19 (79.17%) | 141 (14.80%) | 951 (99.79%) | 953 (100.00%) | 752 (78.91%) |
| west / TL | 9,429 | 4,042 (42.87%) | 5,387 (57.13%) | 357 (3.79%) | 277 (77.59%) | 757 (14.05%) | 5,378 (99.83%) | 5,387 (100.00%) | 4,830 (89.66%) |
| west / VL | 1,784 | 620 (34.75%) | 1,164 (65.25%) | 33 (1.85%) | 31 (93.94%) | 155 (13.32%) | 1,160 (99.66%) | 1,164 (100.00%) | 1,015 (87.20%) |
| east / TL | 10,381 | 4,513 (43.47%) | 5,868 (56.53%) | 800 (7.71%) | 631 (78.88%) | 673 (11.47%) | 5,859 (99.85%) | 5,868 (100.00%) | 5,365 (91.43%) |
| east / VL | 1,938 | 720 (37.15%) | 1,218 (62.85%) | 85 (4.39%) | 75 (88.24%) | 126 (10.34%) | 1,211 (99.43%) | 1,218 (100.00%) | 1,090 (89.49%) |
| jeju-islands / TL | 13,152 | 4,692 (35.68%) | 8,460 (64.32%) | 452 (3.44%) | 338 (74.78%) | 925 (10.93%) | 8,454 (99.93%) | 8,460 (100.00%) | 3,898 (46.08%) |
| jeju-islands / VL | 2,677 | 726 (27.12%) | 1,951 (72.88%) | 46 (1.72%) | 39 (84.78%) | 197 (10.10%) | 1,948 (99.85%) | 1,951 (100.00%) | 752 (38.54%) |

#### Issue #69를 통한 좌표 호환성 및 다단계 매칭 검증 완료

Issue #69에서 TourAPI v4.4 정규 스냅샷에 `mapx`, `mapy`, `addr2` 수집을 확장하고, Baseline D의 4,686개 확정 기준점(anchor)을 통해 AI Hub와 TourAPI 간의 좌표계(CRS) 및 거리 분포를 독립 검증했다.

검증 결과, AI Hub의 `(X_COORD, Y_COORD)`와 TourAPI `(mapx, mapy)`는 모두 대한민국 WGS84 경위도(`lon 124..132`, `lat 33..39`) 범위에 100.00% 부합하며, 두 좌표 간 하버사인 구면 거리는 Regional 기준점(4,279건) 기준 **중앙값(p50) 10.93m**, **200m 이내 93.11%**(Global Arm D 기준점 4,686건 기준 중앙값 10.93m, 200m 이내 93.45%)로 극히 정밀하게 일치했다.

이에 따라 단순 텍스트 추정을 배제하고 다음 5대 물리적 증거만을 단계적으로 결합하는 비퍼지 다단계 매칭 파이프라인(v2)을 확정했다:
1. **Stage 1: 구조화 도로명·지번 주소 키**: 건물명·층·호수·괄호 법정동을 배제한 도로명 핵심 키 `(sido, sigungu, road_name, main_no)` 및 지번 핵심 키 `(sido, sigungu, emd_ri, san_flag, main_no)` 일치 판정
2. **Stage 2: TC_SGG 시군구 일치 해소**: 4개 권역 `TC_SGG` 코드북과 주소 시도/시군구 정규화를 통해 TourAPI `(lDongRegnCd, lDongSignguCd)`와 상호 매핑하고, 시군구 내 유일 동명 후보를 결정론적으로 해소
3. **Stage 3: 검증된 좌표 근접성 해소**: 하버사인 거리 200m 이내(단일 후보 시 500m) 근접성을 기준으로 다중 후보 중 유일 후보를 안전하게 해소
4. **Stage 4: TN_VISIT_AREA_INFO 다중 신호 통합**: 방문 행의 장소명, 주소, 좌표 신호를 통합하여 `identity_source_missing` 26,884건(27.53%)을 완전 해소
5. **Stage 5: 위치 조건부 이름 정규화(Location-Gated Name Normalization)**: 구조화 주소 일치 또는 좌표 거리 200m 이내 등 물리적 위치 증거가 성립된 경우에 한해, 문장부호 정규화(`N1`), 괄호 별칭 분리(`N2`), 선행 지역명 접두어 제거, 부속시설·세부지점 접미어(`주차장`, `입구`, `매표소`, `전망대`, `케이블카`, `안내소` 등) 제거 및 초근접(<=100m) 핵심어 포함 관계를 적용



## Issue #69: 5대 비퍼지 다단계 식별자 매칭(v2) 정량 검증 결과

4개 권역(수도권, 동부권, 서부권, 제주도)의 TL/VL 전체 실제 데이터(97,640 observed positives, 45,353개 고유 (region, POI_ID) 쌍, 전역 고유 POI 41,647개)와 TourAPI v4.4 전체 스냅샷(48,589개, 적격 후보 19,051개)에 대해 산출된 정량 집계 결과는 다음과 같다.

### 1. SggCrosswalk 코드 체계 및 저장 형식 비교 (과제 1)

AI Hub 2023 여행로그와 TourAPI KorService2 v4.4(2026 현행 행정구역) 간의 시군구 법정동 코드 체계 및 저장 형식 차이를 아래와 같이 전수 대조하고 변환 규칙을 정립했다.

#### (1) 데이터 원천별 저장 형식 비교표

| 데이터 원천 | 대상 파일/테이블 | 컬럼명 | 코드 형식 (자릿수) | 예시 값 | 비고 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AI Hub 원본 메타데이터** | `TN_POI_MASTER` | `SGG_CD` | 10자리 행정표준 법정동 코드 (또는 5자리/2자리) | `1111000000`, `41110`, `36` | 앞 5자리가 `SGG_CD1 + SGG_CD2` |
| **AI Hub 방문 관측** | `TN_VISIT_AREA_INFO` | `SGG_CD` | 5자리 시군구 결합 코드 (또는 2자리) | `11110`, `41111`, `12` | 방문지 시군구 행정코드 |
| **AI Hub 코드북** | `TC_SGG` (4개 권역 공통) | `SGG_CD1`, `SGG_CD2` | 분리형: 시도 2자리 + 시군구 3자리 | `SGG_CD1="11"`, `SGG_CD2="110"` | 총 250개 시군구 코드북 |
| **TourAPI 제품 카탈로그** | KorService2 v4.4 Snapshot | `lDongRegnCd`, `lDongSignguCd` | 2자리(또는 5자리) 광역 + 3자리(또는 5자리) 시군구 | `lDongRegnCd="11"`, `lDongSignguCd="110"` | 2026년 행정구역 개편 반영 |

#### (2) 광역 행정구역 개편 및 특수 매핑 비교표

| 권역/지역 | AI Hub 2023 코드 (`c1`, `c2`) | TourAPI 2026 코드 (`lDongRegnCd`, `lDongSignguCd`) | 개편 배경 및 SggCrosswalk 매핑 규칙 |
| :--- | :--- | :--- | :--- |
| **강원도** | `42` (춘천 `42110` 등) | `51` (춘천 `51, 110` 등) | 강원특별자치도 출범 (`42 -> 51`, 하위 3자리 동일 유지) |
| **전라북도** | `45` (전주 `45110` 등) | `52` (전주 `52, 111` 등) | 전북특별자치도 출범 (`45 -> 52`, 하위 3자리 동일 유지) |
| **광주광역시** | `29` (동구 `29110`, 북구 `29170` 등) | `12` (동구 `12, 210`, 서구 `240`, 남구 `270`, 북구 `300`, 광산구 `330`) | **전남광주통합특별시 통합**: 광주 구 단위는 `210..330`으로 재부여되므로, 단순 3자리 코드 일치 사용 금지 (광주 동구 `29110`과 전남 목포 `12, 110` 오매칭 방지) |
| **전라남도** | `46` (목포 `46110`, 나주 `46170` 등) | `12` (목포 `12, 110`, 여수 `130`, 순천 `150`, 나주 `170`, 광양 `190` 등 110..870) | **전남광주통합특별시 통합**: 전남 시·군 단위는 `110..870` 유지 (`46230 광양 -> 12, 190` 등 명시적 매핑 테이블 적용) |
| **세종특별자치시** | `36` 또는 `36110` | `36110, 36110` | 단층제 특별자치시: `lDongRegnCd`와 `lDongSignguCd` 모두 `36110`으로 관리되므로 2자리/5자리 상호 호환 매핑 |
| **일반구 설치 시 (11개 시)** | 대표 코드 `xx0` (수원 `41110`, 성남 `41130`, 안양 `41170`, 안산 `41270`, 고양 `41280`, 용인 `41460`, 청주 `43110`, 천안 `44130`, 전주 `45110`, 포항 `47110`, 창원 `48120`) | 하위 일반구 `xx1..xx9` (장안구 `41, 111`, 분당구 `41, 135` 등) | 한쪽이 시 대표 코드(`c2` 끝자리 `0`)이고 다른 쪽이 하위 일반구 코드(`c2[:2]` 동일 및 끝자리 `1~9`)인 경우 상호 호환 허용 |

### 2. 단계별(Ablation & Cumulative) 매칭 성과 비교

| 단계 (Stage) | MATCHED | 매칭률 | 후보 포함 (Contained) | 후보 포함률 | identity_source_missing | Anchor 일치율 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **Stage 0 (Baseline D: 마스터 완전일치)** | 4,279 | 4.38% | 2,097 | 2.15% | 26,884 | 100.00% |
| **Stage 1 (+ 구조화 도로명/지번 주소 키)** | 8,287 | 8.49% | 4,118 | 4.22% | 26,884 | 100.00% |
| **Stage 2 (+ TC_SGG 시군구 일치 해소)** | 9,504 | 9.73% | 4,702 | 4.82% | 26,884 | 100.00% |
| **Stage 3 (+ WGS84 좌표 근접성 해소)** | 15,029 | 15.39% | 8,464 | 8.67% | 26,884 | 100.00% |
| **Stage 4 (+ 방문 행 이름·주소·좌표 통합)** | 21,319 | 21.83% | 12,157 | 12.45% | 0 | 100.00% |
| **Stage 5 (+ 위치 조건부 이름 정규화)** | **26,454** | **27.09%** | **14,933** | **15.29%** | **0** | **100.00%** |

- **Anchor 일치율**: 기존 Stage 0 MATCHED 4,279건(고유 POI 1,013개)에 대해 Stage 1~5에서 동일한 `contentid`로 식별되었는지 전수 검증한 결과, 다른 `contentid` 매핑 충돌은 **0건(0.00%)**, 일치율은 **100.00%**로 측정되었다.
- **마스터 결측 코호트 전환**: 마스터 부재 양성 26,884건 중 Stage 4에서 3,327건(12.38%, 후보 포함 1,871건 / 6.96%), Stage 5에서 4,131건(15.37%, 후보 포함 2,263건 / 8.42%)이 실제로 `MATCHED`로 전환되었으며, 신호 결측 상태(`identity_source_missing`)는 0건으로 전량 해소되었다. 나머지 22,570건(83.95%)은 현재 5단계 결정론적 증거 규칙으로 매칭되지 않은 `UNMATCHED` 상태로 유지되었다(`UNMATCHED != catalog-outside` 원칙을 엄격히 준수하며 카탈로그 부재를 단정하지 않음).

### 3. TourAPI Catalog Seed Coverage (적격 후보 19,051개 기준)

- **단계별 적격 시드 수 (커버리지)**:
  - Stage 0: 383개 (2.01%) / 전체 스냅샷 992개 (2.04%)
  - Stage 1: 646개 (3.39%) / 전체 스냅샷 1,837개 (3.78%)
  - Stage 2: 837개 (4.39%) / 전체 스냅샷 2,330개 (4.80%)
  - Stage 3: 1,356개 (7.12%) / 전체 스냅샷 3,240개 (6.67%)
  - Stage 4: 2,194개 (11.52%) / 전체 스냅샷 5,154개 (10.61%)
  - Stage 5: **2,753개 (14.45%)** / 전체 스냅샷 6,378개 (13.13%) -> Stage 0 대비 **+12.44%p** 순증
- **권역별 시드 커버리지 (Stage 5)**: 수도권 698개(13.84%), 서부권 775개(12.92%), 동부권 971개(13.45%), 제주도 309개(39.06%).
- **콘텐츠 유형별 시드 커버리지 (Stage 5)**: 관광지(12) 1,905개(15.18%), 문화시설(14) 613개(22.17%), 레포츠(28) 235개(6.30%).
- **시드 아이템별 신호 밀도**:
  - 방문 관측 수: 중앙값(p50) 2회, 평균 5.42회, p90 11회, p99 62회, 최대 205회.
  - 고유 여행 수: 중앙값(p50) 2개, 평균 5.39개, p90 11개, 최대 205개.
  - 고유 AI Hub POI ID 수: 중앙값 1개, 평균 1.09개, 최대 6개.

### 4. 거리 임계값 정합성 및 공간 마진 분석

- **Stage 2 Veto 로직 추가**: TC_SGG 시군구 일치로 유일 후보를 승격할 때 양측 유효 좌표 거리가 200m 초과하거나, 동일 도로명/지번에서 본번(main_no)이 충돌하는 경우 승격을 차단함.
- **Stage 3**: `<= 200m` 899건 매칭, `200~500m` (단일 후보 + TC_SGG 일치 필수) 57건.
- **Stage 5 엄격화**: 반경 `<= 200.0m` + 단일 후보 또는 Nearest-Neighbor Margin (`d2 - d1 >= 50.0m`)만 승격 허용. (200~500m에만 후보가 있어 배제된 관측 POI 수: 5,536개).
- **공간 마진 분포**: 단일 후보 독점 매칭 12.66%(4,142건), d2-d1>=200m 8.54%(2,796건), 100~200m 13.58%(4,444건), 50~100m 16.73%(5,473건), 50m 미만 모호성 배제 48.49%(15,866건).

### 5. 신규 승격 건(Newly Promoted) 물리 신호 사후 정합성 진단 및 층화 표본·전수 감사

- **신규 승격 건 물리 신호 사후 정합성 진단 (Post-Promotion Signal Consistency Diagnostic)**:
  - Stage 1 신규(869개): 선택=도로명/지번 exact_full 주소 키 (main_no + sub_no 일치) / 게이팅=exact_main(부번 생략) 시 단일 동명 후보 + (TC_SGG 일치 또는 거리 <= 200m) / 사후진단=좌표 근접성 및 SGG 일치. 거리 중앙값 p50=6.2m, p90=73.34m, <=200m 95.63%, SGG 일치 99.56%
  - Stage 2 신규(499개): 선택=TC_SGG 시군구 일치 / 게이팅=좌표 거리 >200m 및 본번 충돌 차단 veto / 사후진단=좌표 근접성 및 주소 본번 무충돌. 거리 중앙값 p50=8.37m, p90=84.66m, <=200m 100.00%, SGG 일치 100.00%
  - Stage 3 신규(956개): 선택=WGS84 좌표 근접성(<=200m) / 게이팅=200~500m 구간 TC_SGG 필수 일치 / 사후진단=TC_SGG 일치 및 주소 본번 무충돌. 거리 중앙값 p50=25.72m, p90=154.40m, <=200m 94.04%, SGG 일치 73.33%
  - Stage 4 신규(2,031개): 선택=방문 행 exact_full 주소 키 또는 WGS84 좌표 거리 <= 200m / 게이팅=exact_main 시 단일 후보+(TC_SGG 일치 또는 거리<=200m), 거리 시 단일 후보 또는 마진(d2-d1>=50m) / 사후진단=좌표 근접성 및 SGG 일치. 거리 중앙값 p50=11.07m, p90=113.29m, <=200m 96.60%, SGG 일치 96.59%
  - Stage 5 신규(1,514개): 선택=이름 정규화 / 지점명 분리 / 게이팅=반경 <=200m + 최근접 마진 >=50m / 사후진단=좌표 근접성 및 SGG 일치. 거리 중앙값 p50=12.15m, p90=77.67m, <=200m 99.08%, SGG 일치 98.48%
- **결정론적 비례 층화 100건 표본 감사(seed=42) 및 전수 감사 (Stratified Sample & Population Audit)**:
  동일 도로명/법정동에서 본번이 상이한 경우에만 주소 본번 불일치로 집계하여 정밀도를 평가했다. 4개 권역 비례 층화 100건 표본 감사와 전수 감사에서 산출된 **다중 물리 증거 무충돌률 (Multi-Evidence Non-Conflict Rate)**은 다음과 같다:
  - Stage 1: **표본 94.00%** (수32/서19/동38/제11, 결함 0/0/6) / **전수 95.17%** (869개, 결함 2/2/38)
  - Stage 2: **표본 97.00%** (수11/서49/동34/제6, 결함 3/0/0) / **전수 97.80%** (499개, 결함 11/0/0)
  - Stage 3: **표본 85.00%** (수18/서33/동35/제14, 결함 3/4/9) / **전수 84.94%** (956개, 결함 55/36/57)
  - Stage 4: **표본 94.00%** (수31/서27/동33/제9, 결함 3/1/2) / **전수 93.70%** (2,031개, 결함 45/21/69)
  - Stage 5: **표본 98.00%** (수31/서24/동31/제14, 결함 2/0/0) / **전수 96.24%** (1,514개, 결함 36/8/14)

### 6. 독립(Non-short-circuited) 규칙별 Holdout Anchor 일치율 검증 (1,013개 고유 POI 대상)

| 평가 규칙 | 판정 POI 수 (재현율) | 동일 contentid 일치 | 충돌 건수 | Anchor 일치율 (Agreement Rate) |
| :--- | :---: | :---: | :---: | :---: |
| **구조화 주소 키 단독** | 372개 (36.72%) | 372개 | 0개 | **100.00%** |
| **TC_SGG 시군구 일치 단독** | 539개 (53.21%) | 539개 | 0개 | **100.00%** |
| **좌표 근접성(<=200m) 단독** | 967개 (95.46%) | 967개 | 0개 | **100.00%** |
| **방문 행 신호 단독** | 361개 (35.64%) | 361개 | 0개 | **100.00%** |
| **위치 조건부 이름 정규화 단독** | 973개 (95.85%) | 971개 | 2개 | **99.79%** |

### 7. 관광 대상 코호트 분리 분석 (Stage 5 기준)

| 방문지 유형 코드 | 의미 | 관측 수 | MATCHED | 매칭률 | 후보 포함 | 후보 포함률 |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| `1` | **자연관광지** | 11,029 | 5,375 | **48.74%** | 5,342 | **48.44%** |
| `2` | **역사/유적/종교** | 6,325 | 3,178 | **50.25%** | 3,144 | **49.71%** |
| `3` | **문화/예술** | 3,768 | 1,892 | **50.21%** | 1,810 | **48.04%** |
| `13` | **휴양림/수목원/공원** | 3,266 | 1,355 | **41.49%** | 1,238 | **37.91%** |
| `6` | **테마파크/놀이공원** | 2,002 | 800 | **39.96%** | 764 | **38.16%** |
| `7` | **체험/학습/연구시설** | 2,684 | 955 | **35.58%** | 932 | **34.72%** |
| `8` | **전시/관람시설** | 696 | 222 | **31.90%** | 178 | **25.57%** |
| `5` | **레저/스포츠관련시설** | 1,193 | 312 | **26.15%** | 296 | **24.81%** |
| `12` | **축제/행사** | 1,732 | 179 | **10.33%** | 122 | **7.04%** |
| `4` | 상업지구/거리 | 9,521 | 3,264 | 34.28% | 551 | 5.79% |
| `11` | 음식점/카페 | 32,723 | 6,731 | 20.57% | 129 | 0.39% |
| `10` | 숙박시설 | 4,164 | 783 | 18.80% | 74 | 1.78% |
| `24` | 기타교통시설 | 6,618 | 1,090 | 16.47% | 198 | 2.99% |
| `9` | 쇼핑몰/시장/상점 | 10,131 | 308 | 3.04% | 151 | 1.49% |
| `22` | 고속도로휴게소 | 1,059 | 3 | 0.28% | 1 | 0.09% |

- 순수 관광 대상 코호트에서 35~50%의 실효 매칭률을 달성했으며, 식음료(32,723건) 및 쇼핑(10,131건)은 추천 지원 대상({12, 14, 28})이 아니므로 카탈로그 후보 집합에서 거의 대부분 필터링/배제됨.

### 8. 확인된 사실, 해석, 결정, 미결정 사항

#### 확인된 사실 (Facts)
- TourAPI v4.4 스냅샷 어댑터 및 수집기에 `mapx`, `mapy`, `addr2`가 성공적으로 통합되어 48,589개 카탈로그 아이템 전체가 무결하게 수집됨.
- Baseline D 확정 기준점(4,279건, 고유 POI 1,013개)을 통해 AI Hub와 TourAPI 좌표계가 동일 WGS84 경위도이며 거리 중앙값이 10.93m, 200m 이내 일치율이 93% 이상임을 독립 확인.
- Stage 0의 단락 없는 독립 규칙 검증에서 구조화 주소, 시군구 매핑, 좌표 근접성, 방문 행 신호 모두 일치율 100.00%, 위치 조건부 이름 정규화 99.79%를 기록함.
- `TN_VISIT_AREA_INFO` 통합을 통해 마스터 부재 양성 26,884건의 신호 결측을 0건으로 해소하고, 이 중 4,131건(15.37%)을 최종 `MATCHED`로 전환함.
- TourAPI 적격 후보 19,051개 중 2,753개(14.45%)에 AI Hub 방문 이력 시드가 부여됨 (Obs 중앙값 2회, 평균 5.42회).

#### 해석 (Inferences)
- 전체 관측 양성 대비 후보 포함률(15.29%)이 20% 미만으로 관측되는 근본 원인은 식별자 매칭 파이프라인의 실패가 아니라, 데이터셋의 50% 이상이 식음료점(33.5%) 및 상점·교통시설로 구성되어 있기 때문임.
- 실제 서비스가 타깃팅하는 순수 관광 목적지 코호트에 한정하면 35~50%의 높은 매칭률과 후보 포함률을 나타내므로, 서비스 초기 콜드스타트 브리지로서 실효성이 충분히 검증됨.

#### 결정 (Decisions)
- 서비스 초기 시스템 콜드스타트 브리지로 Stage 5 다단계 매칭 파이프라인을 정식 채택함.
- 물리적 위치 증거(구조화 주소 일치, 반경 200m 이내 좌표 일치 + 최근접 50m 마진, 동일 시군구 유일 후보)가 없는 단순 텍스트 유사도(fuzzy threshold) 단독 승격은 계속해서 엄격히 금지함.

#### 미결정 / 추가 검증 (Unresolved)
- 향후 카탈로그 정책 v2에서 음식점(`39`) 및 쇼핑시설(`38`)을 추천 지원 대상으로 포함할지 여부는 비즈니스 카테고리 기획 및 서빙 인덱스 용량 분석을 거쳐 별도 Issue로 검토함.


## Issue #82: 수도권 TL inner-validation positive 후보 누락 진단

**결론: D — 선택한 로컬 POI Master에서 실제 후보 부재가 확인됐고, 그 원인은 미확정이다.** 이번 진단은 수도권 TL inner-validation의 관측 양성과 같은 수도권 `Other` 역할 Master 사이의 키 포함 여부만 다룬다. 선행 기록의 `883/638/245`는 `(TRAVEL_ID, POI_ID)` 쌍 수다. 고유 `POI_ID` 수는 별도로 계산했다.

### Issue #82 candidate geography correction

`CAPITAL_TL` / `CAPITAL_OTHER`는 입력 출처와 관측 코호트의 역할 binding이다. 이 값만으로 POI의 지리적 수도권을 결정하지 않는다. Runner는 #81의 `canonical_admin_sido_code`와 `load_poi_catalog_policy()`가 읽는 versioned `product_region_to_ldong_regn_cd` 단일 정책으로 ProductRegion을 판정한다. 수도권 후보에는 위치가 resolved이고 canonical SIDO code가 해당 정책의 `capital` code 집합에 속하는 Master item만 포함한다. Unresolved 위치와 다른 ProductRegion은 candidate inventory에서 제외한다.

Validation positive는 candidate filter로 제거하지 않는다. 평가 ground truth에 모두 남기고, privacy-safe 집계에서 candidate coverage, 원본 Master 부재, geography unresolved, duplicate-key 제외, 다른 ProductRegion을 구분한다. 이 offline ranking 후보 범위는 TourAPI serving eligibility나 POI identity를 정하지 않는다.

Corrected 수도권 run은 Master 7,442,866개 중 resolved policy-mapped candidate 3,052,797개를 포함했다. SIDO code 11/28/41 candidate count는 1,158,806 / 338,281 / 1,555,710이며, geography unresolved 60,874개 (0.8179%)와 resolved-outside 4,329,195개는 제외했다. Inner-validation positives는 432 query/883 pairs 모두 ground truth에 남겼고 345 query/568 pairs가 eligible candidate와 교차했다. Runner의 full 432-query cached-item profile은 959.962초 scoring을 측정했다. Source-package region은 provenance로만 쓰였으며 ProductRegion eligibility와 분리됐다.

Scorer optimization은 eligible candidate universe 밖으로 나가지 않는다. 131,072행 bounded frame과 static item-side shallow view cache는 이미 준비된 catalog feature values를 재사용하며 query-context만 query별로 broadcast한다. I2/I3/I4 값·정의, train/validation leakage 경계, positive ground truth, metric implementation, score tie-break를 변경하지 않는다. Cached-vs-uncached corrected geography full runs는 432 queries에서 metric parity가 exact였다. PR #88/#89는 source-tagged full-Master scope였으므로 그 후보 수·metric·runtime과 corrected result 사이의 actual speedup/parity를 주장하지 않는다. Detailed filter counts와 profiler 결과는 CatBoost ranking protocol을 따른다.

아래 195-ID / 245-pair 결과는 이전 PR #88 runner가 사용한 전체 unique Master key 기준 exact-key 부재 기록이다. 해당 known limitation의 원인을 다시 조사하지 않는다. 이전 #88/#89의 전체 후보 수·metric·runtime은 source package region을 후보 geography로 잘못 쓴 run의 역사 기록으로 남기며, corrected ProductRegion baseline과 직접 비교하거나 search budget 단가로 사용하지 않는다. Corrected full TL rerun과 candidate-scope aggregate는 ranking protocol에 기록했다.

### 조사 순서

#### 1. 입력 출처와 release

- 공식 [AI Hub 수도권 데이터셋 #71776](https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71776)은 `TN_VISIT_AREA_INFO`를 여행 로그 표로, `TN_POI_MASTER`를 `Other` 역할의 POI Master 1 set으로 설명한다. 페이지 변경 이력의 최신 표시는 1.2 (2024-12-04)다.
- 공식 [AI Hub 데이터 구축·활용 가이드](https://aihub.or.kr/file/down.do?cnstcPrcuseFileSn=22340&dataSetSn=71776&fileSn=22340)는 `TN_POI_MASTER`가 국토지리정보원(NGII)의 전국 POI 자료를 바탕으로 하며, 2021년에 최초 수집한 뒤 갱신했고, TourAPI를 이용해 보강·중복 제거했다고 설명한다. 이는 시점에 따른 정적 카탈로그 coverage 차이를 설명할 수 있는 맥락이지만, 이번 누락 195개 ID의 원인으로 입증된 것은 아니다.
- 사용자가 지정한 TL 및 Other 역할 바인딩을 적용했다. 공식 비다운로드 파일 목록에서 두 바인딩에 해당하는 filekey가 모두 같은 dataset 71776 목록에 있는 것을 확인했다. 구체 filekey와 로컬 경로는 기록하지 않는다.
- **미확인:** 로컬 사본의 build/release provenance는 공식 버전 이력에 연결되지 않았다. 현재 입력에서 version mismatch가 관측된 것은 아니며, 이 provenance 미확인은 이번 exact-key 비교의 blocker가 아니다. 공식 페이지의 1.2 표시는 로컬 사본의 취득 버전을 증명하지 않는다.

#### 2. 원본 Master와 runner 후보 비교

`A_ID`는 inner-validation positive의 고유 POI ID 집합, `B_ID`는 선택한 원본 Master의 비공백 `POI_ID`를 trim한 exact key 집합, `C_ID`는 PR #88 runner의 같은 권역 후보 ID 집합이다. 별도로 `A_pair`는 고유한 양성 `(TRAVEL_ID, POI_ID)` 쌍 집합이다. 아래 표는 ID 집합 연산과 pair-level membership을 분리한다.

- `|B_ID| = 7,442,866`, `|C_ID| = 7,442,866`.

| ID 집합 연산 | 고유 POI ID 수 |
| --- | ---: |
| `A_ID` | 610 |
| `A_ID ∩ B_ID` | 415 |
| `A_ID − B_ID` | 195 |
| `A_ID ∩ C_ID` | 415 |
| `A_ID − C_ID` | 195 |
| `(A_ID ∩ B_ID) − C_ID` | 0 |

| Pair-level membership | 양성 쌍 수 |
| --- | ---: |
| `A_pair` | 883 |
| `A_pair` 중 `POI_ID ∈ B_ID` | 638 |
| `A_pair` 중 `POI_ID ∉ B_ID` | 245 |
| `A_pair` 중 `POI_ID ∈ C_ID` | 638 |
| `A_pair` 중 `POI_ID ∉ C_ID` | 245 |
| `A_pair` 중 `POI_ID ∈ B_ID` 이고 `POI_ID ∉ C_ID` | 0 |

따라서 이전에 보고한 누락 245는 서로 다른 POI 수가 아니라 양성 trip–POI 쌍 수다. `A_ID − B_ID`에 속하는 195개 고유 positive ID는 245개 `A_pair`에 나타난다. 원본 Master에 exact key가 있던 양성은 runner 후보에서도 모두 유지됐다.

#### Inner-train 및 inner-validation coverage

전담 데이터 분석의 descriptive aggregate는 deterministic traveler-group split(seed 20261025, validation fraction 20%)에서 같은 trip-owner/query 구성, tourism-core positive 정의, unique `(TRAVEL_ID, POI_ID)` 쌍, trimmed exact Master membership을 사용했다.

| Split | 양성 쌍 | Master 후보에 포함 | Master 밖 | 양성 query | 후보 positive가 있는 query | 후보 positive가 없는 query |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Inner-train | 3,542 | 2,560 | 982 | 1,740 | 1,483 | 257 |
| Inner-validation smoke | 883 | 638 | 245 | 432 | 370 | 62 |

runner의 `_make_frame`은 관측 positive를 trip별로 모은 뒤 각 trip의 positive ID를 후보 inventory와 교차시키며, 후보 positive가 하나도 없는 trip은 training frame에 넣지 않는다. 그 결과 inner-train의 후보 positive가 있는 1,483개 query가 runner의 1,483개 training group이 되고, 후보 positive가 없는 257개 query는 training frame에 포함되지 않는다. 검증에서는 ground truth를 전체 inner-validation positive로 유지하므로 후보 positive가 없는 62개 query도 end-to-end 평가에서 miss로 남는다.

이 집계는 이 split 및 smoke cohort 안의 candidate-coverage 관측이다. Train과 validation 양쪽에서 Master 밖 positive가 확인됐다는 사실은 catalog coverage가 validation에만 국한된 문제가 아님을 보여주지만, 원인·모델 품질·일반화 성능을 입증하지 않는다. Covered-query만의 결과가 산출되더라도 전체 end-to-end 평가를 대체하지 않는 보조 진단이다.

#### 3. 단순 문자열 표현 차이

다음 변환은 `A_ID − B_ID`에 속하는 누락 positive ID에만 각각 독립 적용했다. 회복 수는 `고유 positive POI_ID / 해당 ID를 포함한 positive pair` 순서다. 충돌 그룹은 여러 원본 문자열이 같은 변환 key로 합쳐지는 경우다.

| 진단 | 회복된 ID / 쌍 | 충돌 그룹 |
| --- | ---: | ---: |
| 원문 문자열 exact | 0 / 0 | 0 |
| trim | 0 / 0 | 0 |
| Unicode NFC | 0 / 0 | 0 |
| Unicode NFKC | 0 / 0 | 0 |
| ASCII 대소문자 통일 | 0 / 0 | 0 |
| 숫자 문자열의 선행 0 제거 | 0 / 0 | 0 |

이 변환들로 설명되는 누락은 없다. ID 의미의 동등성을 보장하지 않는 정규화 규칙을 후보 계약에 추가할 근거도 없다.

#### 4. CSV 파싱과 dtype 변환

- [runner](../../scripts/recommendation/run_catboost_tl_smoke.py)는 `utf-8-sig`와 `csv.reader`로 선택 열을 읽어 문자열을 유지한다. pandas dtype 추론이나 숫자형 ID 변환은 사용하지 않는다. 후보 키 생성의 `_clean_str`은 문자열 trim만 한다.
- 이번 읽기에서 필요한 헤더가 확인됐고 엄격한 UTF-8 파싱 오류는 0건이었다. 입력 파일의 UTF-8 BOM은 없었으며, reader가 반환한 POI 값은 문자열이었다.
- `A_ID − B_ID`에 속하는 누락 positive ID와 `A_pair` 중 그 ID를 포함한 쌍에서 reader 값이 `_clean_str`로 바뀐 항목은 0 ID / 0쌍이고, 과학적 표기법 형태는 0개였다. 따라서 trim, null 변환, dtype 추론, BOM 또는 인코딩이 이 누락을 만들었다는 증거는 없다.
- 유효 방문 이벤트 중 빈 Visit `POI_ID` 6,710행은 positive를 만들 때 제외됐다. 이는 비어 있지 않은 195개 누락 positive ID의 설명이 아니다.

#### 5. Master 중복 및 이전 runner 필터의 범위

- 선택한 Master는 7,442,866행이며 비공백 ID도 7,442,866개다. 빈 Master ID 0개, 중복 ID 0개였고 duplicate policy로 제외된 positive ID/쌍도 0/0이다.
- 이 값은 이전 PR #88 runner의 source-region-tagged 후보 범위에 대한 기록이다. 그 runner는 canonical geography filter를 적용하지 않았으므로 이 결과를 현재 candidate filter의 제외 집계로 해석하지 않는다. Corrected runner는 canonical location unresolved와 정책 밖 geography를 candidate에서 제외하며, actual corrected filter 집계는 Issue #82 protocol에 기록했다.

#### 6. 선택한 로컬 Master에서 확인된 부재

1–5단계에서 `A_ID − B_ID`에 해당하는 195개 고유 positive ID와 `A_pair` 중 그 ID를 포함하는 245개 positive pair를 설명하는 문자열·파싱·중복·필터 원인은 확인되지 않았다. 이 값들은 **이번 smoke가 사용한 로컬 Master 사본에서의 exact-key 부재**로 확정한다. version mismatch는 관측되지 않았지만, 로컬 취득 release provenance도 검증되지 않았으므로 해당 release의 동일성은 미확정이다. 이는 현재 부재 결과를 설명하거나 무효화하지 않으며, 결과를 다른 release에 일반화하지 않는 범위 한정이다.

#### 7. Visit ↔ Master ID 의미

[수도권 schema 요약](../data/aihub-71776-capital-schema.md)에 따르면 Visit `POI_ID`와 Master `POI_ID`는 모두 `varchar(255)`이고 설명은 `POI ID`다. schema의 Visit `필수 여부 N`은 해당 필드가 필수가 아니라는 뜻이며, SQL 열의 NULL 허용 여부 자체를 명시하지 않는다. Master의 `필수 여부 Y`는 해당 schema에서 필수로 표시한다는 뜻이다.

공식 설명은 두 `POI_ID`의 생성 주체, Visit `POI_ID`가 참조하는 테이블, Master가 대표하는 정확한 모집단을 명시하지 않는다. 두 열 사이의 PK/FK 관계나 동일 namespace 보장도 선언하지 않는다. 따라서 문서상 동일성이 보장되지 않는다는 점은 확인되지만, 이는 서로 다른 ID 체계라는 증거가 아니다.

#### 8. release provenance 및 정적 카탈로그 맥락

공식 현재 목록에는 두 역할 입력이 dataset 71776의 filekey로 나타나고 페이지 버전 이력은 1.2를 표시한다. 다만 로컬 취득본을 해당 release와 연결하는 기록은 검증되지 않았다. **현재 version mismatch가 관측된 것은 아니며, 누락 원인으로 채택하지 않는다.** 위 AI Hub 구축 가이드의 수집·갱신 이력은 정적 카탈로그와 방문 관측의 coverage 차이에 대한 가능한 맥락일 뿐, 이번 195개 고유 ID의 원인 증거가 아니다.

### 결과 분류

#### 확인된 사실

- inner-validation 양성은 883개 trip–POI 쌍과 610개 고유 POI ID다.
- 원본 Master `B_ID`와 이전 PR #88 runner 후보 `C_ID`는 각각 7,442,866개다. `A_ID − B_ID`는 195개 고유 ID이며, `A_pair`에서 그 ID를 포함하는 쌍은 245개다. 이는 현재 geography-scoped candidate size나 coverage가 아니다.
- 432개 evaluation query 중 370개에는 후보 positive가 있었고 62개에는 없었다. 공식 end-to-end ranking 지표에서는 62개 query를 miss로 유지한다.
- 문자열 변환 회복, duplicate, parser/dtype 및 후보 필터에 의한 설명은 0건이다.
- 공식 schema는 ID 열 타입/필수 여부를 정의하지만 Visit ↔ Master 동일 namespace를 보장하지 않는다.

#### 해석

현재 증거는 관측된 positive ID가 선택한 로컬 static Master candidate inventory에 없다는 데까지 뒷받침한다. 2021년 최초 수집 후 갱신된 별도 static catalog라는 공식 설명은 시점·coverage 차이를 가능한 맥락으로 제시하지만, 제품 전체에서 POI Master가 불완전하다거나 Visit과 Master가 다른 namespace라는 주장, 또는 이번 195개 ID의 원인을 입증하지 않는다. 370개 covered-query 결과가 따로 산출되더라도 공식 end-to-end 지표를 대체할 수 없으며, 보조 진단으로만 볼 수 있다.

#### 기각된 가설

- 이 실행의 195개 누락 ID를 trim, Unicode, ASCII case 또는 leading-zero 변환으로 회복할 수 있다는 설명.
- 빈/중복 Master key, admin/category feature 결측, same-region 또는 다른 runner filter가 누락을 만들었다는 설명.
- CSV dtype 수치 변환, BOM, UTF-8 오류, 과학적 표기법이 누락을 만들었다는 설명.

#### 남은 가설 및 후속 확인

- 로컬로 취득한 TL과 Master 사본의 정확한 build/release 동일성은 미확인이다. 현재 version mismatch는 관측되지 않았고, 공식 가이드의 catalog history는 가능한 맥락이지 이 누락 원인의 입증이 아니다.
- 공식 schema는 Visit ID와 Master ID의 동일성을 보장하지 않지만, 서로 다른 namespace라고 선언하지도 않는다. 원인 판별에는 명시적 contract 또는 승인된 crosswalk가 필요하다.
- Inner-train aggregate는 위의 split-specific candidate coverage를 설명하며 root cause를 결정하지 않는다. AI Hub build/release provenance와 ID contract 또는 승인된 crosswalk가 확보되면 원인에 관한 별도 근거로 검토할 수 있다.

#### 결정

최종 분류는 **D — 선택한 로컬 Master에서 실제 부재 확인, 근본 원인 미확정**이다. 후보 계약은 trimmed exact string으로 유지한다. 외부 NGII 자료를 후보에 union하지 않으며, fuzzy identity resolution, 임의 ID 정규화, Visit 기반 Master feature 보강, positive 평가 제외는 적용하지 않는다. 62개 all-zero evaluation query도 end-to-end ranking 지표에서 miss로 남긴다. Covered-query 지표는 보조 진단에만 사용할 수 있다.

#### 실행 참고

이 집계는 Issue #80의 split/positive helper (`dev` base `ad0f78e5dfe471228b81c4576de575c9c91e9e27`)와 PR #88 runner 후보 규칙(문서 수정 전 head `2a1703484bce519e34ad96016c94d7990fbf43f4`)을 기준으로 다시 계산했다. 집계 처리 시간은 84.33초, peak RSS는 750 MiB였다. VL은 열지 않았다.


## Synthetic validation and use

Run `python3 -m unittest discover -s tests -p 'test_poi_catalog_candidate_contract.py' -v`, plus the TourAPI snapshot adapter and experiment-design audit test modules. Tests cover deterministic exact-signal matching, ambiguity, conflict handling, coordinate exclusion, fail-closed eligibility, normalized code handling, independent request-region coverage, proxy rejection from product coverage, explicit CSV field maps, and domain-review checks. The adapter also includes a credential-safe read-only collector; the collection CLI persists only under ignored `results/`. `derive_proxy_requests_from_observations` returns a distinct `HistoricalRequestProxy` for historical-feasibility analysis only, requires one explicit region per request, and does not infer district selection. Product candidate coverage uses independently supplied `CandidateRequest` contexts. The candidate eligibility function must not receive observed category or post-event feedback.

Follow-up context-aware ranking work must use a versioned product catalog and this candidate contract, keep observed positives and unknowns distinct, and compare ranking metrics only within the same candidate definition.
