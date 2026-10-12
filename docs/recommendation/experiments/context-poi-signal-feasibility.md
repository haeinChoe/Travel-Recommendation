# Context × POI 추천 신호 feasibility

**Issue:** [#45](https://github.com/haeinChoe/Travel-Recommendation/issues/45)  
**상태:** **프로토콜 교정 완료 / 실제 4권역 재실행 필요**

> 이전 run `issue45-context-poi-pairs-20261012T141933Z-c6a1b9`은 preliminary evidence로만 보존합니다.
> Issue #45의 질문과 실제 분석 계약이 완전히 정렬되지 않았으므로, 아래 교정 프로토콜의 새 run을 검토하기 전에는
> 이전 수치를 최종 Go / Inconclusive / Reconsider 판단에 사용하지 않습니다.

## 1. 이 실험이 답하려는 질문

2023 AI Hub 국내 여행로그에서 다음을 구분해서 확인합니다.

1. 여행 context 자체에 POI 선택과 관련된 신호가 있는가?
2. 어떤 context feature/group의 신호가 TL에서 관측되고 VL에서도 재현되는가?
3. context와 POI를 함께 볼 때 각각의 main effect보다 추가 predictive value가 있는가?
4. region, popularity, broad POI category 같은 단순 신호를 고려한 뒤에도 context가 추가 정보를 주는가?
5. basic POI와 richer POI metadata가 context에 추가 정보를 주는가?

이 실험은 exploratory / predictive feasibility입니다. 인과 효과, 프로덕션 ranking 품질, 최종 serving contract를 확정하지 않습니다.

- TL: discovery / training
- VL: external replication / validation
- TL/VL 무작위 재분할 없음
- unvisited POI를 negative로 만들지 않음
- ranking metric은 이 실험 범위가 아님

## 2. 실제 Context Feature Contract

### 2.1 Primary context

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

### 2.2 Companion relation은 recorded-only sensitivity

`TN_COMPANION_INFO.REL_CD`에서 만든 `companion_relation_codes`는 별도 분석합니다.

**Primary `context_only`에서는 제외합니다.**

companion row가 없다는 것이 혼자 여행했다는 뜻인지, 단순 미기록/결측인지를 현재 계약이 구분하지 못합니다.
이를 `None`으로 둔 채 primary complete-case 모델에 포함하면 relation이 기록된 여행만 남는 selection effect가 생길 수 있습니다.

따라서:

- context ↔ POI association: 수행
- feature ↔ feedback association: 수행
- `context_companion_relation_recorded`: recorded-only predictive sensitivity
- primary `context_only`: 제외

### 2.3 제외 feature

| Feature | 이유 |
| --- | --- |
| `TRAVEL_MISSION`, `TRAVEL_MISSION_CHECK` | 의미/표현 계약 미해결 |
| raw `TRAVEL_START_YMD`, `TRAVEL_END_YMD` | 정확 날짜는 predictor로 사용하지 않고 month / elapsed_days만 파생 |
| `season` | 문서화된 mapping 미확정 |
| `GENDER`, `AGE_GRP` | demographic은 별도 서술 분석 |
| `TRAVELER_ID`, `TRAVEL_ID`, `POI_ID` | join/group key이며 predictor가 아님 |
| post-event feedback | leakage 방지를 위해 input 금지 |

## 3. POI Representation

### Basic POI

- `region`
- `VISIT_AREA_TYPE_CD`
- 방문 `SGG_CD`

### Richer POI

유일한 region-scoped candidate join이 가능한 경우에 한해:

- POI master `SGG_CD`
- `ASORT_LCLASDC`
- `ASORT_MLSFCDC`
- `ASORT_SDASDC`

`POI_ID` 연결은 exploratory candidate join이며 canonical PK/FK 또는 권역 간 동일 장소 identity로 주장하지 않습니다.

## 4. 실험 설계

### Phase 0 — Availability / Join Audit

`availability_audit.csv`에서 각 context/POI feature의 권역 × TL/VL별 다음 항목을 기록합니다.

- rows / nonmissing
- missing-rate band
- cardinality band
- category support
- POI join coverage / duplicate / collision

최종 보고서에는 대체로 충분하다는 문장만 쓰지 않고 **feature group별 availability**를 표로 요약합니다.

### Phase 1 — 개별 Context ↔ POI Association

`associations.csv`의 `analysis=context_to_poi`는 context feature만 대상으로 생성합니다.

예:

- `TRAVEL_STYL_1 × VISIT_AREA_TYPE_CD`
- `TRAVEL_MOTIVE_2 × visit_SGG_CD`
- `month × VISIT_AREA_TYPE_CD`
- `elapsed_days × POI_master_ASORT_LCLASDC`

각 결과는 support, Cramér's V, chi-square p-value를 기록하고 TL→VL replication을 확인합니다.
`visit-row`와 `distinct-trip-pair` grain을 분리합니다.

`region`은 primary context에 포함하지만 단일 권역에서는 상수이므로 `insufficient-support`가 정상이며 aggregate scope에서 직접 봅니다.

### Phase 2 — Main Effects와 Joint-feature Increment

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

### Phase 3 — Context Group Predictive Ablation

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

### Phase 4 — Dominant Signal을 고려한 공통 코호트 비교

`common_cohort_sensitivity.csv`의 각 pair는 동일한 TL 학습 행과 동일한 VL 평가 행을 사용합니다.

| Comparison | Left | Right | 질문 |
| --- | --- | --- | --- |
| `region_vs_context` | region only | full context | region보다 context가 추가 정보를 주는가? |
| `popularity_vs_context` | region + popularity | 동일 + context | popularity를 고려한 뒤 context가 추가 정보를 주는가? |
| `broad_category_vs_context` | broad POI category | 동일 + context | broad category보다 context가 추가 정보를 주는가? |
| `context_vs_poi` | context | context + basic POI | basic POI가 context에 추가 정보를 주는가? |
| `poi_vs_richer_poi` | context + basic POI | + richer POI | richer POI가 추가 정보를 주는가? |

Phase 1 association은 권역별로 따로 계산되므로 같은 region 내부에서도 context ↔ POI association이 남는지 확인할 수 있습니다.

## 5. Feedback Targets

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

## 7. Privacy / Statistical Reporting

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

## 10. 재실행 후 이 문서에 채울 결과

### A. Context Feature Evidence Matrix

| Context group | Feature(s) | Availability TL/VL | POI association TL | POI association VL | Replication | 판단 |
| --- | --- | --- | --- | --- | --- | --- |
| Style | `TRAVEL_STYL_1~8` | pending | pending | pending | pending | pending |
| Motive | `TRAVEL_MOTIVE_1~3` | pending | pending | pending | pending | pending |
| Destination | destination + region | pending | pending | pending | pending | pending |
| Companion | accompany + count | pending | pending | pending | pending | pending |
| Temporal | month + elapsed days | pending | pending | pending | pending | pending |
| Companion relation | recorded-only | pending | pending | pending | pending | pending |

### B. Context Group Predictive Ablation

| Group | DGSTFN | REVISIT | RCMDTN | 해석 |
| --- | --- | --- | --- | --- |
| Style | pending | pending | pending | pending |
| Motive | pending | pending | pending | pending |
| Destination | pending | pending | pending | pending |
| Companion | pending | pending | pending | pending |
| Temporal | pending | pending | pending | pending |
| All context | pending | pending | pending | pending |

### C. Controlled Incremental Comparisons

| Comparison | 결과 | 해석 |
| --- | --- | --- |
| region → +context | pending | pending |
| popularity → +context | pending | pending |
| broad category → +context | pending | pending |
| context → +basic POI | pending | pending |
| basic POI → +richer POI | pending | pending |

### D. Joint-feature sensitivity

style / motive / destination / companion / temporal 각각에서 TL에서 관측되고 VL에서 재현되는 context×POI joint-feature increment가 있는지 요약합니다.
최고값만 고르지 않고 support와 권역 일관성을 같이 봅니다.

## 11. 결론 상태

**현재: Pending rerun**

새 run을 검토한 뒤에만 다음 중 하나로 바꿉니다.

- **Go** — context-aware POI ranking 후속 실험으로 갈 근거가 있음
- **Inconclusive** — coverage / representation / evaluation 한계로 아직 결론 불가
- **Reconsider** — 충분한 feature/POI representation에서 신호가 반복적으로 재현되지 않음

특정 subset 실패 또는 privacy-limited 결과만으로 `Reconsider`를 내리지 않습니다.

## 12. 여전히 이 실험이 답하지 않는 것

- context가 Top-K POI ranking을 실제로 개선하는지
- unvisited candidate의 negative 정의
- 최종 candidate universe
- canonical POI identity
- production serving feature
- UI에서 어떤 질문으로 context를 받을지
- Two-Tower / LambdaMART 등 최종 모델 선택
- causal interaction

이 항목들은 교정 run 결과를 바탕으로 후속 ranking/evaluation 및 #41에서 결정합니다.