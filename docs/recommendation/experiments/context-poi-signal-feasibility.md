# 여행 문맥 × POI 추천 신호 타당성 검증

**관련 Issue:** [#45](https://github.com/haeinChoe/Travel-Recommendation/issues/45)  
**현재 상태:** 교정 프로토콜 4개 권역 재실행 완료 / **판정 보류(Inconclusive)**

## 한눈에 보기

### 이 문서가 답하려는 질문

2023 AI Hub 국내 여행로그에서 **여행 문맥(context)**이 어떤 POI를 방문하는지와 관련된 신호를 제공하는지, 그리고 그 신호가 단순한 권역·인기도·POI 분류 정보보다 추가적인 예측 가치를 갖는지 확인한다.

이 실험은 문맥 신호의 **탐색적·예측적 타당성**을 보는 실험이다. Top-K 추천 순위 품질이나 인과 효과를 직접 평가하지 않는다.

### 결론

여행 스타일, 동기, 목적지, 동반자, 시기 정보와 POI 특성 사이의 연관성(association)은 TL과 VL에서 관측됐다. 그러나 aggregate 평가에서 핵심 문맥 그룹 어느 것도 다수 클래스 기준 모델보다 방문 후 피드백 예측을 개선하지 못했다.

권역, 인기도, 넓은 POI 카테고리를 먼저 사용한 뒤 문맥을 추가해도 개선이 관측되지 않았고, 문맥과 POI를 결합한 joint feature의 중앙 증분도 모든 그룹·대상에서 음수였다. 더 풍부한 POI 메타데이터의 추가 가치는 VL의 complete-case 지원 수가 `<10`이라 개인정보 보호 기준상 판단할 수 없었다.

따라서 **문맥과 POI 사이에 신호가 있다는 사실을 곧바로 추천 순위 성능 개선의 근거로 사용하지 않는다.**

### 현재 결정된 것

- 이 결과만으로 문맥 기반 순위 모델로 진행한다고 결정하지 않는다.
- 방문 후 만족도·재방문 의향·추천 의향은 추천 시점 입력 특성으로 사용하지 않는다.
- 미방문 POI를 자동으로 음성(negative)으로 만들지 않는다.
- 기본 `poi_only` 비교와 richer POI 비교를 분리한다.
- 연관성, 예측 가치, 인과 효과, 추천 순위 품질을 서로 다른 주장으로 취급한다.

### 아직 결정되지 않은 것

- 문맥이 실제 Top-K POI 순위를 개선하는지
- 최종 후보 집합(candidate set)과 미방문 항목의 평가 의미
- canonical POI identity
- richer POI 메타데이터의 실제 추가 가치
- 운영 시 사용할 특성과 UI에서 받을 여행 문맥
- Two-Tower, LambdaMART 등을 포함한 최종 모델 선택

### 다음 행동

추천 순위 평가에 사용할 후보 집합과 평가 계약을 먼저 고정한 뒤, 충분한 VL 지원을 확보한 상태에서 단순 기준 모델과 문맥 기반 순위 모델을 같은 조건으로 비교한다. richer POI의 추가 가치는 개인정보 보호 기준을 만족하는 검증 코호트가 확보된 경우에만 다시 판단한다.

> 이전 실행 `issue45-context-poi-pairs-20261012T141933Z-c6a1b9`은 예비 근거(preliminary evidence)로만 보존한다. 아래 상세 결과는 POI-only 비교를 바로잡은 `issue45-context-poi-poionly-20261013T040619Z-9519be`를 기준으로 한다.

## 필요한 용어

공통 추천 용어는 [추천 시스템 용어 사전](../glossary.md)을 따른다.

- **여행 문맥(context)**: 한 번의 여행이나 추천 요청에 관련된 여행 스타일, 동기, 목적지, 동반자, 시기 등의 정보
- **연관성(association)**: 두 변수가 함께 달라지는 통계적 관계. 인과관계나 추천 성능 개선을 뜻하지 않는다.
- **추가 예측 가치(incremental predictive value)**: 이미 사용한 정보에 새 특성을 더했을 때 같은 평가 조건에서 예측 성능이 추가로 개선되는 정도
- **특성 제거 비교(ablation)**: 특정 특성 또는 특성 그룹을 포함·제외한 모델을 비교해 그 정보의 기여를 확인하는 실험
- **complete-case**: 비교에 필요한 모든 필드가 존재하는 관측치만 사용한 코호트
- **main effects / joint feature**: 문맥과 POI를 각각 넣은 기준과 두 값을 결합한 범주형 특성을 추가한 비교
- **richer POI**: 기본 권역·방문 유형·시군구보다 더 세부적인 POI master 분류 메타데이터를 사용한 표현
- **privacy-limited**: 지원 수가 개인정보 보호 공개 기준보다 작아 지표를 공개하거나 결론에 사용할 수 없는 상태

## 1. 이 실험이 답하려는 세부 질문

2023 AI Hub 국내 여행로그에서 다음을 구분해서 확인한다.

1. 여행 문맥 자체에 POI 선택과 관련된 신호가 있는가?
2. 어떤 문맥 특성 또는 특성 그룹의 신호가 TL에서 관측되고 VL에서도 재현되는가?
3. 문맥과 POI를 함께 볼 때 각각을 따로 사용한 경우보다 추가 예측 가치가 있는가?
4. 권역(region), 인기도(popularity), 넓은 POI 카테고리 같은 단순 신호를 고려한 뒤에도 문맥이 추가 정보를 주는가?
5. 기본 POI 정보보다 더 풍부한 POI 메타데이터가 추가 정보를 주는가?

실험 경계:

- TL: 탐색·학습(discovery / training)
- VL: 외부 재현·검증(external replication / validation)
- TL/VL 무작위 재분할 없음
- 미방문 POI를 음성으로 만들지 않음
- 추천 순위 지표는 이 실험 범위가 아님
- 인과 효과, 운영 ranking 품질, 최종 serving contract를 확정하지 않음

## 2. 실제 여행 문맥 특성 계약

### 2.1 핵심 여행 문맥

`context_only`과 context-group predictive ablation에 들어가는 핵심 context는 아래와 같습니다.

| Group | Feature | 데이터상 의미 | 실험 처리 |
| --- | --- | --- | --- |
| Style | `TRAVEL_STYL_1~8` | 여행스타일 1~8, 코드 그룹 `TSY` | 각 필드 association + style group predictive ablation |
| Motive | `TRAVEL_MOTIVE_1~3` | 여행동기 1~3, 코드 그룹 `TMT` | 각 필드 association + motive group predictive ablation |
| Destination | `TRAVEL_STATUS_DESTINATION` | 여행현황-목적지 | 개별 association + destination group |
| Destination | `region` | Capital / West / East / Jeju 권역 | aggregate association + primary context |
| Companion | `TRAVEL_STATUS_ACCOMPANY` | 여행현황-동반현황 | 개별 association + companion group |
| Companion | `TRAVEL_COMPANIONS_NUM` | 여행동반자 수 | 개별 association + companion group |
| Temporal | `month` | `TRAVEL_START_YMD`에서 파생한 시작 월 | 개별 association + temporal group |
| Temporal | `elapsed_days` | `TRAVEL_END_YMD - TRAVEL_START_YMD` | 개별 association + temporal group |

원시 코드의 세부 의미가 문서로 확정되지 않은 경우 값은 opaque category로 취급합니다.

### 2.2 동반자 관계: 기록된 경우만 보는 민감도 분석

`TN_COMPANION_INFO.REL_CD`에서 만든 `companion_relation_codes`는 별도 분석합니다.

**Primary `context_only`에서는 제외합니다.**

companion row가 없다는 것이 혼자 여행했다는 뜻인지, 단순 미기록/결측인지를 현재 계약이 구분하지 못합니다.
이를 `None`으로 둔 채 primary complete-case 모델에 포함하면 relation이 기록된 여행만 남는 selection effect가 생길 수 있습니다.

따라서:

- context ↔ POI association: 수행
- feature ↔ feedback association: 수행
- `context_companion_relation_recorded`: recorded-only predictive sensitivity
- primary `context_only`: 제외

### 2.3 제외 특성

| Feature | 이유 |
| --- | --- |
| `TRAVEL_MISSION`, `TRAVEL_MISSION_CHECK` | 의미/표현 계약 미해결 |
| raw `TRAVEL_START_YMD`, `TRAVEL_END_YMD` | 정확 날짜는 predictor로 사용하지 않고 month / elapsed_days만 파생 |
| `season` | 문서화된 mapping 미확정 |
| `GENDER`, `AGE_GRP` | demographic은 별도 서술 분석 |
| `TRAVELER_ID`, `TRAVEL_ID`, `POI_ID` | join/group key이며 predictor가 아님 |
| post-event feedback | leakage 방지를 위해 input 금지 |

## 3. POI 표현

### 기본 POI

- `region`
- `VISIT_AREA_TYPE_CD`
- 방문 `SGG_CD`

### 확장 POI

유일한 region-scoped candidate join이 가능한 경우에 한해:

- POI master `SGG_CD`
- `ASORT_LCLASDC`
- `ASORT_MLSFCDC`
- `ASORT_SDASDC`

`POI_ID` 연결은 exploratory candidate join이며 canonical PK/FK 또는 권역 간 동일 장소 identity로 주장하지 않습니다.

## 4. 실험 설계

### 단계 0 — 특성 가용성과 연결 상태 점검

`availability_audit.csv`에서 각 context/POI feature의 권역 × TL/VL별 다음 항목을 기록합니다.

- rows / nonmissing
- missing-rate band
- cardinality band
- category support
- POI join coverage / duplicate / collision

최종 보고서에는 대체로 충분하다는 문장만 쓰지 않고 **feature group별 availability**를 표로 요약합니다.

### 단계 1 — 개별 여행 문맥 ↔ POI 연관성

`associations.csv`의 `analysis=context_to_poi`는 context feature만 대상으로 생성합니다.

예:

- `TRAVEL_STYL_1 × VISIT_AREA_TYPE_CD`
- `TRAVEL_MOTIVE_2 × visit_SGG_CD`
- `month × VISIT_AREA_TYPE_CD`
- `elapsed_days × POI_master_ASORT_LCLASDC`

각 결과는 support, Cramér's V, chi-square p-value를 기록하고 TL→VL replication을 확인합니다.
`visit-row`와 `distinct-trip-pair` grain을 분리합니다.

`region`은 primary context에 포함하지만 단일 권역에서는 상수이므로 `insufficient-support`가 정상이며 aggregate scope에서 직접 봅니다.

### 단계 2 — 개별 효과와 결합 특성의 추가 예측 가치

기존 `joint_context_poi_to_feedback` Cramér's V는 결합 범주의 association이지 통계적 interaction effect가 아닙니다.

교정 run에서는 `joint_feature_sensitivity.csv`를 추가합니다. 각 context × POI × feedback target에 대해 동일 complete-case TL/VL 관측치에서:

1. main-effects model: context + POI
2. joint-feature model: context + POI + `(context, POI)` joint categorical feature

를 비교합니다.

보고값:

- `main_effect_accuracy`
- `joint_feature_accuracy`
- 각 모델의 majority baseline 대비 Δ
- `delta_joint_vs_main`
- TL/VL support

이 값은 **joint feature의 추가 predictive value**이지 causal interaction 또는 회귀 interaction coefficient가 아닙니다.

### 단계 3 — 여행 문맥 그룹별 특성 제거 비교

`predictive_ablation.csv`에서 기존 전체 context뿐 아니라 다음 그룹을 각각 평가합니다.

- `context_style`
- `context_motive`
- `context_destination`
- `context_companion`
- `context_temporal`
- `context_companion_relation_recorded` — recorded-only
- `context_only` — primary context 전체

기존 비교도 유지합니다.

- `popularity_only`
- `poi_only`
- `context_plus_poi`
- `context_plus_richer_poi`

각 ablation은 자체 complete-case cohort를 사용하므로 서로 다른 ablation의 raw Δ를 직접 feature contribution으로 해석하지 않습니다.

### 단계 4 — 지배적 신호를 고려한 공통 코호트 비교

`common_cohort_sensitivity.csv`의 각 pair는 동일한 TL 학습 행과 동일한 VL 평가 행을 사용합니다.

| Comparison | Left | Right | 질문 |
| --- | --- | --- | --- |
| `region_vs_context` | region only | full context | region보다 context가 추가 정보를 주는가? |
| `popularity_vs_context` | region + popularity | 동일 + context | popularity를 고려한 뒤 context가 추가 정보를 주는가? |
| `broad_category_vs_context` | broad POI category | 동일 + context | broad category보다 context가 추가 정보를 주는가? |
| `context_vs_poi` | context | context + basic POI | basic POI가 context에 추가 정보를 주는가? |
| `poi_vs_richer_poi` | context + basic POI | + richer POI | richer POI가 추가 정보를 주는가? |

Phase 1 association은 권역별로 따로 계산되므로 같은 region 내부에서도 context ↔ POI association이 남는지 확인할 수 있습니다.

## 5. 방문 후 피드백 목표값

서로 합치지 않고 별도 target으로 유지합니다.

- `DGSTFN`
- `REVISIT_INTENTION`
- `RCMDTN_INTENTION`

모두 post-visit outcome이며 input feature가 아닙니다.

## 6. 이번 교정에서 바뀐 점

| 이전 상태 | 교정 후 |
| --- | --- |
| association의 context와 predictive `context_only` 정의가 달랐음 | primary context contract 명시, `region` 포함 여부 정렬 |
| POI feature끼리도 `context_to_poi`로 섞일 수 있었음 | `context_to_poi`는 context feature에서만 생성 |
| companion relation 결측이 primary complete-case cohort를 축소 | relation은 recorded-only sensitivity로 분리 |
| 전체 context 하나만 predictive 평가 | style/motive/destination/companion/temporal group ablation 추가 |
| region/popularity/category를 각각 나열 | 동일 cohort incremental comparison 추가 |
| joint-category Cramér's V를 interaction처럼 읽을 위험 | main-effects vs explicit joint-feature sensitivity 추가 |

## 7. 개인정보 보호와 통계 보고

- raw row, raw identifier, exact date, coordinates, free text 공유 금지
- raw category value를 artifact에 기록하지 않음
- count: `0 / <10 / 10+`
- small support metric: `privacy-limited`
- 관측 불가/단일 범주: `insufficient-support`
- visit-row와 distinct-trip-pair를 구분
- p-value만으로 결론내리지 않음
- effect size, support, 권역별 패턴, TL→VL replication을 같이 봄

## 8. 산출물

새 run은 6개 artifact를 생성합니다.

| Artifact | 역할 |
| --- | --- |
| `availability_audit.csv` | feature availability / join audit |
| `associations.csv` | 개별 context↔POI, feature↔feedback, joint-category association |
| `predictive_ablation.csv` | context group 및 전체 feature-set predictive feasibility |
| `common_cohort_sensitivity.csv` | dominant signal / POI incremental pairwise 비교 |
| `joint_feature_sensitivity.csv` | context×POI joint feature 추가 predictive value |
| `run_metadata.json` | 데이터 역할, revision, protocol, privacy metadata |

## 9. 재실행 절차

이전 run을 덮어쓰지 않고 새 run ID를 사용합니다.

합성 검증:

```bash
python3 -m unittest tests.test_context_poi_feasibility -v
python3 -m py_compile scripts/recommendation/analyze_context_poi.py tests/test_context_poi_feasibility.py
git diff --check
```

실제 4권역 실행 전에는 현재 로컬 셸에서 `RAW_ROOT`, 4권역 TL/VL 변수와 각 권역 POI master 역할을 다시 확인합니다.
변수가 없을 때만 승인된 raw-root 후보를 제한 탐색하고 실제 경로 값은 공유 로그나 문서에 남기지 않습니다.

실행 예:

```bash
RUN_ID="issue45-context-poi-corrected-$(date -u +%Y%m%dT%H%M%SZ)"

python3 scripts/recommendation/analyze_context_poi.py \
  --raw-root "$RAW_ROOT" \
  --input "capital:TL=$CAPITAL_TL" --input "capital:VL=$CAPITAL_VL" \
  --input "west:TL=$WEST_TL" --input "west:VL=$WEST_VL" \
  --input "east:TL=$EAST_TL" --input "east:VL=$EAST_VL" \
  --input "jeju-islands:TL=$JEJU_TL" --input "jeju-islands:VL=$JEJU_VL" \
  --poi-master "capital=$CAPITAL_OTHER" \
  --poi-master "west=$WEST_OTHER" \
  --poi-master "east=$EAST_OTHER" \
  --poi-master "jeju-islands=$JEJU_OTHER" \
  --allow-approved-capital-filekey-folders \
  --run-id "$RUN_ID" \
  --confirm-approved --confirm-terms --confirm-poi-candidate
```

## 10. POI-only 비교 교정 실행 결과

- Run ID: `issue45-context-poi-poionly-20261013T040619Z-9519be`
- Code revision: base commit `205eafa3c71a5aa3d121ae0901c1b609f4180ec3`; the analysis ran with the POI-only correction in a dirty worktree. The run metadata records the matching analysis-script SHA-256 `b212e86fd812a383a204d5a9a1bb90b2e527255d1836e8e815a64d05982c9943`.
- 입력 역할: 2023 데이터의 네 권역별 TL/VL과 같은 권역의 승인된 POI Master. 무작위 재분할 없이 TL로 학습하고 VL에서 평가했습니다.
- 산출물: 여섯 artifact를 Git 제외 로컬 결과 위치에 생성했습니다. 원본 행, 원본 경로, raw ID·category value, 좌표와 자유 텍스트는 기록하지 않았습니다.
- 범위: 결과는 exploratory association 및 feedback 예측입니다. causal effect나 ranking 성능을 뜻하지 않습니다.
- 이 rerun은 `poi_only`를 basic POI(`region`, `visit_area_type`, `visit_sgg`)만 포함하도록 바로잡습니다. 이전 corrected run은 richer POI metadata까지 `poi_only`에 포함해 그 비교의 validation support를 privacy-limited로 만들었습니다. 다른 feature-set 계약은 바꾸지 않았습니다.
- Association 및 joint-feature artifact는 이전 corrected run과 동일하게 재생성됐습니다. 아래 association 및 joint-feature 결과는 새 run의 artifact에서 확인했으며, byte-for-byte 동일한 집계 결과입니다.

### A. 여행 문맥 가용성과 POI 연결

| Context group | 점검 결과 |
| --- | --- |
| Style | 8개 필드를 모두 4권역 TL/VL에서 점검. missing-rate band는 모두 `0-<10%`; 필드별 cardinality는 `<10` band. |
| Motive | 3개 필드를 모두 점검. missing-rate는 `0-<10%`부터 `10-<25%` 및 억제 band까지, cardinality는 `<10` 또는 `10+` band. |
| Destination | 목적지 필드를 8개 권역/split 역할에서 점검. missing-rate는 `0-<10%`; cardinality는 `<10` 또는 `10+` band. `region`은 aggregate context에 포함했습니다. |
| Companion | 동반현황과 동반자 수 두 필드를 모두 점검. missing-rate는 `0-<10%`; cardinality는 `<10` 또는 `10+` band. |
| Temporal | 시작·종료일 필드의 coarse availability를 점검하고 month와 elapsed days를 파생했습니다. missing-rate는 `0-<10%`, cardinality는 `10+` band였습니다. 정확한 날짜는 predictor나 artifact에 기록하지 않았습니다. |
| Companion relation | 네 권역 TL/VL 모두 relation 필드를 점검했습니다. 기록된 관계가 있는 관측만 sensitivity에 사용했으며 primary context에서 제외했습니다. |

POI master candidate join coverage는 capital, west, east에서 TL과 VL 모두 `50-<75%`, jeju-islands에서 두 split 모두 `75-<90%`였습니다. 네 권역 모든 split에서 master의 duplicate candidate key와 서로 다른 행정구역 값을 가진 key는 각각 `0` bucket이었습니다. Join은 region-scoped `POI_ID` 후보 관계이며 canonical identity가 아닙니다.

Issue #4의 [POI catalog / candidate contract](../poi-catalog-candidate-contract.md)는 이 집계를 **과거 `TN_POI_MASTER` 참조 커버리지**로 한정한다. 이 값은 TourAPI 식별 커버리지나 제품 후보 자격을 나타내지 않는다.

Issue #4 후속 진단에 사용한 네 권역별 `TN_POI_MASTER` 후보 파일은 사용자가 승인된 파일이라고 명시적으로 확인했다. 이 확인은 해당 진단의 입력 승인을 확정하지만, 위 과거 집계를 canonical identity나 TourAPI 제품 후보 커버리지로 바꾸지는 않는다.

### B. 여행 문맥–POI 연관성과 TL→VL 재현

아래 값은 지원이 공개 가능한 association에서 context-feature × POI-feature Cramér's V의 중앙값입니다. TL/VL 각 split 안에서 feature 조합을 합치지 않고, visit-row와 distinct-trip-pair를 따로 계산했습니다.

| Group | Visit-row TL / VL | Distinct-trip-pair TL / VL | 관찰 |
| --- | ---: | ---: | --- |
| Style | 0.054 / 0.120 | 0.052 / 0.125 | 네 권역에서 각 style feature의 POI association이 양 split에서 관찰됨. |
| Motive | 0.065 / 0.129 | 0.062 / 0.138 | 네 권역에서 각 motive feature의 POI association이 양 split에서 관찰됨. |
| Destination | 0.318 / 0.350 | 0.284 / 0.345 | 목적지 association이 양 split에서 관찰됨. `region` association은 aggregate에서만 평가했고 권역별로는 상수여서 `insufficient-support`였습니다. |
| Companion | 0.095 / 0.140 | 0.086 / 0.132 | 동반현황·동반자 수 association이 양 split에서 관찰됨. |
| Temporal | 0.164 / 0.231 | 0.129 / 0.219 | month·elapsed days association이 양 split에서 관찰됨. |

지원이 있는 조합의 association은 visit-row와 trip-pair 집계에서 비슷한 양상을 보였습니다. VL 중앙 effect가 TL보다 높았지만 Cramér's V는 방향을 나타내지 않고, 이 집계만으로 feature 조합의 예측 기여를 주장할 수 없습니다. 작은 지원으로 숨겨진 결과는 `privacy-limited`와 `insufficient-support`로 구분했습니다.

Context feature와 세 feedback target 간 association도 각각 계산했습니다. Aggregate에서 field별 Cramér's V 중앙값 범위는 style이 TL `0.046–0.051`, VL `0.049–0.052`; motive는 TL `0.019–0.021`, VL `0.040–0.045`; destination은 TL `0.023–0.027`, VL `0.044–0.047`; companion은 TL `0.025–0.026`, VL `0.050–0.053`; temporal은 TL `0.018–0.021`, VL `0.034–0.037`였습니다. 이 세 target은 합치지 않았습니다. Recorded-only relation은 TL `0.060–0.063`, VL `0.123–0.125`였지만, 기록된 동행 정보가 있는 사례로 제한된 sensitivity라 primary context와 같은 근거로 보지 않습니다.

### C. 피드백 예측 특성 제거 비교

값은 aggregate TL 학습 및 VL 평가에서 majority baseline 대비 accuracy 차이입니다. 각 칸은 `DGSTFN / REVISIT_INTENTION / RCMDTN_INTENTION` 순서입니다.

| Ablation | Δ vs majority | 해석 |
| --- | ---: | --- |
| `context_style` | `-0.018 / -0.026 / -0.029` | 세 target 모두 baseline보다 낮음. |
| `context_motive` | `0.000 / 0.000 / 0.000` | 추가 성능이 관찰되지 않음. |
| `context_destination` | `-0.003 / 0.000 / 0.000` | 추가 성능이 관찰되지 않음. |
| `context_companion` | `≈0.000 / ≈0.000 / 0.000` | 추가 성능이 관찰되지 않음. |
| `context_temporal` | `0.000 / 0.000 / 0.000` | 추가 성능이 관찰되지 않음. |
| `context_companion_relation_recorded` | `≈0.000 / -0.002 / -0.001` | Recorded-only sensitivity. |
| `context_only` | `-0.015 / -0.022 / -0.015` | primary context 전체가 majority baseline을 넘지 못함. |
| `poi_only` (basic POI) | `-0.017 / -0.022 / -0.009` | 세 target 모두 majority baseline보다 낮음; 새 비교의 aggregate TL/VL support는 `10+ / 10+`. |

위에서 수치가 공개된 aggregate ablation은 TL/VL 지원 `10+ / 10+`로 `observed`였습니다. `context_plus_richer_poi`는 VL complete-case 지원이 `<10`이라 metric이 `privacy-limited`로 억제됐습니다. 이는 데이터 지원이 0이라는 뜻이 아니며, 그 결과로 richer POI의 기여를 판단하지 않았습니다. `poi_only`가 이제 basic POI만 포함하므로 해당 비교는 privacy-limited가 아닙니다.

### D. 지배적 신호 통제와 확장 POI

아래 값은 새 POI-only correction run에서 같은 TL 학습 코호트와 같은 VL 평가 코호트로 다시 확인했습니다. 각 비교는 오른쪽 feature set의 accuracy에서 왼쪽을 뺀 값입니다. 양수는 오른쪽의 정확도 개선, 음수는 하락입니다.

| 비교 | DGSTFN | REVISIT | RCMDTN | 결과 |
| --- | ---: | ---: | ---: | --- |
| region → +context | -0.015 | -0.022 | -0.015 | region을 넘어서는 feedback 예측 개선이 없음. |
| popularity → +context | -0.020 | -0.020 | -0.016 | popularity 이후 context를 추가해도 개선되지 않음. |
| broad category → +context | -0.030 | -0.069 | -0.062 | broad category 이후 context를 추가해도 개선되지 않음. |
| context → +basic POI | +0.006 | +0.004 | -0.007 | 변화가 작고 target 간 일관된 개선이 없음. |
| basic POI → +richer POI | privacy-limited | privacy-limited | privacy-limited | VL complete-case 지원 `<10`; 기여 판단 불가. |

첫 네 비교의 지원은 각각 `10+ / 10+`였고 다섯 비교 모두 각 target에서 left/right 지원 bucket이 일치했습니다. Richer POI 비교는 `10+ / <10` 지원으로 억제됐으므로 `insufficient-support`와 혼동하지 않았습니다.

### E. 여행 문맥 × POI 결합 특성 민감도

값은 aggregate에서 같은 complete-case TL/VL 코호트의 `(context, POI)` joint categorical feature를 main-effects model에 추가했을 때의 accuracy 차이 중앙값입니다. 열은 `DGSTFN / REVISIT_INTENTION / RCMDTN_INTENTION` 순서입니다.

| Context group | Δ joint vs main 중앙값 |
| --- | ---: |
| Style | `-0.021 / -0.018 / -0.020` |
| Motive | `-0.010 / -0.009 / -0.009` |
| Destination (region 포함) | `-0.014 / -0.025 / -0.020` |
| Companion (primary fields) | `-0.013 / -0.017 / -0.017` |
| Temporal | `-0.007 / -0.011 / -0.004` |
| Companion relation (recorded-only) | `-0.021 / -0.036 / -0.034` |

필수 context group의 aggregate 조합은 모두 `observed`였습니다. Feature별 범위 일부에 양수 값이 있어도 각 group/target의 중앙값은 음수였습니다. Joint feature는 예측 민감도 분석이며 causal interaction이 아닙니다.

### F. 예비 실행과의 비교

`issue45-context-poi-pairs-20261012T141933Z-c6a1b9`는 프로토콜 불일치가 있어 최종 판단 근거가 아닙니다. 이전 corrected run `issue45-context-poi-corrected-20261013T021312Z-acf6c4`도 basic `poi_only` 비교에 richer metadata를 포함했으므로 그 한 비교는 새 run으로 대체했습니다.

- Style, motive, companion, temporal association effect 분포는 preliminary와 corrected run에서 대체로 비슷했습니다. Destination 비교는 corrected contract에서 `region`을 추가해 비교 범위가 달라졌습니다.
- Preliminary `context_only`의 majority 대비 차이는 target 순서대로 `-0.019 / -0.026 / -0.032`; 새 run은 `-0.015 / -0.022 / -0.015`였습니다. 두 실행 모두 context-only feedback 예측의 이점은 관찰되지 않았습니다.
- Preliminary `context_vs_poi` paired 차이는 `+0.001 / -0.016 / -0.006`, 새 run은 `+0.006 / +0.004 / -0.007`입니다. 코호트·feature 계약이 교정되어 직접적인 성능 추세로 해석하지 않습니다.
- Preliminary run에는 region, popularity, broad-category 공통 코호트 비교가 없었습니다. 새 run에서는 세 비교 모두 context 추가 후 개선되지 않았습니다.
- 이전 corrected run의 `poi_only`는 richer metadata가 섞여 VL 지원 `<10`으로 privacy-limited였습니다. 새 basic-only `poi_only` 비교는 세 target 모두 VL 지원 `10+`이며 majority baseline보다 낮았습니다. `context_plus_richer_poi`와 `poi_vs_richer_poi` 오른쪽 비교는 여전히 `<10`으로 privacy-limited입니다.
- Association과 joint-feature sensitivity는 새 run에서도 이전 corrected run과 동일한 집계 결과입니다. Preliminary run에는 joint-feature sensitivity가 없어 비교할 값이 없습니다.

## 11. 판정 정리

### 확인된 사실

- 여행 스타일, 동기, 목적지, 동반자, 시기 문맥은 POI 특성과 TL 및 VL에서 연관성을 보였다.
- aggregate 평가에서 핵심 문맥 그룹 어느 것도 다수 클래스 기준 모델보다 방문 후 피드백 예측을 개선하지 못했다.
- 동일 코호트에서 권역, 인기도, 넓은 POI 카테고리에 문맥을 추가해도 개선되지 않았다.
- 문맥 × POI joint feature의 중앙 증분은 모든 그룹과 대상에서 음수였다.
- 기본 POI를 문맥에 추가한 변화는 작고 대상별 방향이 일관되지 않았다.
- richer POI 증분 비교는 VL complete-case 지원이 `<10`이어서 `privacy-limited`였다.
- 실제 Top-K ranking, 최종 후보 집합, 미방문 음성 정의는 이 실험에서 평가하지 않았다.

### 해석

문맥과 POI 사이에 통계적 연관성이 있다는 사실과, 그 문맥이 실제 추천 순위를 개선한다는 주장은 다르다. 이번 결과에서는 연관성은 관측됐지만 단순 신호를 넘어서는 일관된 추가 예측 가치는 확인되지 않았다.

또한 richer POI의 결과가 제한된 이유는 "효과가 없다"가 아니라 검증 지원 수가 개인정보 보호 기준보다 작아 판단할 수 없기 때문이다.

### 결정

**판정 보류(Inconclusive).**

현재 결과만으로 문맥 기반 ranking 진행 여부를 확정하지 않는다. 동시에 이 결과를 모델 방향의 폐기(Reconsider)로 해석하지도 않는다. 여러 문맥–POI 연관성이 TL/VL에서 관측됐고 richer POI 비교는 아직 충분한 검증 지원을 확보하지 못했기 때문이다.

### 미결정 / 추가 검증 필요

- 문맥이 Top-K POI ranking을 실제로 개선하는지
- 미방문 후보의 음성 정의
- 최종 후보 집합
- canonical POI identity
- 운영 추천 시점 특성
- UI에서 어떤 질문으로 여행 문맥을 받을지
- Two-Tower / LambdaMART 등 최종 모델 선택
- causal interaction

다음 판단에는 **추천 순위용 후보·평가 계약**과 충분한 richer-POI 검증 지원이 필요하다. 이 항목들은 교정 실행 결과를 바탕으로 후속 ranking/evaluation 작업과 #41에서 결정한다.
