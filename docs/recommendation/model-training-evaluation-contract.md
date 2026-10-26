# Cold-user POI ranking 학습·평가 계약

**관련 Issue:** #41, #79, #80, #81, #82, #83
**현재 상태:** #80 traveler split·I3/I4 경계와 #81 I2 계약이 반영됐고, PR #88에서 #82 runner와 Stage 1 수도권 TL smoke를 완료했다. #82 scoring 최적화와 full 수도권 TL inner-validation 재측정에서 #88에 공개된 다섯째 소수점 정밀도 기준으로 metric parity를 확인했다. Full-precision parity는 주장하지 않는다. 실측 비용에 따라 feature search는 forward + backward greedy, broad search는 후보당 1 seed, 최종 configuration은 총 3 seeds로 결정했다. 다음은 negative sampling search다.

## 이 문서가 답하려는 질문

과거 행동 이력이 없는 사용자에게 현재 여행 문맥과 목적 지역을 받아 POI를 추천할 때, 무엇을 입력으로 사용하고 무엇을 정답 신호로 보며 어떤 후보를 어떤 split에서 순위화할지 고정한다.

이 문서는 CatBoost만을 위한 설명이 아니라 후속 모델도 같은 candidate, split, label, metric 정의로 비교하기 위한 공통 계약이다.

## 한눈에 보는 결론

~~~text
cold user + 현재 여행 문맥 + 목적 지역
        ↓
해당 지역의 AI Hub 후보 POI hard filter
        ↓
(request context, candidate POI) feature row
        ↓
CatBoostRanker prototype: YetiRank
        ↓
POI score → Top-K ranking
~~~

실제 방문 POI는 관측 양성 1이다. sampled-unobserved POI는 학습 비교용 0으로 표현하지만, 이 0은 사용자가 싫어했다는 관측 음성이 아니다.

## 현재 결정된 것

- 문제 유형: **cold-user contextual POI ranking**
- ranking group: 한 trip/request
- 요청 지역을 ranking 전에 hard filter
- 현재 offline candidate/evaluation source는 AI Hub만 사용
- prototype model은 **CatBoostRanker**
- prototype objective는 **YetiRank**
- objective 비교 후보는 **YetiRank / PairLogit / LambdaMart**
- TL 내부에서 모델 선택을 수행하고 공식 VL은 최종 holdout으로 보존
- 평가 지표는 NDCG@K, Recall@K, MRR@K, HitRate@K
- raw 좌표, H3, distance, TN_GPS_COORD는 현재 ranking feature에서 제외

## 확인 완료 및 남은 결정

