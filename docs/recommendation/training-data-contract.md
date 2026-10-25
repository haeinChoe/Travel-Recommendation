# 추천 학습 데이터 구성·포함 기준 및 Feature/Label 계약

- **관련 Issue:** [#17](https://github.com/haeinChoe/Travel-Recommendation/issues/17), [#45](https://github.com/haeinChoe/Travel-Recommendation/issues/45), [#69](https://github.com/haeinChoe/Travel-Recommendation/issues/69), [#71](https://github.com/haeinChoe/Travel-Recommendation/issues/71)
- **현재 상태:** 4개 권역(수도권·서부권·동부권·제주도 및 도서지역) 실제 데이터 코호트 감사 및 `TC_CODEB`(`cd_a = 'VIS'`) 공식 코드북 검증 완료 (`issue71-training-contract-20261020T1550Z`)

- **TL inner split (Issue #80):** `TRAVELER_ID` 단위 결정론적 분할과 privacy-safe 분포 감사 CLI를 추가했다. 실제 4개 권역 분포는 이번 실행 환경에서 읽지 않았으므로 traveler-trip 수치와 실증 결론은 아직 없다. I3 재계산은 inner-train TL interaction만 사용하고, I4는 inner-train 방문 이벤트 입력이 없으면 fail-closed한다.

> 이 문서는 코호트·라벨의 의미와 승인된 분석 집계를 설명한다. 실제 세 Parquet 출력 이름, TL/VL→`train`/`validation` 변환, 모든 출력 컬럼의 null·타입·역할 규칙은 [표준 학습 데이터셋 스키마](training-dataset-schema.md)를 기준으로 한다. 여기서 언급하는 대문자 AI Hub 컬럼은 원천 필드 이름이다.

## 한눈에 보기

### 이 문서가 답하려는 질문

2023년 AI Hub 국내 여행로그 데이터를 사용하여 추천 모델을 학습할 때 **어떤 방문 관측치를 학습 대상(코호트)에 포함·배제할지**, **조인·집계·후보 식별용 구분자(`POI_ID`, `contentid`)와 기계학습 모델의 입력 특성(feature) 경계를 어떻게 분리할지**, 그리고 **AI Hub로 학습한 모델을 향후 미매칭(unseen) TourAPI 후보 POI 점수화로 연결하기 위해 어떤 공통 특성 공간 후보와 미해결 선행 과제가 있는지**를 확정한다.

### 한눈에 보는 결론

- **TourAPI 식별자 매칭 상태로부터의 완전한 독립**: 학습 데이터의 관측치 포함 자격(eligibility)은 TourAPI 식별자 매칭 결과(`MATCHED`, `AMBIGUOUS`, `UNMATCHED`, `identity_source_missing`)에 의존하지 않는다. 추천 모델은 개별 `POI_ID`나 `contentid`를 암기(ID 임베딩)하는 것이 아니라 **여행/요청 문맥(context) 특성과 아이템 속성(권역, 행정구역, 관광 분류, 인기도) 간의 관계**를 학습하도록 설계한다. 따라서 AI Hub의 미매칭(`UNMATCHED`) 방문 기록도 유효한 관광 속성을 갖추고 있다면 100% 정상 학습 데이터로 사용한다.
- **3단계 관측 단위(observation grain) 확정**:
  - **방문 이벤트 단위(`visit_event_grain`: `(region, TRAVEL_ID, VISIT_AREA_ID)`)**: 원시 방문 행(총 **140,555건**, TL 125,174건 / VL 15,381건). 여행 내 반복 방문과 방문별 사후 피드백(`DGSTFN`, `REVISIT_INTENTION`, `RCMDTN_INTENTION`)을 보존한다.
  - **여행-POI 상호작용 단위(`trip_poi_grain`: `(region, TRAVEL_ID, POI_ID)`)**: 비어 있지 않은 `POI_ID` 기준으로 동일 여행 내 반복 방문(8,832쌍, 추가 이벤트 11,231건)을 1회 이진 관측 양성(`observed_positive = 1`)으로 중복 제거한 순위 학습 기본 단위(총 **97,640건**, TL 87,010건 / VL 10,630건).
  - **여행/요청 단위(`trip_request_grain`: `(region, TRAVELER_ID, TRAVEL_ID)`)**: 문맥 특성 결합 및 학습/검증 분할 무결성 단위(총 **11,520건**, TL 10,240건 / VL 1,280건, 전 권역 TL/VL `TRAVEL_ID` 중복 **0건**).
- **2단계 코호트 분리(구조적 유효성 + `TC_CODEB` 검증 기반 순수 관광 코호트)**:
  - 4개 권역 8개 분할의 공식 코드북 `TC_CODEB`(`cd_a = 'VIS'`, 총 17개 코드, 권역 간 불일치 0건)를 전수 대조한 결과, 전체 유효 방문 이벤트 140,555건 중 식당/카페(`11`: 25.51%), 집(`21`: 15.07%), 역·터미널·휴게소(`9`: 10.11%), 숙소(`24`: 9.38%), 상업지구(`4`: 7.56%) 등 비관광/일상 경유지가 **74.07%(104,112건)**를 차지한다.
  - 관광지 추천 모델의 기본 양성 타깃은 `VISIT_AREA_TYPE_CD` 기준 **순수 관광 코호트(`tourism_core_cohort`: `{"1", "2", "3", "5", "6", "7", "8", "12", "13"}`)**인 **32,893건**(TL 29,307건 / VL 3,586건, 방문 이벤트 기준 36,443건)으로 분리하되, 전체 유효 방문(`all_valid_visits`) 집계를 항상 함께 보고하여 코호트 선택에 따른 분모 변화를 투명하게 통제한다. (※ `VIS=12`는 `TC_CODEB` 원문 명칭이 `'기타'`이므로 후속 실험에서 포함/제외 민감도 점검 대상으로 함께 기록한다.)
- **순수 관광 코호트 분리 시 VL 아이템 콜드 스타트 완화 확인**: 전체 방문(`all_valid_visits`)에서는 VL 관측 양성의 **35.99%**(3,826/10,630건, 수도권 51.68%)가 TL 미등장 POI였으나, 순수 관광 코호트(`tourism_core_cohort`)에서는 VL 콜드 스타트 비율이 **25.35%**(909/3,586건, 수도권 34.94%, 제주 20.18%)로 **10.64%p** 감소한다.
- **미매칭(Unseen) TourAPI 후보 점수화를 위한 구조적 설계와 선행 조건 식별**: 속성 기반 학습(`f(X_context, X_item)`)은 ID 암기 없이 미매칭 TourAPI 후보를 점수화하기 위한 구조적 청사진을 제공한다. 다만 **현 시점에서 모든 미매칭 TourAPI 후보의 온라인 서빙 호환성(parity)이 완성된 것은 아니며**, `region`(100% 매핑 완료) 외에 `SGG_CD` 결측 처리(현재 순수 관광 코호트의 **24.48%**만 보유), AI Hub ↔ TourAPI **카테고리 교차 매핑표(category crosswalk) 정의**, 그리고 미매칭 후보(85.55%)의 **인기도 콜드 스타트 기본값(prior) 설계**가 후속 모델링 단계에서 해결되어야 한다.

### 현재 결정된 것

- `TRAVELER_ID`, `TRAVEL_ID`, `VISIT_AREA_ID`, `POI_ID`, TourAPI `contentid`는 **메모리 내 조인·집계·중복 제거·분할 검증 및 후보 식별용 구분자(key)로는 사용할 수 있으나, 기계학습 모델의 입력 특성(feature)이나 ID 임베딩 학습 대상으로는 사용하지 않는다.**
- 학습 관측치 자격은 AI Hub 내부의 데이터 유효성과 관광 도메인 규칙으로 결정하므로, TourAPI 식별자 매칭 상태를 학습 코호트 필터로 사용하지 않는다(`experiment_design_audit.py`에서 자동 차단).
- 핵심 여행 문맥 5대 그룹(`STYLE`, `MOTIVE`, `DESTINATION`, `COMPANION`, `TEMPORAL`)의 도메인·결측·파생 규칙을 고정하고, 동반자 관계(`companion_relation_codes`)는 기록된 여행(81.21%)만 보는 민감도 분석 전용으로 분리한다.
- 방문 후 생성되는 모든 필드(`DGSTFN`, `REVISIT_INTENTION`, `RCMDTN_INTENTION`, `REVISIT_YN`, `VISIT_CHC_REASON_CD`, `RESIDENCE_TIME_MIN`, `VISIT_ORDER`, `VISIT_START_YMD`, `VISIT_END_YMD`)는 추천 요청 시점에 알 수 없으므로 입력 특성 사용을 금지한다.
- 미방문(unobserved) POI는 `unknown`으로 유지하며, 명시적 노출 가정이나 음성 표본 추출(negative sampling) 프로토콜·시드(seed) 없이 `0`(음성)으로 자동 변환하지 않는다.

### 아직 결정되지 않은 것

- 오프라인 AI Hub 세분류(`VISIT_AREA_TYPE_CD`, `ASORT_LCLASDC/MLSFCDC/SDASDC`)와 운영 TourAPI 분류(`contenttypeid`, `lclsSystm1..3`) 사이의 **공식 카테고리 교차 매핑표(category crosswalk)**
- `TC_CODEB` 원문 명칭이 `'기타'`인 `VISIT_AREA_TYPE_CD = "12"`(여행-POI 양성 중 단독 비중 1,774건: TL 1,582 / VL 192)를 후속 순위 모델에서 `tourism_core`에 유지할지 제외할지에 대한 민감도 비교
- 순위 학습 시 사용할 구체적인 음성 표본 추출(negative sampling) 비율·후보 범위와 최종 순위 모델 알고리즘(Two-Tower, GBDT/LambdaMART 등)
- 독립 테스트 분할(test split)의 출처 및 승인 프로토콜 (현재는 TL=학습, VL=검증까지만 허용)
- 온라인 서비스 UI에서 여행 문맥(스타일 8문항, 동기 3문항 등)을 어떤 설문 인터페이스로 수집할지

### 다음 행동

이 문서로 확정된 **학습 데이터 구성 및 특성/라벨 계약(`scripts/recommendation/training_data_contract.py`)**을 후속 순위 모델링 및 후보 평가 실험의 공통 입력 계층으로 사용한다. 미매칭 TourAPI 후보까지 실제로 점수를 매기는 서빙 모델을 학습하기 전에는 (1) 카테고리 교차 매핑표(crosswalk) 정의, (2) `SGG_CD` 결측(75.52%) 처리 전략, (3) 미매칭 후보의 인기도 콜드 스타트 기본값(prior) 프로토콜을 먼저 확정한다.

---

## 필요한 용어

공통 추천 용어는 [추천 시스템 용어 사전](glossary.md)을 기준으로 하며, 이 문서에서 핵심으로 쓰는 개념은 다음과 같다.

- **관측 단위(observation grain)**: 데이터 행 하나가 무엇을 의미하는지 정의하는 수준. 원시 방문 행 단위(`visit_event_grain`), 여행-장소 중복 제거 단위(`trip_poi_grain`), 여행 요청 단위(`trip_request_grain`)를 구분한다.
- **조인 키(join/grouping key)와 입력 특성(model feature)**: 조인 키(`TRAVEL_ID`, `POI_ID`, `contentid` 등)는 테이블을 연결하고 그룹을 나누며 후보 아이템을 식별하는 구분자(key)로 사용할 수 있으나, 기계학습 모델의 입력 특성(feature)으로는 사용하지 않는다. 입력 특성은 모델이 선호 패턴을 일반화하기 위해 학습하는 속성값(여행 스타일, 목적지 권역, 장소 유형 등)이다.
- **순수 관광 코호트(`tourism_core_cohort`)**: 식당·카페·집·숙소·단순 이동시설 등 일상/경유 방문을 제외하고 `TC_CODEB`(`cd_a = 'VIS'`) 기준 자연관광지(`1`)·역사/유적/종교(`2`)·문화시설(`3`)·레저/스포츠(`5`)·테마시설(`6`)·산책로/둘레길(`7`)·지역 축제/행사(`8`)·기타(`12`)·체험 활동 관광지(`13`)를 분리한 기본 학습 대상 집단.
- **학습-서빙 특성 호환성(training-serving feature parity)**: 오프라인 학습 데이터(AI Hub)에서 사용한 입력 특성을 온라인 추천 시점의 후보 아이템(TourAPI)에서도 동일한 의미와 코드 체계로 공급할 수 있는 성질. 이 계약은 각 특성의 호환성 상태(확립 / 부분 커버리지 / 교차 매핑 미정의)를 구분하여 기록한다.

---

## 1. 왜 TourAPI 식별자 매칭 상태와 학습 데이터 자격은 독립인가?

### 1.1 질문과 배경

Issue #69의 다단계 식별자 매칭 파이프라인(Stage 5)은 AI Hub 방문-POI 쌍 97,640건 중 **26,454건(27.09%)**을 TourAPI `contentid`와 확정 연결(`MATCHED`)하고, TourAPI 적격 후보 카탈로그(19,051개) 중 **2,753개(14.45%)**에 대한 시드 브리지(seed bridge)를 확보했다. 이때 **"TourAPI와 `MATCHED`된 방문만 추천 모델 학습에 써야 하는가, 아니면 `UNMATCHED` 방문도 학습에 포함해야 하는가?"**라는 질문이 발생한다.

### 1.2 아키텍처 원칙: ID 암기가 아닌 속성 기반(Attribute-Based) 학습 설계

이 계약은 ID 기반 표현의 한계와 외부 식별자 연결의 역할을 다음과 같이 구분한다.

1. **운영 카탈로그의 85.55%가 ID 학습 이력 부재(Item Cold-Start)**: TourAPI 적격 관광 후보 19,051개 중 AI Hub 방문 이력과 직접 매칭되지 않은 **16,298개(85.55%)** 후보에는 학습된 ID 임베딩이 존재하지 않아 ID 기반 모델로는 추천 점수를 계산할 수 없다.
2. **외부 식별자 연결과 학습 관측치 자격의 분리**: `UNMATCHED`는 현재 매칭 규칙으로 외부 카탈로그 식별자와의 동등성을 확정하지 못했다는 뜻이다. 이 상태만으로 장소의 존재 여부나 AI Hub 관측치의 유효성을 판정할 수 없으므로, 학습 자격은 AI Hub 내부 유효성과 관광 도메인 규칙으로 별도 판단한다.

따라서 본 프로젝트의 추천 학습 계약은 원시 ID를 조인·집계·후보 식별용 키(key)로만 사용하고, 모델 입력 특성(feature)은 속성 공간으로 구성하는 아래 설계를 따른다.

```text
[오프라인 학습 (AI Hub 2023 TL)]
  여행/요청 문맥 특성 X_context (스타일, 동기, 동반자, 시기, 목적지 권역)
        ×
  방문 장소 속성 특성 X_item (권역, 시군구 코드, 관광 분류, 학습 내 인기도)
        ↓
  점수 함수 f(X_context, X_item) 학습  (※ POI_ID / contentid는 조인·식별 키로만 쓰고 모델 입력 특성에서 제외)

[온라인 추론 / 미매칭 후보 점수화 목표 구조 (TourAPI v4.4 Catalog)]
  신규 사용자 요청 문맥 X_context
        ×
  TourAPI 후보 속성 X_item (ProductRegion 매핑 + SggCrosswalk + [선행 과제: 카테고리 Crosswalk & Cold-Start Prior])
        ↓
  공통 속성 공간이 정렬된 범주에서 미매칭(unseen) TourAPI 후보에 점수 부여
```

> **주의 (미해결 선행 과제 명시)**: 위 구조는 ID 암기 없이 미매칭 후보를 다루기 위한 **구조적 설계 방향**이며, 현재 모든 특성에서 학습-서빙 호환성이 완성되었다는 뜻이 아니다. `region`(100% 매핑 완료)과 달리 `SGG_CD`는 순수 관광 양성의 **24.48%**에서만 존재하고, `VISIT_AREA_TYPE_CD`/`ASORT_*` ↔ TourAPI `contenttypeid`/`lclsSystm1..3` 간 **공식 카테고리 교차 매핑표(crosswalk)는 아직 정의되지 않았으며**, 미매칭 TourAPI 후보(85.55%)의 `train_positive_interaction_count`는 `0`이므로 명시적 콜드 스타트 기본값(prior) 설계가 선행되어야 한다(§3.2 상세).

**[결정]**
- 학습 관측치의 포함 자격은 오직 **AI Hub 내부의 구조적 무결성과 관광 도메인 적합성**으로만 판정하며, TourAPI `catalog_match_status`(`MATCHED`, `AMBIGUOUS`, `UNMATCHED`, `identity_source_missing`)에 의해 학습 데이터를 필터링하지 않는다.
- TourAPI 식별자 브리지(Stage 5)는 **(a) TourAPI 카탈로그 후보 위에서 오프라인 Top-K 순위 지표를 계산할 때 정답(ground-truth) 위치를 확인하는 평가 브리지** 및 **(b) 매칭된 시드 POI(14.45%)의 초기 인기도 보정 신호**로만 역할이 구분된다.

---

## 2. 관측 단위(Grain)와 식별자 경계 계약

### 2.1 3단계 관측 단위(Observation Grain)

분석 목적과 학습 단계에 따라 아래 세 가지 관측 단위를 엄격히 구분한다.

| 관측 단위 명칭 | 메모리 내 복합 키 구성 | 전체 규모 (TL / VL) | 정의 및 계약상 용도 |
| :--- | :--- | ---: | :--- |
| **`visit_event_grain`** (방문 이벤트 단위) | `(region, TRAVEL_ID, VISIT_AREA_ID)` | **140,555건** (125,174 / 15,381) | `TN_VISIT_AREA_INFO`의 원시 방문 행 단위. 한 여행 내 동일 장소 재방문과 방문별 사후 피드백(`DGSTFN` 등), `POI_ID` 결측 방문(31,684건)을 모두 보존한다. 원시 품질 감사 및 사후 만족도 보조 실험의 기본 단위다. |
| **`trip_poi_grain`** (여행-POI 상호작용 단위) | `(region, TRAVEL_ID, POI_ID)` *(단, `POI_ID` 비결측)* | **97,640건** (87,010 / 10,630) | 동일 `TRAVEL_ID` 안에서 같은 `POI_ID`를 여러 번 방문한 경우(8,832쌍, 추가 이벤트 11,231건)를 **단일 이진 관측 양성(`observed_positive = 1`)**으로 중복 제거한 단위. 후보 순위화(ranking) 및 문맥-POI 쌍 모델링의 **주 학습 단위**다. |
| **`trip_request_grain`** (여행/요청 문맥 단위) | `(region, TRAVELER_ID, TRAVEL_ID)` | **11,520건** (10,240 / 1,280) | 여행 문맥(`TN_TRAVEL`, `TN_TRAVELLER_MASTER`)이 결합되는 단위이자 **데이터 분할(split) 무결성 단위**. 동일 `TRAVEL_ID`에 속한 모든 방문은 반드시 같은 분할(TL 또는 VL)에 속해야 한다. |

### 2.2 식별자(Join / Candidate Key) vs 기계학습 모델 입력 특성(Feature) 경계

| 구분 | 대상 필드 | 허용 역할 (In-Memory Identifier / Key) | 금지 역할 (ML Input Feature / Output) |
| :--- | :--- | :--- | :--- |
| **원시 식별자 (Memory-Only Keys)** | `TRAVELER_ID`, `TRAVEL_ID`, `VISIT_AREA_ID`, `POI_ID`, TourAPI `contentid` | 메모리 내 테이블 조인, 중복 제거, 여행 단위 그룹화, 후보 아이템 인덱싱/식별, TL/VL 누수 점검 | **기계학습 모델의 입력 특성(feature)**, ID 임베딩 레이어 학습 대상, 로그/아티팩트/문서 출력 |
| **권역 스코프 키 겸 범주형 특성** | `region` (`capital`, `west`, `east`, `jeju-islands`) | 원천 데이터 스코프 분리 키 **및** 요청/아이템의 광역 권역 범주형 입력 특성 | 다른 권역의 동일 문자열 ID를 같은 개체로 병합하는 근거로 사용 금지 |

---

## 3. 입력 특성(Input Feature) 및 학습-서빙 호환성(Parity) 계약

추천 시점(prediction time)에 사용할 수 있는 입력 특성과 데이터 정제 규칙, 그리고 운영 시 TourAPI 후보 아이템과의 호환성 상태 및 미해결 선행 과제를 아래 표로 확정한다.

### 3.1 여행/요청 문맥 특성 (Trip / Request Context Features)

이 표는 추천 요청 시점에 여행자·여행 단위에서 입력받는 문맥 특성의 허용 도메인, 결측 처리, 그리고 4개 권역 실제 데이터(`trip_request_grain`, N=11,520) 기준 완전성(completeness)을 판단하기 위한 계약표다.

| 특성 그룹 | 특성명 (컬럼명) | 원천 테이블 | 타입 및 허용 도메인 | 정제·파생 및 결측 처리 규칙 | 4권역 완전성 (TL / VL) | 온라인 서빙 호환성 상태 및 선행 조건 |
| :--- | :--- | :--- | :--- | :--- | ---: | :--- |
| **STYLE** | `TRAVEL_STYL_1` .. `TRAVEL_STYL_8` | `TN_TRAVELLER_MASTER` | 범주형 문자열, 도메인 `{"1".."7"}` (코드 `TSY`) | 공백 제거 후 `1..7` 범위 밖 값은 임의 대체(imputation) 없이 `None`(결측) 처리 | **100.00%** (10,240 / 1,280) | **설문 수집 시 호환 가능**: 온라인 서비스에서 8개 스타일 문항(1~7 척도) 수집 UI 정의 필요 |
| **MOTIVE** | `TRAVEL_MOTIVE_1` .. `TRAVEL_MOTIVE_3` | `TN_TRAVELLER_MASTER` | 범주형 문자열, 도메인 `{"1".."10"}` (코드 `TMT`) | `1..10` 범위 밖 또는 빈 값은 `None` 처리. (`TRAVEL_MOTIVE_3` 등 일부 결측 존재) | **92.65%** (9,491 / 1,182) | **설문 수집 시 호환 가능**: 3순위 동기 결측(7.35%) 처리를 위한 명시적 결측 토큰 또는 1순위 동기 단독 사용 결정 필요 |
| **DESTINATION** | `region` | 데이터셋 권역 바인딩 | 범주형 문자열 (`capital`, `west`, `east`, `jeju-islands`) | 필수 스코프 값 (결측 없음) | **100.00%** (10,240 / 1,280) | **호환성 확립(Parity Established)**: [`poi-catalog-policy-v1.json`](../../config/recommendation/poi-catalog-policy-v1.json)의 16개 시도 `lDongRegnCd` 매핑과 100% 대응 |
| **DESTINATION** | `TRAVEL_STATUS_DESTINATION` | `TN_TRAVELLER_MASTER` | 범주형 문자열 (목적지 코드) | 공백 제거 후 비결측 원문 코드를 범주형으로 사용 | **100.00%** (10,240 / 1,280) | **오프라인 전용 (서빙 매핑 미정)**: 온라인 요청 지역 코드와의 세부 대응 규칙이 확정되기 전까지 오프라인 문맥 실험에만 사용 |
| **COMPANION** | `TRAVEL_STATUS_ACCOMPANY` | `TN_TRAVELLER_MASTER` | 범주형 문자열 (동반 현황 코드) | 공백 제거 후 비결측 원문 코드를 범주형으로 사용 | **100.00%** (10,240 / 1,280) | **설문 수집 시 호환 가능**: 여행 요청 시 동반 유형 선택값과 코드북 매핑 정의 필요 |
| **COMPANION** | `TRAVEL_COMPANIONS_NUM` | `TN_TRAVELLER_MASTER` | 정수형 (`int >= 0`) | 정수 파싱 후 음수(`< 0`) 또는 파싱 불가 값은 `None` 처리 | **100.00%** (10,240 / 1,280) | **호환성 확립**: 여행 요청 시 동반 인원수 입력(`>= 0`)과 직접 호환 |
| **TEMPORAL** | `month` | `TN_TRAVEL.TRAVEL_START_YMD` 파생 | 범주형 문자열 (`"01"`..`"12"`) | ISO 날짜 파싱 후 시작 월 2자리 추출. 원시 날짜(`YYYY-MM-DD`)는 저장·입력 금지 | **100.00%** (10,240 / 1,280) | **호환성 확립**: 추천 요청 시점의 계획 여행 월(`01`..`12`)과 100% 호환 |
| **TEMPORAL** | `elapsed_days` | `TN_TRAVEL.TRAVEL_START_YMD`, `TRAVEL_END_YMD` 파생 | 정수형 (`(end - start).days >= 0`) | `end < start`(역전 날짜) 또는 파싱 실패 시 `None` 처리 (4권역 역전 날짜 **0건**) | **100.00%** (10,240 / 1,280) | **호환성 확립**: 추천 요청 시점의 여행 기간(박/일수) 입력과 100% 호환 |
| **COMPANION (민감도 전용)** | `companion_relation_codes` | `TN_COMPANION_INFO.REL_CD` 파생 | 정렬된 고유 튜플, 도메인 `{"1".."11"}` (코드 `TCR`) | 여행별 유효 `REL_CD` 오름차순 중복 제거. 행 부재 시 1인 여행과 미기록 구분 불가하므로 **기본 `context_only` 코호트에서 제외**하고 `recorded_only` 민감도 분석에만 사용 | **81.21%** (8,304 / 1,051) | **오프라인 민감도 분석 전용**: 기본 서빙 필수 입력 아님 |

### 3.2 아이템 / POI 표현 특성 및 미매칭(Unseen) TourAPI 후보 연결 상태

이 표는 AI Hub 방문 장소에서 추출한 아이템 특성이 운영 시점의 TourAPI 후보 아이템(특히 AI Hub 매칭 이력이 없는 85.55%의 unseen 후보)과 연결될 때 **현재 무엇이 준비되어 있고 무엇이 아직 미해결인지**를 명확히 구분한다.

| 특성 구분 | 특성명 (컬럼명) | AI Hub 학습 원천 | TourAPI 서빙 원천 | 4권역 순수 관광 코호트 커버리지 (TL / VL) | 학습 ↔ TourAPI 서빙 호환성 상태 및 미해결 선행 과제 |
| :--- | :--- | :--- | :--- | ---: | :--- |
| **기본 공간 특성** | `region` | 권역 스코프 (`capital`, `west`, `east`, `jeju-islands`) | `lDongRegnCd` → `ProductRegion` 정책 매핑 | **100.00%** (29,307 / 3,586) | **호환성 확립(Parity Established)**: 모든 TourAPI 후보는 `poi-catalog-policy-v1.json`에 의해 4대 권역 중 하나로 100% 매핑됨 |
| **세부 행정구역 특성** | `SGG_CD` | `TN_VISIT_AREA_INFO.SGG_CD` 및 `TN_POI_MASTER.SGG_CD` (5자리 시군구 코드) | `(lDongRegnCd, lDongSignguCd)` | 방문 행 단독 **1.26%** (360 / 54) → 마스터 결합 시 **24.48%** (7,132 / 922) | **코드 매핑(`SggCrosswalk`) 확립 / AI Hub 커버리지 부분적(24.48%)**: 강원(`42→51`), 전북(`45→52`), 전남광주(`29/46→12`), 세종(`36110`) 및 일반구 호환 규칙은 구현되었으나, AI Hub 순수 관광 양성의 **75.52%**에서 `SGG_CD`가 비어 있으므로 결측 허용(missing-aware) 인코딩 또는 주소 기반 시군구 보강 없이는 전체 후보 점수화의 주 신호로 단독 사용할 수 없음 |
| **기본 장소 유형** | `VISIT_AREA_TYPE_CD` | `TN_VISIT_AREA_INFO.VISIT_AREA_TYPE_CD` (`1..13, 21..24`, 코드 `VIS`) | `contenttypeid` (`{12, 14, 28}`) 및 `lclsSystm1..3` | **100.00%** (29,307 / 3,586) | **오프라인 코호트 분리 확정 / 서빙 피처 호환 미확립(Crosswalk 미정의)**: AI Hub 내부에서 순수 관광 코호트를 분리하는 데는 100% 사용 가능하나, AI Hub `VIS` 코드와 TourAPI `contenttypeid`는 1:1 동등 코드가 아니다. **공식 카테고리 교차 매핑표(crosswalk)가 정의되기 전에는 미매칭 TourAPI 후보에 이 특성을 직접 주입할 수 없다** |
| **확장 마스터 분류** | `ASORT_LCLASDC`, `ASORT_MLSFCDC`, `ASORT_SDASDC` | 동일 권역 `TN_POI_MASTER` 유일 `POI_ID` 조인 | TourAPI `lclsSystm1`, `lclsSystm2`, `lclsSystm3` | 마스터 조인 **77.72%** (22,799 / 2,764), 4개 필드 모두 비결측 **2.69%** (785 / 101) | **오프라인 보조 실험 전용 (서빙 피처 미확립)**: 마스터 조인은 77.72%에서 성립하나 4개 필드가 모두 채워진 `rich_complete` 비율이 **2.69%**(전체 방문 기준 3.57%)로 극히 희소하며, TourAPI `lclsSystm1..3`와의 분류 체계 교차 매핑(crosswalk)도 아직 정의되지 않음 |
| **학습 분할 인기도** | `train_positive_interaction_count`, `popularity_band` | **오직 TL(학습 분할) 내부**에서 집계한 `(region, POI_ID)` 관측 양성 빈도 | Stage 5 매칭 시드(14.45%)는 TL 빈도 전이 가능; 미매칭 후보(85.55%)는 `0` (Cold-Start) | TL 정의 **100.00%**, VL 중 TL 등장 비율 **74.65%** (2,677 / 3,586) | **시드 브리지(14.45%)만 전이 가능 / 미매칭 후보(85.55%)는 Cold-Start Prior 필수**: VL을 인기도 계산에 포함하면 데이터 누수이므로 엄격히 금지한다. 운영 시 미매칭 TourAPI 후보(85.55%)는 과거 방문 수가 `0`이므로 명시적 cold-start prior 규칙이 정의되어야 한다 |

### 3.3 명시적 사용 금지 특성 (Explicitly Excluded Features)

다음 필드는 데이터 누수(leakage), 식별자 암기, 개인정보 보호 또는 의미 미확정 사유로 기계학습 모델의 입력 특성(feature)에서 **전면 배제**한다.

| 배제 범주 | 배제 대상 필드 | 배제 사유 |
| :--- | :--- | :--- |
| **원시 식별자 (Identifiers as Features)** | `TRAVELER_ID`, `TRAVEL_ID`, `VISIT_AREA_ID`, `POI_ID`, `contentid` | 메모리 내 조인·집계·후보 식별용 키(key)로는 사용할 수 있으나, **기계학습 모델의 입력 특성(feature)**으로 넣으면 ID 암기에 의존하게 되어 신규 사용자 및 미매칭 후보 일반화를 해침 |
| **사후 피드백 및 방문 후 기록 (Post-Event Leakage)** | `DGSTFN`, `REVISIT_INTENTION`, `RCMDTN_INTENTION`, `REVISIT_YN`, `VISIT_CHC_REASON_CD`, `RESIDENCE_TIME_MIN`, `VISIT_ORDER`, `VISIT_START_YMD`, `VISIT_END_YMD`, `LODGING_TYPE_CD`, 이동/소비/활동/사진 테이블 전체 | 모두 여행 중 실제 방문이 일어난 뒤에만 관측되는 사후(post-visit) 결과값으로, 추천 요청 시점(prediction time)에 알 수 없는 미래 정보 누수임 |
| **인구통계 및 민감 속성 (Demographics)** | `GENDER`, `AGE_GRP`, `INCOME`, `HOUSE_INCOME`, `EDU_NM`, `EDU_FNSH_SE`, `MARR_STTS`, `JOB_NM`, `JOB_ETC`, `RESIDENCE_SGG_CODE` | 온라인 서비스 최소 수집 원칙, 동의 정책 미정, 공정성 이슈로 기본 추천 입력에서 제외 |
| **원시 날짜·좌표·자유 텍스트·이미지 및 미확정 코드** | 원시 `TRAVEL_START_YMD`/`TRAVEL_END_YMD`, `X_COORD`/`Y_COORD`, `VISIT_AREA_NM`/`POI_NM`/`ROAD_NM_ADDR`/`LOTNO_ADDR`, `TRAVEL_MISSION`/`TRAVEL_MISSION_CHECK`, `season`, 원시 사진 및 `SbL` 캡션(`IMG_CAPTION`) | 개인정보/위치 추적 위험, 자유 텍스트/좌표의 직접 입력 부적합, 복합 코드(`TRAVEL_MISSION`) 정규화 규칙 미확정 |

---

## 4. 라벨(Label) 및 상호작용 의미 계약

### 4.1 주 학습 라벨: 암묵적 관측 양성 (`observed_positive = 1`)

- **정의**: `trip_poi_grain`(`(region, TRAVEL_ID, POI_ID)`)에서 관측된 방문 쌍은 `observed_positive = 1`을 부여한다.
- **여행 내 반복 방문 처리**: 동일 여행(`TRAVEL_ID`) 안에서 같은 `POI_ID`가 여러 번 기록된 경우(전체 97,640쌍 중 **8,832쌍(9.05%)**, 추가 방문 이벤트 **11,231건**)도 기준 계약에서는 가중치를 곱하지 않고 이진 양성(`1`) 하나로 중복 제거한다. 반복 횟수(`repeat_visit_count`)는 진단 지표로만 보존한다.
- **미관측(Unobserved) 항목 처리**: 해당 여행에서 방문 기록이 없는 후보 POI는 **알 수 없음(`unknown`)**이지 "방문하지 않음 = 싫어함(`0`)"이 아니다. 여행로그에는 당시 사용자가 어떤 후보를 보았는지(노출, exposure) 기록이 없기 때문이다. 순위 학습(BPR, Cross-Entropy 등)을 위해 음성 표본 추출(negative sampling)을 수행할 때는 반드시 **(a) 추출 후보 모집단 정의**, **(b) 추출 비율**, **(c) 고정 난수 시드(seed)**를 실험 설정에 명시해야 한다.

### 4.2 보조 사후 피드백 라벨 (`DGSTFN`, `REVISIT_INTENTION`, `RCMDTN_INTENTION`)

- **정의**: `TN_VISIT_AREA_INFO`에 기록된 만족도(`DGSTFN`), 재방문 의향(`REVISIT_INTENTION`), 추천 의향(`RCMDTN_INTENTION`)은 허용 도메인 `{"1", "2", "3", "4", "5"}`를 갖는 방문 후 평가 응답이다.
- **취급 규칙**:
  1. 세 라벨은 의미가 서로 다르므로 임의로 합산하거나 평균내어 단일 점수로 만들지 않고 **각각 독립된 보조 타깃(auxiliary target)**으로 유지한다.
  2. 추천 시점의 입력 특성(feature)으로 절대 사용할 수 없다.
  3. 이미 방문한 장소에 대한 사후 만족도 분류 정확도(accuracy) 결과를 근거로 "Top-K POI 추천 순위 품질이 개선되었다"고 주장할 수 없다(`experiment_design_audit.py`에서 차단).

---

## 5. 관측치 포함·배제 규칙 (2단계 코호트 구조 및 `TC_CODEB` 검증)

학습 및 평가 코호트는 **1단계 구조적 무결성 필터**와 **2단계 관광 도메인 코호트 분리**를 거쳐 정의한다. 모든 단계는 TourAPI 매칭 여부와 무관하게 AI Hub 원천 데이터 내부 규칙으로만 결정론적으로 판정한다.

### 5.1 1단계: 구조적 배제 규칙 (Hard Structural Exclusions)

| 배제 사유 코드 (`exclusion_reason`) | 판정 기준 | 적용 범위 및 실제 감사 건수 (4권역 합계) |
| :--- | :--- | :--- |
| `missing_or_unmapped_trip` | 방문 행의 `TRAVEL_ID`가 비어 있거나 동일 권역/분할의 `TN_TRAVEL`에 유일하게 매핑되지 않음 | 모든 단위에서 배제 (**0건** — 전 권역 100% 유일 매핑 확인) |
| `missing_or_ambiguous_traveler` | `TN_TRAVEL.TRAVELER_ID`가 비어 있거나 동일 권역/분할의 `TN_TRAVELLER_MASTER`에 유일하게 매핑되지 않음 | 문맥 결합 및 모든 단위에서 배제 (**0건** — 전 권역 100% 유일 매핑 확인) |
| `missing_visit_area_id` | `TN_VISIT_AREA_INFO.VISIT_AREA_ID`가 비어 있음 | 모든 단위에서 배제 (**0건**) |
| `missing_poi_id` | `TN_VISIT_AREA_INFO.POI_ID`가 비어 있음 | `visit_event_grain`(140,555건)에서는 보존하되, `trip_poi_grain`(97,640건) 및 POI 기반 순위/인기도 코호트에서 배제 (**31,684건**, 전체 방문 이벤트의 22.54%) |
| `invalid_value_or_date` | 허용 도메인 밖의 코드값 또는 종료일이 시작일보다 빠른 역전 날짜(`TRAVEL_END_YMD < TRAVEL_START_YMD`) | 임의 대체 없이 해당 특성을 `None`으로 변환하며, 해당 특성을 필수로 요구하는 `complete-case` 코호트에서만 제외 (역전 날짜 **0건**, 동기 일부 결측 여행 **847건(7.35%)**) |

### 5.2 2단계: 공식 코드북 `TC_CODEB`(`cd_a = 'VIS'`) 검증 및 관광 도메인 코호트 분리

4개 권역(`capital`, `west`, `east`, `jeju-islands`)의 TL/VL 8개 분할에 포함된 실제 `TC_CODEB` CSV 파일을 `validate_vis_codebook_rows()`로 전수 검증한 결과, 8개 분할 모두 `cd_a = 'VIS'` 코드 **17개(`1..13, 21..24`)의 `cd_b -> cd_nm` 매핑이 100% 동일(불일치 0건)**함을 확인했다.

이 표는 4개 권역 `TC_CODEB`(`cd_a = 'VIS'`)에서 직접 검증한 공식 코드명(`cd_nm`)과 이 계약에서의 코호트 배정 기준을 보여준다.

| `cd_b` (`VISIT_AREA_TYPE_CD`) | `TC_CODEB` 공식 코드명 (`cd_nm`, `cd_a = 'VIS'`) | 코호트 배정 | 배정 근거 및 해석 시 주의점 |
| :---: | :--- | :---: | :--- |
| `1` | `자연관광지` | **`tourism_core`** | 자연 명소·해변·산·섬 등 핵심 관광지 |
| `2` | `역사/유적/종교 시설(문화재, 박물관, 촬영지, 절 등)` | **`tourism_core`** | 문화재·박물관·사찰·촬영지 등 핵심 역사/문화 관광지 |
| `3` | `문화 시설(공연장, 영화관, 전시관 등)` | **`tourism_core`** | 공연장·전시관 등 문화시설 (TourAPI `14 문화시설` 대응 도메인) |
| `5` | `레저/스포츠 관련 시설(스키, 카트, 수상레저)` | **`tourism_core`** | 스키·카트·수상레저 등 (TourAPI `28 레포츠` 대응 도메인) |
| `6` | `테마시설(놀이공원, 워터파크)` | **`tourism_core`** | 놀이공원·워터파크 등 핵심 테마 관광시설 |
| `7` | `산책로, 둘레길 등` | **`tourism_core`** | 올레길·둘레길·트레킹 코스 등 도보 관광지 |
| `8` | `지역 축제/행사` | **`tourism_core`** | 지역 축제 및 관광 행사 |
| `12` | `기타` | **`tourism_core`** *(주의)* | **[주의]** `TC_CODEB` 원문 명칭은 `'기타'`다. Issue #69 및 본 계약의 기본 `tourism_core` 집합(`32,893건`)에는 다른 유형(1~11, 13, 21~24)에 속하지 않는 기타 방문지(`12`)가 포함되어 있으나, 엄밀한 순수 관광 정의에서는 모호성이 있으므로 **후속 실험에서 `12` 포함(32,893건: TL 29,307 / VL 3,586) vs `12` 제외(31,119건: TL 27,725 / VL 3,394, 차이 1,774건) 민감도를 점검할 수 있도록 원문 라벨 `'기타'`를 그대로 보존**한다. |
| `13` | `체험 활동 관광지` | **`tourism_core`** | 체험 마을·공방·농어촌 체험 등 핵심 체험 관광지 |
| `4` | `상업지구(거리, 시장, 쇼핑시설)` | `non_tourism` | 상업 거리·시장·쇼핑 (TourAPI 기본 추천 지원 유형 `{12,14,28}` 외) |
| `9` | `역, 터미널, 고속도로 휴게소` | `non_tourism` | 교통 환승·이동 경유 시설 |
| `10` | `상점` | `non_tourism` | 일반 소매 상점 |
| `11` | `식당/카페` | `non_tourism` | 식음료 소비 시설 (전체 방문 이벤트의 25.51%) |
| `21` | `집` | `non_tourism` | 여행자의 출발/귀가 자택 (전체 방문 이벤트의 15.07%) |
| `22` | `친구/친지집` | `non_tourism` | 지인 거주지 방문 |
| `23` | `사무실` | `non_tourism` | 업무 공간 |
| `24` | `숙소` | `non_tourism` | 호텔·펜션 등 체류 숙박시설 (전체 방문 이벤트의 9.38%) |

---

## 6. 4개 권역 실제 데이터 코호트 감사 결과

아래 수치는 `scripts/recommendation/training_data_contract.py`를 통해 4개 권역(`capital`, `west`, `east`, `jeju-islands`)의 승인된 2023년 TL/VL, `TC_CODEB`, `TN_POI_MASTER` 원본을 읽기 전용으로 감사한 비식별 정확 집계(`run_id: issue71-training-contract-20261020T1550Z`)다.

### 6.1 관측 단위별 코호트 퍼널 (Cohort Funnel Summary)

이 표는 원시 여행·방문 행이 1단계 구조적 필터(`missing_poi_id` 등)와 2단계 순수 관광 도메인 분리(`tourism_core_cohort`), 그리고 주요 문맥 완전성(`primary_context_complete`) 조건을 거치며 학습·검증 표본 크기가 어떻게 결정되는지 판단하기 위한 핵심 퍼널 자료다.

| 퍼널 단계 및 코호트 정의 | 관측 단위 | TL (학습 분할) | VL (검증 분할) | 4권역 합계 | 상위 분모 대비 비율 |
| :--- | :--- | ---: | ---: | ---: | ---: |
| **1. 전체 유효 여행 (`trips_valid_owner`)** | `trip_request_grain` | 10,240 | 1,280 | **11,520** | 100.00% (구조적 누락 0건) |
| ├─ 비결측 `POI_ID` 방문이 1건 이상 있는 여행 | `trip_request_grain` | 10,053 | 1,255 | **11,308** | 98.16% (전체 여행 대비) |
| ├─ 순수 관광(`tourism_core`) POI 방문이 1건 이상 있는 여행 | `trip_request_grain` | 9,381 | 1,167 | **10,548** | 91.56% (전체 여행 대비) |
| └─ 5대 핵심 문맥(`STYLE`·`MOTIVE`·`DEST`·`COMP`·`TEMP`) 완비 여행 | `trip_request_grain` | 9,491 | 1,182 | **10,673** | 92.65% (전체 여행 대비) |
| **2. 전체 유효 방문 이벤트 (`visit_events_valid`)** | `visit_event_grain` | 125,174 | 15,381 | **140,555** | 100.00% (구조적 누락 0건) |
| ├─ `POI_ID` 결측 방문 행 (`missing_poi_id` 배제) | `visit_event_grain` | 28,177 | 3,507 | **31,684** | 22.54% (전체 방문 이벤트 대비) |
| ├─ 순수 관광 방문 이벤트 (`visit_events_tourism_core`) | `visit_event_grain` | 32,434 | 4,009 | **36,443** | 25.93% (전체 방문 이벤트 대비) |
| ├─ 비관광/일상 방문 이벤트 (`visit_events_non_tourism`) | `visit_event_grain` | 92,740 | 11,372 | **104,112** | 74.07% (전체 방문 이벤트 대비) |
| └─ 사후 피드백 3종(`DGSTFN` 등) 도메인 유효 이벤트 | `visit_event_grain` | 102,859 | 12,586 | **115,445** | 82.14% (전체 방문 이벤트 대비) |
| **3. 전체 여행-POI 관측 양성 (`trip_poi_positives_all`)** | `trip_poi_grain` | 87,010 | 10,630 | **97,640** | 100.00% (비결측 POI 중복 제거 후) |
| ├─ 여행 내 동일 POI 반복 방문 쌍 (`repeat_visit_count >= 2`) | `trip_poi_grain` | 7,841 | 991 | **8,832** | 9.05% (중복 제거된 추가 이벤트 11,231건) |
| ├─ **순수 관광 코호트 양성 (`tourism_core_cohort`)** | `trip_poi_grain` | **29,307** | **3,586** | **32,893** | **33.69%** (전체 `trip_poi` 양성 대비) |
| ├─ 비관광 전용 양성 (`non_tourism_only`) | `trip_poi_grain` | 57,703 | 7,044 | **64,747** | 66.31% (전체 `trip_poi` 양성 대비) |
| ├─ 핵심 문맥 완비 × 전체 여행-POI 양성 | `trip_poi_grain` | 81,741 | 9,985 | **91,726** | 93.94% (전체 `trip_poi` 양성 대비) |
| └─ **핵심 문맥 완비 × 순수 관광 코호트 양성** | `trip_poi_grain` | **27,586** | **3,400** | **30,986** | **94.20%** (순수 관광 `trip_poi` 양성 대비) |

### 6.2 권역 × 분할별 코호트 및 아이템 특성 커버리지 상세

이 표는 4개 권역 각각의 TL/VL 분할에서 전체 관측 양성(`all_valid`)과 순수 관광 코호트(`tourism_core`)의 표본 수, 고유 POI 수, `TN_POI_MASTER` 조인율, `SGG_CD` 교차 매핑(crosswalk) 유효율, 그리고 VL 콜드 스타트 비율이 권역별로 균일하게 유지되는지 확인하기 위한 자료다.

| 권역 / 분할 | 유효 여행 수 (문맥 완비율) | 전체 방문 행 (`missing_poi`) | `trip_poi` 전체 양성 (고유 POI) | `trip_poi` **순수 관광 양성** (고유 관광 POI) | 순수 관광 × 문맥 완비 양성 | 순수 관광 `TN_POI_MASTER` 유일 조인율 | 순수 관광 통합 `SGG_CD` 유효율 | 순수 관광 VL 콜드 스타트율 (전체 VL 콜드 스타트율) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **capital / TL** | 2,560 (91.64%) | 21,384 (6,710) | 13,660 (8,655) | **4,425** (2,121) | 4,140 (93.56%) | 3,198 (72.27%) | 1,430 (32.32%) | — |
| **capital / VL** | 320 (94.69%) | 2,770 (828) | 1,811 (1,545) | **621** (486) | 601 (96.78%) | 460 (74.07%) | 204 (32.85%) | **34.94%** (51.68%) |
| **west / TL** | 2,560 (92.34%) | 28,389 (6,941) | 19,584 (9,429) | **7,145** (2,684) | 6,659 (93.20%) | 5,627 (78.75%) | 2,274 (31.83%) | — |
| **west / VL** | 320 (89.69%) | 3,486 (890) | 2,357 (1,784) | **851** (586) | 784 (92.13%) | 667 (78.38%) | 282 (33.14%) | **25.38%** (36.57%) |
| **east / TL** | 2,560 (92.42%) | 29,392 (6,848) | 20,456 (10,381) | **6,975** (2,656) | 6,533 (93.66%) | 5,338 (76.53%) | 1,520 (21.79%) | — |
| **east / VL** | 320 (90.62%) | 3,538 (823) | 2,468 (1,938) | **801** (566) | 752 (93.88%) | 600 (74.91%) | 201 (25.09%) | **26.34%** (39.30%) |
| **jeju-islands / TL** | 2,560 (94.34%) | 46,009 (7,678) | 33,310 (13,152) | **10,762** (3,275) | 10,254 (95.28%) | 8,636 (80.25%) | 1,908 (17.73%) | — |
| **jeju-islands / VL** | 320 (94.38%) | 5,587 (966) | 3,994 (2,677) | **1,313** (773) | 1,263 (96.19%) | 1,037 (78.98%) | 235 (17.90%) | **20.18%** (26.49%) |
| **4권역 합계** | **11,520 (92.65%)** | **140,555 (31,684)** | **97,640** | **32,893** | **30,986 (94.20%)** | **25,563 (77.72%)** | **8,054 (24.48%)** | **25.35%** (35.99%) |

### 6.3 방문지 유형 코드(`VISIT_AREA_TYPE_CD`) 전체 분포와 `TC_CODEB` 공식 명칭

이 표는 원시 방문 이벤트(140,555건)가 `TC_CODEB`(`cd_a = 'VIS'`) 공식 코드명 기준으로 어떻게 분포되어 있으며, 왜 `tourism_core`와 `non_tourism` 분리가 필수적인지 보여주는 근거 표다.

| `VISIT_AREA_TYPE_CD` | `TC_CODEB` 공식 코드명 (`cd_nm`) | 도메인 코호트 분류 | TL 방문 이벤트 | VL 방문 이벤트 | 전체 방문 이벤트 | 전체 대비 비중 |
| :---: | :--- | :---: | ---: | ---: | ---: | ---: |
| `1` | 자연관광지 | **`tourism_core`** | 10,769 | 1,336 | 12,105 | 8.61% |
| `2` | 역사/유적/종교 시설(문화재, 박물관, 촬영지, 절 등) | **`tourism_core`** | 5,947 | 760 | 6,707 | 4.77% |
| `3` | 문화 시설(공연장, 영화관, 전시관 등) | **`tourism_core`** | 3,644 | 444 | 4,088 | 2.91% |
| `5` | 레저/스포츠 관련 시설(스키, 카트, 수상레저) | **`tourism_core`** | 1,276 | 153 | 1,429 | 1.02% |
| `6` | 테마시설(놀이공원, 워터파크) | **`tourism_core`** | 1,938 | 252 | 2,190 | 1.56% |
| `7` | 산책로, 둘레길 등 | **`tourism_core`** | 2,833 | 325 | 3,158 | 2.25% |
| `8` | 지역 축제/행사 | **`tourism_core`** | 796 | 91 | 887 | 0.63% |
| `12` | 기타 *(원문 `cd_nm = '기타'`)* | **`tourism_core`** | 1,989 | 265 | 2,254 | 1.60% |
| `13` | 체험 활동 관광지 | **`tourism_core`** | 3,242 | 383 | 3,625 | 2.58% |
| **소계 (`tourism_core`)** | **9개 유형 (`1..3, 5..8, 12, 13`)** | **`tourism_core`** | **32,434** | **4,009** | **36,443** | **25.93%** |
| `11` | 식당/카페 | `non_tourism` | 31,990 | 3,862 | 35,852 | 25.51% |
| `21` | 집 | `non_tourism` | 18,871 | 2,314 | 21,185 | 15.07% |
| `9` | 역, 터미널, 고속도로 휴게소 | `non_tourism` | 12,700 | 1,516 | 14,216 | 10.11% |
| `24` | 숙소 | `non_tourism` | 11,745 | 1,438 | 13,183 | 9.38% |
| `4` | 상업지구(거리, 시장, 쇼핑시설) | `non_tourism` | 9,443 | 1,188 | 10,631 | 7.56% |
| `10` | 상점 | `non_tourism` | 4,217 | 551 | 4,768 | 3.39% |
| `22` | 친구/친지집 | `non_tourism` | 3,146 | 421 | 3,567 | 2.54% |
| `23` | 사무실 | `non_tourism` | 628 | 82 | 710 | 0.51% |
| **소계 (`non_tourism`)** | **8개 비관광/일상 유형 (`4, 9..11, 21..24`)** | **`non_tourism`** | **92,740** | **11,372** | **104,112** | **74.07%** |

---

## 7. 사실 / 해석 / 결정 / 미결정 정리

### 확인된 사실 (Facts)

1. **구조적 키 무결성 및 `TC_CODEB` 일치**: 4개 권역 8개 분할(TL/VL) 전체에서 `TN_TRAVEL`의 고유 여행 11,520건은 모두 `TN_TRAVELLER_MASTER`의 유일한 `TRAVELER_ID`에 100% 매핑되며(`ambiguous_traveler = 0`), `TN_VISIT_AREA_INFO`의 140,555개 방문 행도 모두 유효한 `TRAVEL_ID`에 100% 매핑된다(`unmapped_trip = 0`). 각 권역의 TL과 VL 사이 `TRAVEL_ID` 중복은 **0건**이며, 8개 분할의 `TC_CODEB`(`cd_a = 'VIS'`) 17개 코드 정의도 권역 간 불일치 없이 **100% 동일**하다.
2. **`POI_ID` 결측과 비관광 방문의 관계**: 원시 방문 이벤트 140,555건 중 `POI_ID`가 비어 있는 행은 **31,684건(22.54%)**이다. 순수 관광 방문 이벤트(36,443건) 중에서는 33,947건(**93.15%**)이 비결측 `POI_ID`를 보유한 반면, 집(`21`) 등 비관광 방문 이벤트(104,112건)에서는 비결측 `POI_ID` 보유 비율이 74,924건(**71.96%**)으로 낮다.
3. **핵심 문맥 완비율**: 5대 핵심 문맥 그룹 중 `STYLE`(8개), `DESTINATION`(2개), `COMPANION`(2개), `TEMPORAL`(2개, 역전 날짜 0건)은 전체 11,520개 여행에서 **100.00%** 완비되어 있다. `MOTIVE`(3개 문항 모두 유효)만 10,673개 여행(**92.65%**)에서 완비되어 전체 `primary_context_complete` 비율을 결정한다.
4. **아이템 속성 가용성 차이**: 순수 관광 코호트(`trip_poi_grain` 32,893건)에서 `TN_POI_MASTER` 유일 조인율은 **77.72%**(25,563건)로 전체 방문(72.47%, 70,756/97,640건)보다 5.25%p 높다. 반면 `SGG_CD`는 방문 테이블 단독으로는 1.26%(414/32,893건), 마스터 테이블 통합 시 **24.48%**(8,054/32,893건)에서만 채워져 있으며, 마스터의 세분류 3종과 `SGG_CD`가 모두 채워진 `rich_complete` 비율은 **2.69%**(886/32,893건, VL 총 101건: 수도권 33, 서부 10, 동부 29, 제주 29)다.
5. **순수 관광 코호트의 콜드 스타트 감소**: VL 관측 양성이 TL 학습 분할에 한 번도 등장하지 않은 아이템 콜드 스타트 비율은 전체 방문 기준 **35.99%**(수도권 51.68%)에서 순수 관광 코호트 기준 **25.35%**(수도권 34.94%, 제주 20.18%)로 낮아진다.

### 해석 (Interpretation)

- 일회성 식당·카페·집·상점 방문을 포함한 전체 방문(`all_valid_visits`)에서는 재방문 빈도가 낮고 일회성 장소 비중이 높아 VL 아이템 콜드 스타트 비율이 높게 관측된다(35.99%). 순수 관광 코호트(`tourism_core_cohort`)로 분리하면 관측된 VL 콜드 스타트 비율이 25.35%로 10.64%p 낮아지는 비율 차이가 확인된다. 다만 이러한 분포 변화가 실제 오프라인 순위 모델의 일반화 성능과 지지력(support) 향상으로 이어지는지는 후속 모델링 실험에서 별도로 검증해야 한다.
- 속성 기반 학습(`f(X_context, X_item)`)은 미매칭 TourAPI 후보를 다루기 위한 필수 조건이지만, 현재 AI Hub 원천에서 `SGG_CD`(통합 24.48%)와 `TN_POI_MASTER` 세분류(`rich_complete` 2.69%)의 결측 비중이 높고 카테고리 교차 매핑표(crosswalk)가 아직 정의되지 않았으므로, **현 시점에서 곧바로 모든 미매칭 TourAPI 후보에 정밀한 속성 점수를 부여할 수 있다고 주장해서는 안 된다.**

### 결정 (Decisions)

1. **TourAPI 매칭 독립 원칙 확정**: 추천 모델의 학습 관측치 포함 여부는 TourAPI 매칭 상태(`MATCHED`, `AMBIGUOUS`, `UNMATCHED`)로 필터링하지 않는다.
2. **식별자(Key)와 기계학습 입력 특성(Feature) 경계 확정**: `POI_ID`와 `contentid`(및 `TRAVELER_ID`, `TRAVEL_ID`, `VISIT_AREA_ID`)는 조인·집계·중복 제거·후보 식별용 구분자(key)로는 사용할 수 있으나, 기계학습 모델의 입력 특성(feature)으로는 사용하지 않는다.
3. **2대 기준 코호트 병행 보고 및 `TC_CODEB` 검증 의무화**: 관광지 추천 모델의 기본 학습·평가 양성 타깃은 `tourism_core_cohort`(32,893건, 코드 `12 기타`를 포함하는 현재 설계 결정)로 하되, 모든 실험에서 `all_valid_visits`(97,640건) 대비 제외 사유와 분모를 함께 보고하며 `TC_CODEB`(`cd_a = VIS`) 공식 코드명 검증을 유지한다.

### 미결정 및 후속 과제 (Unresolved)

- AI Hub `VISIT_AREA_TYPE_CD` / `ASORT_*`와 TourAPI `contenttypeid` / `lclsSystm1..3` 간의 공식 카테고리 교차 매핑표(crosswalk) 설계
- `VISIT_AREA_TYPE_CD = "12"`(`TC_CODEB` 원문 `'기타'`, 단독 양성 1,774건) 포함/제외 민감도 점검
- `SGG_CD` 결측(75.52%) 처리 및 미매칭 TourAPI 후보(85.55%)의 인기도 콜드 스타트 기본값(prior) 설계
- 순수 관광 코호트 위에서의 음성 표본 추출(negative sampling) 프로토콜 및 문맥 결합 순위 모델 대 인기도 기준선 비교 실험

---

## 8. 재현 및 검증 명령

합성 단위 테스트 및 설계 감사 테스트 실행:

```bash
uv run python -m unittest discover -s tests -p 'test_*.py' -v
uv run python -m py_compile \
  scripts/recommendation/training_data_contract.py \
  scripts/recommendation/experiment_design_audit.py \
  tests/test_training_data_contract.py \
  tests/test_experiment_design_audit.py
```

> **기존 실제 데이터 감사 실행 메타데이터**:
> - 기존 산출물 실행 ID: `issue71-training-contract-20261020T1550Z`
> - 기존 산출물 script_sha256: `be3247e07e90d179375cb5ac5c427e15d11dfc88db291f6a41cfa9212b3f02a6`
> - **참고**: 현재 작업트리의 스크립트는 리뷰어 피드백(코드 캐시 키 보완, 주석·문서 정합화 등) 반영으로 소스 해시가 다르며, 이번 단계에서는 원본 데이터 접근 제한 원칙에 따라 실제 데이터 재감사를 실행하지 않고 합성 단위 테스트로만 검증했다.

승인된 환경에서 4개 권역 실제 데이터 코호트 및 `TC_CODEB`(`VIS`) 감사를 재실행하는 명령 (환경 변수 `CAPITAL_TL` 등 바인딩 필요, 원시 경로나 식별자는 출력되지 않음):

```bash
uv run python scripts/recommendation/training_data_contract.py \
  --run-id "issue71-training-contract-repro"
```

---

## 9. Legacy TravelMate 구조 복원 및 필드 매핑 근거 (Issue #17 보존)

> 아래 절은 Issue #17에서 수행한 기존 TravelMate 공개 코드(`travelmate-model`, `travelmate-backend`) 구조 복원 및 AI Hub 필드 대응 검토 기록을 역사적 근거로 보존한다.

### 9.1 기존 TravelMate 구조 및 복원

**[코드 사실 — 의도된 설계]** 공개 `travelmate-model`의 `app/preprocessing.py`는 `gender`, `age_grp`, `start_month`를 one-hot encode하고 `content_id` 방문 pivot으로 `traveler_id` × `content_id` 방문 행렬을 만든다. 코드는 profile 기반 user-user similarity에 0.7, 방문 기반 user-user similarity에 0.3을 곱해 더하려는 연산을 작성한다.

**[구현 결함 후보 — 실제 코드]** 두 similarity dataframe은 각각 본래 traveler × traveler 축이다. 그러나 유효 사용자 필터 단계에서 두 dataframe을 `index=visit_matrix.index`, `columns=visit_matrix.columns`로 재색인하며, `visit_matrix.columns`는 traveler가 아니라 `content_id`다. 따라서 결과 column 축이 content 축으로 바뀌거나 label 교집합에 의존하게 되어, 0.7/0.3 결합 결과가 의도한 user-user similarity matrix라고 확정할 수 없다.

`app/recommendation.py`는 이 결합 결과의 행을 user-user similarity처럼 읽어 정렬된 label을 얻으려 한다. similarity 값의 수가 dataframe index보다 많으면 정렬 위치를 index에 적용하는 단계에서 실패할 수 있고, 성공하면 `similar_users`에는 traveler index label이 들어간다. `app/main.py`는 방문 행렬을 NumPy 배열로 변환해 추천 함수에 넘기지만, 추천 함수는 먼저 `visit_matrix.to_numpy(...)`를 호출하므로 공개 호출 경로는 그 지점에서 자료형 오류가 발생한다. DataFrame이 직접 전달되는 경우에도 함수는 이를 NumPy 행렬로 바꾼 뒤 traveler ID label을 `visit_matrix_np[similar_users]`의 행 위치로 사용하므로 ID와 위치가 같다는 보장이 없다. 또 `similar_users`는 similarity 값의 argsort 순서로 정렬하지만, 가중 합에는 정렬 전 `similarity_values[:len(similar_users)]`를 사용해 사용자와 점수의 순서가 어긋날 수 있다. 이후 콘텐츠 기반 경로는 원래 `visit_matrix`의 `.loc`를 기대한다. 따라서 축·label·순서·자료형의 불일치가 있으며, 이 문서는 legacy 추천 흐름의 정상 실행이나 추천 품질을 검증하지 않았다.

**[새 시스템 결정]** 0.7/0.3 가중치, 이 similarity 계산 방식, legacy one-hot preprocessing을 새 baseline에 이전하지 않는다. Legacy 코드는 과거 구현을 복원하는 참고 자료이지 새 데이터 계약이나 알고리즘의 정답이 아니다.

**[코드 사실 — 소비 의도]** `app/recommendation.py`에는 유사 사용자 방문과 `content_embeddings`를 함께 읽으려는 추천 경로가 있다. 이는 collaborative interaction과 item-content를 결합하려는 구조를 보여줄 뿐, 위에서 확인한 축·호출 불일치가 있는 코드의 정상 실행이나 추천 품질을 입증하지 않는다. embedding 생성 provenance나 AI Hub 필드 대응도 확인되지 않았다.

**[코드 사실]** `travelmate-model/app/schema.py`와 `models.py`는 `Preference` 입력(여행 스타일 1–7 및 동반자 포함)과 `Visited(traveler_id, content_id)`를 정의한다. `travelmate-backend`의 `Preference.java`는 traveler relation, 인구통계, 여행 날짜, 스타일 1–7 및 동반자를 보유하며, `Visited.java`는 traveler와 `contentId`를 보유한다. `TourSpot.java`의 `contentId`는 TourAPI content ID이고, 분류·지역/구역·테마 metadata가 함께 정의된다.

**[코드 사실]** backend `PreferenceDTO.java`에는 `regionId`가 있고 `RecommendController`는 survey 입력을 받아 preference를 저장한 뒤 모델에 user id와 region을 전달한다. 별도 save-visited endpoint는 방문을 저장한다. 따라서 legacy 추천 요청의 user/region/preferences context와 방문 기록은 구분된다.

### 9.2 Legacy → AI Hub 필드 매핑 및 유지·변경·폐기 요약

| Legacy field / artifact | Legacy role | AI Hub 2023 source candidate | 새 시스템 처리 (Issue #17 → #71 확정) | 근거 / 제한 |
| --- | --- | --- | --- | --- |
| `Preference.gender`, `age_grp` | 사용자 survey profile | `TN_TRAVELLER_MASTER.GENDER`, `AGE_GRP` | **배제(기본 입력 제외):** 최소 수집·동의·공정성 정책 확정 전까지 기본 추천 입력에서 제외 | 네 schema는 두 열을 선택 항목으로 정의 |
| `Preference.travel_style_1..7` | 선호 context | `TN_TRAVELLER_MASTER.TRAVEL_STYL_1..8` | **유지/확장:** 8개 문항(도메인 `1..7`)을 `STYLE` 핵심 문맥 그룹으로 사용하되 기존 1–7과 직접 동등시하지 않음 | 4권역 여행 단위 완비율 100.00% |
| legacy companion fields | trip companion context | `TRAVEL_STATUS_ACCOMPANY`, `TRAVEL_COMPANIONS_NUM`, `TN_COMPANION_INFO.REL_CD` | **변경:** 동반 현황과 동반자 수는 `COMPANION` 핵심 문맥으로 채택, `REL_CD`는 `recorded_only` 민감도 분석으로 분리 | 동반자 테이블 미기록과 1인 여행 구분 한계 반영 |
| `Preference.regionId` / request region | 요청 지역 context | `region` 스코프, `TRAVEL_STATUS_DESTINATION`, `SGG_CD` | **변경:** `region`은 `poi-catalog-policy-v1.json`으로 TourAPI와 100% 매핑; `SGG_CD`는 `SggCrosswalk`로 법정동 호환되나 AI Hub 측 결측(75.52%) 고려 필요 | 권역 호환 확립, 시군구는 결측 허용 처리 필요 |
| `Visited(traveler_id, content_id)` | user-item 방문 interaction | `(region, TRAVEL_ID, POI_ID)` (`trip_poi_grain`) | **변경:** `POI_ID`와 `contentid`는 조인·집계·후보 식별용 구분자(key)로만 쓰고 기계학습 입력 특성(feature)에서 제외하며 학습 자격은 TourAPI 매칭과 독립으로 유지 | 외부 카탈로그 연결과 학습 관측치 자격의 분리 |
| `TourSpot` categories, region/district/theme | item metadata | `VISIT_AREA_TYPE_CD`, `SGG_CD`, `TN_POI_MASTER.ASORT_*` | **변경:** `VISIT_AREA_TYPE_CD`로 `tourism_core_cohort`를 분리하고 오프라인 속성 학습에 사용 | 미매칭 TourAPI 후보 서빙에 쓰려면 별도 카테고리 crosswalk 정의 선행 필요 |
| `content_embeddings` | item content representation | SbL `caption.IMG_CAPTION`, 원시 이미지 | **폐기:** 기존 임베딩 미이식, 원시 이미지 및 캡션 텍스트는 기본 계약에서 제외 | 생성 출처 미확인 및 서빙 시점 호환성 미검증 |
| profile 0.7 + visit 0.3 similarity | user-user recommendation score 의도 | 해당 없음 | **폐기:** 가중치와 계산 방식을 새 시스템으로 이전하지 않음 | 재색인 축 오류 확인 |

---

## Appendix A. Public legacy source references

Code evidence refers to the published repository files below, pinned to the model commit `097fca72b9c4299f70bdec30730ba7342710bbf7` and backend commit `0f63c6ec9a754aafc5cb8b1eb847209f034f37cb`. The links establish implementation locations; they do not prove AI Hub field semantics, model quality, successful runtime behavior, or an external data license. In particular, the preprocessing source contains a 0.7/0.3 weighted-combination expression, but its reindexing uses the content axis for similarity columns, so the result is not established as a valid user-user matrix.

| Evidence | Exact public source path |
| --- | --- |
| Profile and visit similarity construction, intended 0.7/0.3 combination, and traveler/content reindexing | [`travelmate-model/app/preprocessing.py`](https://github.com/9roomthon-TravelMate/travelmate-model/blob/097fca72b9c4299f70bdec30730ba7342710bbf7/app/preprocessing.py) |
| Consumption of the combined dataframe as user similarity, visit-matrix indexing, and `content_embeddings` recommendation | [`travelmate-model/app/recommendation.py`](https://github.com/9roomthon-TravelMate/travelmate-model/blob/097fca72b9c4299f70bdec30730ba7342710bbf7/app/recommendation.py), [`travelmate-model/app/main.py`](https://github.com/9roomthon-TravelMate/travelmate-model/blob/097fca72b9c4299f70bdec30730ba7342710bbf7/app/main.py) |
| Model Preference / Visited schema | [`travelmate-model/app/schema.py`](https://github.com/9roomthon-TravelMate/travelmate-model/blob/097fca72b9c4299f70bdec30730ba7342710bbf7/app/schema.py), [`travelmate-model/app/models.py`](https://github.com/9roomthon-TravelMate/travelmate-model/blob/097fca72b9c4299f70bdec30730ba7342710bbf7/app/models.py) |
| Backend `Preference`, `Visited`, and `TourSpot` entities | [`travelmate-backend/src/main/java/travelmate/backend/entity/Preference.java`](https://github.com/9roomthon-TravelMate/travelmate-backend/blob/0f63c6ec9a754aafc5cb8b1eb847209f034f37cb/src/main/java/travelmate/backend/entity/Preference.java), [`Visited.java`](https://github.com/9roomthon-TravelMate/travelmate-backend/blob/0f63c6ec9a754aafc5cb8b1eb847209f034f37cb/src/main/java/travelmate/backend/entity/Visited.java), [`TourSpot.java`](https://github.com/9roomthon-TravelMate/travelmate-backend/blob/0f63c6ec9a754aafc5cb8b1eb847209f034f37cb/src/main/java/travelmate/backend/entity/TourSpot.java) |
| Request DTO / recommend flow | [`travelmate-backend/src/main/java/travelmate/backend/dto/PreferenceDTO.java`](https://github.com/9roomthon-TravelMate/travelmate-backend/blob/0f63c6ec9a754aafc5cb8b1eb847209f034f37cb/src/main/java/travelmate/backend/dto/PreferenceDTO.java), [`RecommendController.java`](https://github.com/9roomthon-TravelMate/travelmate-backend/blob/0f63c6ec9a754aafc5cb8b1eb847209f034f37cb/src/main/java/travelmate/backend/controller/RecommendController.java) |
| Save-visited persistence flow | [`travelmate-backend/src/main/java/travelmate/backend/service/RecommendationService.java`](https://github.com/9roomthon-TravelMate/travelmate-backend/blob/0f63c6ec9a754aafc5cb8b1eb847209f034f37cb/src/main/java/travelmate/backend/service/RecommendationService.java) |

**Source verification:** the cited `preprocessing.py`, `recommendation.py`, `main.py`, and `crud.py` contents were re-read at model commit `097fca72b9c4299f70bdec30730ba7342710bbf7`; backend references remain pinned to `0f63c6ec9a754aafc5cb8b1eb847209f034f37cb`. The similarity-axis and downstream-consumption statements above describe code structure and possible failure/misalignment, not a reproduced runtime result.