- #80 실제 감사 완료: 네 권역 모두 traveler:trip = 1:1, multi-trip traveler = 0%, seed `issue80-v1`·validation fraction 0.2에서 권역별 inner-train 2,048 / inner-validation 512 traveler와 trip, traveler overlap 0이다.
- #81 I2 Administrative Location 계약 완료: `canonical_admin_sido_code`, `canonical_admin_sgg_code`, `canonical_admin_location_status`를 모델 입력으로 사용한다. 실제 AI Hub coverage/conflict/provenance 감사만 후속 입력 확보 후 수행한다.
- #80 I4 Historical POI의 inner-train-safe 재계산 helper 구현·테스트 완료. PR #88에서 #82 runner의 TL visit-event input 연결을 완료했다.
- sampling / feature group / objective의 실제 최종 선택: #82
- seed budget: broad search 후보당 1 seed, 잠글 최종 configuration 총 3 seeds (#82 runtime benchmark 근거)
- bootstrap: 현재 데이터 기준 trip/request 단위를 기본으로 하고, #83에서 입력 데이터와 traveler identity 전제가 유지되는지 확인한 뒤 신뢰구간 설정을 확정한다.

남은 항목은 설계 누락이 아니라 #82/#83의 실제 실험 결과로 결정하도록 분리한 항목이다.

## 다음 행동

1. #79 완료: 계약과 synthetic experiment harness를 구현했다.
2. #80 완료: traveler-trip 분포 감사, traveler group split, inner-train I3/I4 재계산 경계를 구현·검증했다.
3. #81 완료: canonical administrative location(I2) 계약과 synthetic reconciliation을 구현·검증했다.
4. **#82 진행:** PR #88 runner smoke 이후 scoring runtime을 최적화하고 같은 TL inner-validation에서 재측정했다. Metric parity를 확인했으며 measured full-configuration cost를 근거로 sampling → forward/backward greedy feature → objective → hyperparameter 순서와 1-seed screening / 3-seed final budget을 정했다. 다음 checkpoint에서 negative sampling부터 시작한다.
5. configuration을 잠근 뒤 #83에서 처음 VL을 평가하고 bootstrap 신뢰구간을 계산한다.

---

## 1. 모델의 X, Y와 GroupId

### 1.1 입력 X

한 학습 행은 하나의 request와 하나의 candidate POI 조합이다.

~~~text
X(q, i) = [request_context(q), item_features(i)]

q1 × POI-A
q1 × POI-B
q1 × POI-C
~~~

trip_key와 item_key 같은 식별 키는 join과 group 구분에만 사용하고 모델 입력 feature로 넣지 않는다.

### 1.2 학습 target Y

~~~text
실제 관측 방문 POI      → label = 1
sampled-unobserved POI   → label = 0
~~~

의미 경계는 다음과 같다.

- 1은 방문이 관측된 implicit positive다.
- 0은 negative sampling으로 만든 비교 행이다.
- 0은 노출됐지만 선택하지 않았거나 싫어했다는 관측 사실이 아니다.
- 미방문 전체를 자동으로 negative로 변환하지 않는다.

### 1.3 GroupId

GroupId는 trip/request 단위다.

~~~text
Group q1
  POI-A label=1
  POI-B label=0
  POI-C label=1
  POI-D label=0
~~~

같은 group의 행은 CatBoost 입력에서 연속이어야 한다. #79 harness는 group이 끊겨 다시 나타나거나 한 group에 1 또는 0 중 하나만 있는 경우를 오류로 처리한다.

## 2. 후보 집합 계약

validation의 정답을 본 뒤 후보를 추가하면 evaluation 정보가 candidate 생성에 섞이므로 금지한다.

### 2.1 TL inner-validation

한 request의 후보는 다음과 같다.

~~~text
AI Hub item inventory 중 요청 문맥과 설정된 feature를 만들 수 있는 item
∩
request의 region
~~~

후보 자격은 inner-train에서 관측됐는지와 분리한다. Train-unseen POI도 AI Hub inventory에 있고 필요한 정적 특성과 inner-train 기준 파생 특성을 만들 수 있으면 후보에 포함한다. 이 계약은 cold-item을 별도 평가 문제로 나누지 않는다. 인기 횟수처럼 inner-train에서 계산하는 값은 후보 전체에 대해 inner-train만으로 다시 만들며, 상호작용이 없는 item은 그 집계 규칙에 따른 값을 받는다.

inner-validation positive는 정답 집합에 남기고 후보 구성에 사후 주입하지 않는다. 필요한 feature를 만들 수 없어 후보에서 제외된 positive는 miss가 되며 candidate/positive coverage 진단에서 확인한다.

이 경우 어떤 validation query는 candidate row 전체가 label 0일 수 있다. Training group은 학습 비교를 위해 label 1과 sampled label 0을 모두 요구하지만, validation group은 all-zero candidate row를 허용한다. 최종 NDCG/Recall/MRR/HitRate는 CatBoost eval_set label만으로 계산하지 않고, 원래 held-out positive 집합을 별도 ground truth로 유지해 계산한다. 그래야 candidate 밖 positive도 올바르게 miss로 반영된다.

### 2.2 공식 VL

VL 평가 후보는 다음과 같다.

~~~text
AI Hub item inventory 중 설정된 feature를 만들 수 있는 item
∩
VL request의 region
~~~

Train-unseen item을 후보에서 제외하지 않는다. TL 전체 interaction으로 파생되는 feature는 최종 학습 시점에만 TL에서 재계산한다.

TourAPI 전체 catalog는 이번 offline 모델 선택 candidate universe가 아니다.

### 2.3 region의 두 역할

region은 다음 두 역할을 구분한다.

1. **candidate scope:** 요청 지역 밖 POI를 ranking 전에 제외하는 hard filter
2. **C1 Region feature:** 여러 region을 하나의 global model에서 학습할 때 region 자체의 추가 가치 확인

따라서 hard filter를 했다는 이유로 C1 ablation을 자동 생략하지 않는다.

## 3. Split과 데이터 누수 방지

### 3.1 outer split

~~~text
TL / train      → 개발과 최종 학습
VL / validation → 최종 holdout
~~~

VL metric을 보고 feature, sampling, objective, hyperparameter를 다시 고르지 않는다.

### 3.2 TL inner split

cold-user 문제이므로 기본 identity key인 `(region, TRAVELER_ID)` 기준 group split을 사용한다.

같은 traveler의 모든 trip은 inner-train 또는 inner-validation 한쪽에만 둔다. #80 구현은 각 TL 권역 안에서 `(region, TRAVELER_ID)`와 seed의 SHA-256 정렬 순서로 validation traveler를 선택하는 결정론적 group split을 제공한다. seed와 validation 비율은 재현 metadata에 남기며 기본값은 `issue80-v1`과 0.2다. 한 traveler만 있거나 split 비율이 유효하지 않으면 분할을 실패 처리한다. split map은 메모리에서만 유지하고 각 권역 안에서 traveler overlap이 0인지 검사한다. 원천 계약은 권역 간 traveler ID 전역 유일성을 선언하지 않으므로 identity key에 region을 포함한다. 분포와 split에는 유일한 `TRAVEL_ID` 및 유일한 `TN_TRAVELLER_MASTER.TRAVELER_ID` 연결만 사용한다.

네 TL role binding은 provenance 검사를 통과했고, Issue #80 코드를 대상으로 privacy-safe 실제 aggregate를 실행했다. 각 권역은 distinct traveler 2,560명 / distinct trip 2,560개였고, 모든 traveler가 한 trip만 보유했다 (mean/median/max = 1, multi-trip share = 0%). `issue80-v1`, validation fraction 0.2에서 각 권역의 inner-train은 2,048 traveler/trip, inner-validation은 512 traveler/trip이며 group-split traveler overlap은 0이다. Trip-level reference의 structural traveler overlap도 모든 권역에서 0이었다. 현재 표본에서 두 split은 traveler leakage 방지 구조 측면에서 동등하다. 다만 반복 traveler가 있는 미래 데이터에도 안전하도록 기본 계약은 `TRAVELER_ID` group split으로 유지한다. Partition-label disagreement는 수도권 784/2,560 (30.6250%), 동부권 812/2,560 (31.71875%), 제주도 및 도서지역 804/2,560 (31.40625%), 서부권 818/2,560 (31.953125%)이다. 이 값은 서로 다른 hash key로 만든 두 결정론적 assignment의 label 차이이며 leakage metric가 아니다.

synthetic fixture 테스트는 감사 함수와 4개 권역 CSV CLI를 실행하며 aggregate 출력에 ID나 입력 경로가 없는지 확인한다. CatBoost 1.2.10이 설치된 임시 Python 3.12 환경에서 집중 테스트 12개와 전체 350개 테스트가 모두 통과했으며 건너뛴 테스트는 없다. Ruff 0.17.2, `py_compile`, `git diff --check`도 통과했다.

### 3.3 train-derived feature의 inner split 누수

현재 canonical item_features.parquet의 다음 값은 outer TL 전체에서 계산된다.

- train_positive_interaction_count
- train_observed_visit_type_codes

이 값을 TL inner-validation에서 그대로 사용하면 inner-validation interaction이 feature 생성에 참여한다. 따라서 TL tuning에서는 반드시 inner-train 기준으로 다시 계산한다.

| Group | 값 | inner-validation 규칙 |
| --- | --- | --- |
| I3 Popularity | train_positive_interaction_count | inner-train interaction만 집계 |
| I4 Historical POI | train_observed_visit_type_codes | inner-train 방문 이벤트만 집계 |

popularity-weighted / mixed sampling의 popularity와 hard sampling의 score도 inner-train 정보만 사용한다.

canonical `trip_item_interaction.parquet`에는 visit type이 없어 그 파일만으로 I4를 재계산할 수 없다. #80의 `recompute_inner_train_visit_type_codes` 함수는 같은 TL의 `TN_VISIT_AREA_INFO` 이벤트를 inner-train 여행에 한정해 읽고, 관광 핵심 방문이 있는 trip-item의 유효 `VISIT_AREA_TYPE_CD`를 집계하도록 구현·테스트 완료했다. 방문 이벤트 입력이 없거나 필수 trip/item/visit-type/TL split 필드가 빠지면 `I4SourceUnavailableError`로 fail-closed한다. PR #88에서 CatBoost runner는 이 helper에 visit-event input을 연결해 inner-train I4를 사용한다. canonical full-TL I4 값을 inner-validation에 제공하면 안 된다.

## 4. Feature Group v1

### Query / request context

| ID | Group | 컬럼 |
| --- | --- | --- |
| Q1 | Style | travel_style_1..8 |
| Q2 | Motive | travel_motive_1..3 |
| Q3 | Companion | companion_status, companion_count |
| Q4 | Temporal | start_month, elapsed_days |
| Q5 | Destination Context | travel_status_destination |

### Item / POI

| ID | Group | 컬럼 / 상태 |
| --- | --- | --- |
| I1 | Category | source_category_l1_code, l2, l3 |
| I2 | Administrative Location | `canonical_admin_sido_code`, `canonical_admin_sgg_code`, `canonical_admin_location_status` |
| I3 | Popularity | train_positive_interaction_count, inner-train 재계산 필수 |
| I4 | Historical POI | `recompute_inner_train_visit_type_codes` 구현·테스트 완료; PR #88에서 #82 runner가 TL visit-event input과 inner-train materialization을 연결 |

### Control

| ID | Group | 컬럼 |
| --- | --- | --- |
| C1 | Region | region |

Category는 L1 / L1+L2 / L1+L2+L3를 비교할 수 있다. Popularity는 raw count와 log(1 + count)를 비교한다.

## 5. 위치 feature 현재 범위

Issue #69는 matched anchor subset에서 AI Hub/TourAPI 좌표의 WGS84 범위와 거리 분포(4,279 regional anchor 중 93.11%, 4,686 global anchor 중 93.45%가 200m 이내)를 경험적으로 확인했다. 이 identity 검증은 전체 AI Hub Master inventory의 CRS/X-Y source contract 및 좌표 coverage를 확립하지 않는다. 이번 I2는 subset identity evidence를 전체 정적 item feature로 일반화하지 않고 좌표를 사용하지 않는다.

I2는 `TC_SGG`의 AI Hub 2023 행정 코드 체계에 맞춘 광역 시도(2자리)와 시군구(5자리)다. `canonical_admin_sido_name` 및 `canonical_admin_sgg_name`은 사람이 확인하는 코드북 이름이며 입력에는 코드를 사용한다. `region`(`capital`, `west`, `east`, `jeju-islands`)은 데이터·제품의 거친 권역이고, 행정 시군구나 개별 요청의 목적지와 같은 값이 아니다. 요청 target geography는 request context/후보 hard filter에서 별도 공급한다.

학습 item feature는 Master inventory의 정적 근거만으로 생성한다. 방문 행 SGG/address는 train-only 집계 진단에 남기되 I2 모델 입력을 채우거나 덮어쓰지 않으며, inner-validation/VL positive로 자기 위치 특성을 만들지 않는다. 정적 근거가 충돌하거나 모호하면 코드 필드는 null이고 상태와 출처 토큰은 보존된다. 좌표 상태는 `subset_validation_only_not_used`: 과거 anchor subset의 empirical validation은 인정하되 좌표, H3, distance를 이번 전체 inventory I2 정제/feature에 쓰지 않는다.

현재 보류:

- raw latitude / longitude
- H3
- distance feature
- TN_GPS_COORD

#81의 administrative location만으로 너무 거칠거나 향후 거리·동선 요구가 생기면 다시 검토한다.

## 6. Negative sampling

### 가설

같은 region의 미관측 candidate를 어떤 분포로 얼마나 많이 뽑는지가 ranking 성능과 popularity bias에 영향을 준다.

### 비교 family

- uniform
- popularity-weighted
- mixed
- hard

### 초기 ratio

~~~text
1x, 2x, 4x, 8x, 16x
~~~

4x는 positive 하나당 최대 네 개의 sampled-unobserved를 비교 행으로 만든다는 뜻이다.

재현 규칙:

- sampling seed를 기록한다.
- 같은 candidate, positive, seed이면 같은 sample을 만든다.
- weighted/hard sampling 통계는 inner-train만 사용한다.
- popularity smoothing 값과 mixed sampling의 uniform 분율은 설정으로 기록한다. prototype 기본값은 각각 `1.0`과 `0.5`이며, #82 결과 전까지 확정된 모델링 결정이 아니다.
- final VL metric 계산에서는 negative sampling으로 candidate를 축소하지 않는다.

## 7. CatBoost objective

prototype은 YetiRank로 고정한다.

최종 비교 후보:

- YetiRank
- PairLogit
- LambdaMart

현재 CatBoost 공식 문서는 위 objective를 ranking 최적화에 지원하고 CatBoostRanker.fit에서 group_id를 받을 수 있다. NDCG, RecallAt, MRR 같은 평가 metric과 학습 objective는 같은 개념이 아니다.

Objective 비교에서는 세 모델에 같은 `iterations=1000` prototype budget과 `eval_metric=NDCG:top=10`을 사용한다. `use_best_model=False`로 두어 validation score가 모델별 저장 tree 수를 바꾸지 않게 한다. CatBoost는 eval set이 있고 validation label이 한 값으로만 구성되지 않으면 기본으로 best-model 저장을 켤 수 있으므로 명시적으로 끈다. 이 설정은 objective 비교를 통제하기 위한 초기 budget이지 최종 hyperparameter 결정이 아니다. 여러 K의 최종 ranking 지표는 별도 metric 코드로 계산하고, #82에서 objective 비교 후 hyperparameter search를 진행한다. ([CatBoost common training parameters](https://catboost.ai/docs/en/references/training-parameters/common))

CatBoost는 범주형 feature를 일반 수치형 결측 규칙으로 처리하지 않는다. 입력에 `None`, `NaN`, pandas의 nullable 값이 있으면 예약 문자열 `__MISSING__`으로 정규화하고, 나머지 범주값도 문자열로 통일한다. 이 값은 데이터의 실제 범주 코드로 사용하지 않는 sentinel이다. ([CatBoost missing values](https://catboost.ai/docs/en/concepts/algorithm-missing-values-processing), [categorical features FAQ](https://catboost.ai/docs/en/concepts/faq))

PR #88은 `pyproject.toml`과 `uv.lock`에 CatBoost runtime dependency를 고정했다. Issue #82의 실제 실행 환경은 Python 3.12와 CatBoost 1.2.10을 사용했다.

## 8. 평가 지표

초기에는 하나의 primary metric을 고르지 않고 다음을 모두 측정한다.

- **NDCG@K:** relevant POI를 더 높은 순위에 놓았는지 반영
- **Recall@K:** 실제 positive 중 상위 K가 얼마나 회수했는지
- **MRR@K:** 첫 relevant POI가 얼마나 빨리 나오는지
- **HitRate@K:** 상위 K에 relevant POI가 하나라도 있는지

기본 K는 5, 10, 20이다. UI 노출 개수가 정해지면 중요한 K를 다시 정할 수 있다.

## 9. 실험 순서

1. YetiRank prototype smoke
2. sampling search
3. feature-group search
4. objective search
5. hyperparameter search
6. final candidate multi-seed 확인
7. configuration lock
8. untouched VL final evaluation
9. bootstrap confidence interval

optimized full-TL benchmark가 4,655.510초/config이므로 feature search는 forward + backward greedy로 진행하고 exhaustive search는 하지 않는다. 열 개 group의 최대 66-config greedy 경로는 약 85.35시간/seed이며 1,023-config exhaustive는 약 55.1일/seed로 projection된다. Broad search는 후보당 1 seed, 최종 finalist 하나는 총 3 seeds로 확인한다. 세 seed는 stability heuristic이며 formal confidence interval이 아니다.

## 10. Bootstrap 리마인더

bootstrap은 negative sampling이 아니라 최종 metric의 변동성과 신뢰구간을 추정하는 통계 절차다.

#80 실제 감사 결과는 네 권역 모두 traveler:trip = 1:1, multi-trip traveler = 0%다. 따라서 현재 데이터 기준 #83의 기본 bootstrap 단위는 trip/request다. #83에서는 입력 데이터와 traveler identity 전제가 바뀌지 않았는지만 재확인한다.

- 현재 데이터가 유지되면 trip/request bootstrap
- 향후 반복 traveler가 의미 있게 생기면 traveler-cluster bootstrap으로 전환

## 11. 해석 한계

현재 offline 질문은 다음이다.

> holdout request에서 실제 관측된 방문 POI를 같은 region의 사전에 정의된 AI Hub candidate 중 얼마나 높은 순위에 배치하는가?

따라서 현재 metric은 이 offline ranking 문제의 품질이다. 클릭, 저장, 만족도, 실제 서비스 재사용을 직접 측정하지 않는다.

## 12. #79 코드 범위

scripts/recommendation/catboost_ranking_experiment.py는 raw data loader가 아니라 다음 계약 primitive를 제공한다.

- Feature Group v1
- unknown or unavailable feature group fail-closed
- train-derived inner-train scope guard
- same-region candidate filter
- 네 negative sampling strategy
- sampling / feature / objective config builder
- NDCG / Recall / MRR / HitRate
- ranking group layout validation
- CatBoost thin adapter
- machine-readable default protocol 출력

#80의 traveler 감사와 #81의 synthetic I2 검증은 완료됐다. PR #88의 YetiRank prototype을 기준으로 scoring을 최적화하고 같은 수도권 TL inner-validation 전체를 재실행했다. Runtime은 4,655.510초, scoring은 4,394.086초, process peak RSS는 6,779 MiB였다. #88과 metric은 공개된 다섯째 소수점 정밀도에서 일치하며, #88 peak RSS는 기록되지 않아 비교할 수 없다. Search/seed budget은 protocol에 따라 결정 완료됐지만 실제 탐색과 final three-seed 확인은 아직 시작하지 않았다. #83의 untouched VL 평가는 configuration lock 전에는 금지한다.

## 확인된 사실 / 결정 / 한계

### 확인된 사실

- canonical interaction에는 observed positive만 저장된다.
- 현재 I3/I4 값은 outer TL 전체 기준이다.
- canonical interaction만으로 I4를 inner-train 기준으로 다시 만들 정보는 부족하지만, canonical schema가 지정한 `TN_VISIT_AREA_INFO.VISIT_AREA_TYPE_CD` 원천 이벤트는 필요한 trip/item/type 경계를 제공한다. #80 helper는 이 이벤트 경로를 사용한다.
- 실제 4개 권역 traveler-trip 집계는 완료했고 위 aggregate만 보고한다. raw ID, row data, 입력 경로는 공개하지 않는다.

### 결정

- TL tuning의 train-derived feature와 sampling 통계는 inner-train에서만 계산한다.
- I2 canonical administrative location은 #81 코드 계약과 synthetic 검증 기준으로 available이다. PR #88은 I4 재계산 helper를 TL visit-event input과 연결하고 inner-train materialization을 fit/scoring 경계까지 전달한다.
- VL은 최종 configuration을 잠글 때까지 tuning에 사용하지 않는다.

### 한계

- #79는 actual AI Hub row를 읽지 않는다.
- PR #88은 YetiRank prototype을 실제 수도권 TL inner-validation에 실행했지만, 이는 feasibility smoke이며 최종 모델 선택이나 일반화 성능 근거가 아니다. 이번 optimized scoring 재실행은 runtime 및 공개 정밀도 metric parity의 benchmark로 사용하고, 모델 선택 근거는 다음 search 축에서 마련한다.
- #81 I2 코드 계약과 synthetic 구현은 준비됐으며, 승인된 입력으로 실제 coverage/conflict 감사는 아직 수행되지 않았다.
- #80 traveler-trip aggregate 및 split leakage 검증은 완료했다. #82의 최적화된 full TL runtime, process peak RSS, 공개 precision metric parity, greedy/exhaustive 결정과 seed budget은 후속 actual-data run에서 확인해 문서화했다. Sampling/feature/objective/hyperparameter 결과는 아직 없다.

## 재현 참고

~~~bash
python scripts/recommendation/catboost_ranking_experiment.py --print-default-protocol
python -m unittest tests.test_catboost_ranking_experiment -v
~~~

실제 데이터 실행 명령은 #80~#83에서 별도로 기록한다.
