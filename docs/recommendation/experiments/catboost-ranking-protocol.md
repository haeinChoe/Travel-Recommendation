# CatBoost cold-user ranking 실험 프로토콜

**관련 Issue:** #79, #82
**현재 상태:** #82 runner가 #80 traveler split과 inner-train I3/I4 재계산을 연결함 / 실제 TL smoke는 메모리 증가로 중단되어 완료 지표 없음; 사용자가 actual-data 실행을 멈췄고 현재 최적화 검증은 synthetic only

## 이 문서가 답하려는 질문

확정된 cold-user POI ranking 계약에서 negative sampling, feature group, CatBoost objective를 어떤 순서와 동일 조건으로 비교해야 각 요인의 효과를 설명할 수 있는지 정한다.

## 한눈에 보는 결론

한 번에 모든 축을 같이 튜닝하지 않는다.

~~~text
고정된 candidate + TL inner split
        ↓
YetiRank prototype
        ↓
sampling search
        ↓
feature-group search
        ↓
objective search
        ↓
hyperparameter search
        ↓
multi-seed 확인
        ↓
configuration lock
        ↓
VL 최종 평가 (#83)
~~~

## 현재 결정된 것

- prototype objective: **YetiRank**
- sampling: **uniform / popularity-weighted / mixed / hard**
- 초기 negative ratio: **1 / 2 / 4 / 8 / 16**
- feature: #41의 Feature Group v1
- metrics: **NDCG@K / Recall@K / MRR@K / HitRate@K**
- 기본 K: **5 / 10 / 20**
- seed 반복 횟수는 실제 runtime 확인 뒤 결정
- 공식 VL은 모든 tuning이 끝난 뒤 사용

## 선행 작업 상태

- I2 Administrative Location의 feature 계약과 synthetic 검증은 #81에서 완료됐다. `canonical_admin_sido_code`, `canonical_admin_sgg_code`, `canonical_admin_location_status`를 모델 입력으로 사용하며, 실제 AI Hub coverage/conflict 감사만 후속 입력 확보 후 수행한다.
- I3 Popularity의 inner-train 재계산 경계와 I4 Historical POI의 `recompute_inner_train_visit_type_codes` helper는 #80에서 구현·검증 완료됐다.
- #82 runner는 한 권역의 TL trip-owner, positive interaction, `TN_VISIT_AREA_INFO` 이벤트, AI Hub 후보 feature를 받아 traveler-group split을 만들고 I3/I4를 inner-train에서 다시 계산한다. 기존 outer-TL I3/I4 값은 덮어쓴다.
- CatBoost runtime dependency는 `pyproject.toml`과 `uv.lock`에서 고정한다. Issue #82 검증 환경은 Python 3.12와 CatBoost 1.2.10을 사용한다.

## 다음 행동

#80과 #81은 완료됐다. 다음 단계는 #82이며, 아래 순서대로 실제 TL inner-validation 실험을 수행한다.

---

## Stage 0 — 공통 조건 잠금

비교 전 다음 조건을 모든 run에서 동일하게 둔다.

- 같은 TL inner split
- 같은 request grain
- 같은 region hard filter
- 같은 candidate universe
- 같은 positive label 의미
- 같은 metric implementation과 K
- 같은 privacy-safe result schema

한 실험 축을 비교할 때 다른 축을 함께 바꾸지 않는다.

## Stage 1 — YetiRank prototype smoke

목적은 최고 성능을 찾는 것이 아니라 end-to-end ranking pipeline이 계약대로 동작하는지 확인하는 것이다.

권장 첫 실행:

~~~text
objective = YetiRank
sampling = uniform
negative_ratio = 1x
feature = 작은 runnable set
~~~

확인 사항:

- 한 request의 모든 row가 같은 GroupId에 속한다.
- training group에는 positive와 sampled-unobserved가 같이 있다.
- validation은 candidate 안에 positive가 하나도 없는 all-zero group도 허용한다.
- 같은 group의 row가 contiguous하다.
- candidate가 request region 밖으로 새지 않는다.
- inner-validation이 train-derived feature나 sampling 통계에 사용되지 않는다.
- metric이 query 단위로 계산된다.

## Stage 2 — Negative sampling search

### 질문

같은 feature와 objective에서 sampled-unobserved의 선택 분포와 양이 ranking 결과를 얼마나 바꾸는가?

### 고정

- objective = YetiRank
- feature set = prototype 기준 set
- split / candidate / metric = 동일

### 초기 grid

~~~text
strategy ∈ {
  uniform,
  popularity-weighted,
  mixed,
  hard
}

ratio ∈ {1, 2, 4, 8, 16}
~~~

초기 grid는 20개 configuration이다.

### 누수 규칙

- popularity-weighted와 mixed의 weight는 inner-train popularity만 사용한다.
- hard sampling score도 inner-train에서만 만들어야 한다.
- unobserved를 실제 dislike로 해석하지 않는다.
- ratio가 커질수록 metric뿐 아니라 runtime과 training row 수도 기록한다.

`popularity_smoothing=1.0`과 `mixed_uniform_fraction=0.5`는 하네스의 prototype 기본값이다. 두 값은 명시적 config로 기록하고 #82에서 필요하면 비교한다. Mixed에서는 `floor(sample_count × mixed_uniform_fraction)`개를 uniform으로 고르고 나머지를 popularity-weighted로 고른다. 합의된 최종 공식으로 해석하지 않는다.

상위 sampling protocol을 Stage 3으로 넘긴다. 몇 개를 넘길지는 runtime과 결과를 본 뒤 정한다.

## Stage 3 — Feature Group search

### 질문

동일 sampling 조건에서 어떤 정보 그룹이 POI 순위에 추가 가치를 주는가?

~~~text
Q1 Style
Q2 Motive
Q3 Companion
Q4 Temporal
Q5 Destination Context
I1 Category
I2 Administrative Location
I3 Popularity
I4 Historical POI
C1 Region
~~~

모든 10개 그룹이 runnable이면 empty를 제외한 조합은 2^10 - 1 = 1023개다. 이 수에 sampling, objective, seed를 동시에 곱하지 않는다.

탐색 원칙:

- runtime이 충분하면 exhaustive search
- 비용이 크면 forward greedy 후 backward removal check
- I2와 I4는 runnable이다. `fit_catboost`는 I3/I4를 포함한 행마다 helper가 발급한 immutable materialization과의 item key, trip partition, feature 값 일치를 확인한다. `inner-train` 문자열만으로는 fit을 허용하지 않는다.

해석을 위해 best configuration 하나만 남기지 않고 최소 다음 비교도 보존한다.

~~~text
context + static item
context + static item + popularity
context + static item + popularity + historical POI
~~~

내부 표현:

- Category: L1 / L1+L2 / L1+L2+L3
- Popularity: raw / log1p

그룹 on/off 효과와 그룹 내부 표현 효과를 구분해 기록한다.

## Stage 4 — Objective search

### 질문

같은 data, sampling, feature 조건에서 CatBoost ranking objective가 metric을 얼마나 바꾸는가?

비교:

~~~text
YetiRank
PairLogit
LambdaMart
~~~

평가 metric과 objective를 같은 것으로 취급하지 않는다. 예를 들어 PairLogit으로 학습한 모델이 NDCG@10에서 가장 높을 수도 있다.

CatBoost 공식 문서 기준으로 위 세 objective는 ranking 최적화에 지원된다. PairLogit 계열은 explicit pair가 없을 때 같은 group의 label을 사용해 pair를 생성할 수 있으므로 현재 binary 1/0 label과 GroupId 계약을 유지하면서 비교한다.

비교 중에는 모든 objective에 동일한 `eval_metric=NDCG:top=10`과 명시된 `iterations`를 적용하고 `use_best_model=False`로 둔다. CatBoost는 eval set이 있고 validation label이 한 값으로만 구성되지 않으면 `use_best_model`을 기본 활성화할 수 있으며, 켜져 있으면 eval metric에 따라 저장되는 tree 수가 달라진다. 따라서 이 프로토콜은 validation 기반 best-iteration 선택을 끄고 같은 반복 수로 objective만 비교한다. `1000`은 harness의 prototype budget이며 최종 탐색값은 아니다. Final NDCG@5/10/20 및 Recall/MRR/HitRate는 별도의 metric 계산으로 비교한다. ([CatBoost common training parameters](https://catboost.ai/docs/en/references/training-parameters/common))

## Stage 5 — Hyperparameter search

sampling, feature, objective를 먼저 잠근 뒤 CatBoost 세부 설정을 조정한다.

후보 예:

- iterations
- depth
- learning_rate
- regularization 계열

구체적인 search space는 #82에서 prototype runtime과 과적합 패턴을 확인한 뒤 정한다. 성능 근거 없이 임의 숫자를 지금 확정하지 않는다.

## Stage 6 — Seed 반복

seed 수는 실행시간을 보고 정한다.

- 넓은 탐색: 적은 seed로 후보를 줄인다.
- 최종 후보: 여러 seed로 다시 실행해 평균과 변동을 확인한다.

sampling seed와 CatBoost random_seed는 run metadata에서 재현 가능해야 한다.

## Stage 7 — Configuration lock

VL을 보기 전에 다음을 하나의 고정 configuration으로 기록한다.

- split recipe와 seed
- candidate universe
- feature groups와 내부 표현
- sampling strategy와 ratio
- objective
- CatBoost hyperparameter
- final seed set
- metrics와 K
- code revision

이 상태가 #83의 입력이다.

## Stage 8 — VL final evaluation과 bootstrap

#83에서는 잠긴 configuration만 공식 VL에 적용한다.

VL 결과를 본 뒤 #82로 돌아가 feature, sampling, objective를 다시 선택하면 VL은 holdout이 아니게 되므로 금지한다.

#80 실제 감사에서 네 권역 모두 traveler:trip = 1:1이고 multi-trip traveler가 0%였다. 따라서 현재 데이터 기준 #83 bootstrap 기본 단위는 trip/request다. #83에서는 입력 데이터와 traveler identity 전제가 바뀌지 않았는지만 재확인한다.

- 현재 데이터가 유지되면 trip/request bootstrap
- 향후 반복 traveler가 의미 있게 생기면 traveler-cluster bootstrap으로 전환

## Harness 책임 범위

scripts/recommendation/catboost_ranking_experiment.py가 제공하는 것:

- ExperimentConfig
- Feature Group v1
- I3/I4 inner-train feature materialization with full-TL aggregate replacement
- train-derived source scope guard
- same-region candidate filter
- 네 sampling strategy
- sampling search config builder
- exhaustive feature config builder
- objective comparison config builder
- NDCG / Recall / MRR / HitRate
- ranking group layout validation
- CatBoost thin adapter
- machine-readable default protocol

이 파일이 하지 않는 것:

- raw AI Hub data loading
- canonical location reconciliation
- request-ranking frame assembly
- large-scale result artifact 생성
- 실제 CatBoost tuning

실행 책임은 분리되어 있다. #80은 traveler split과 I3/I4 재계산 경계를 완료했고, #81은 I2 정적 위치 계약을 완료했다. #82 runner integration은 inner-train item feature materialization까지 연결했다. 첫 실제 TL smoke는 메모리 증가로 중단되어 완료 지표가 없다. 사용자가 actual-data 실행을 멈춘 뒤 수행한 평가 경로 최적화와 벤치마크는 synthetic 자료만 사용했으며 실제 데이터 성능 개선을 입증하지 않는다.

### 준비된 카탈로그와 bounded scoring

동일 권역 후보 목록은 `PreparedItemCatalog.from_materialization(...)`으로 한 번 준비한다. 이 객체는 helper가 만든 I3/I4 및 선택한 정적 item 열을 정규화해 불변 tuple로 보관하며, feature transform 설정과 helper provenance가 일치하지 않으면 평가를 거부한다. I2 열은 category depth와 관계없이 모두 보존하고, query-context 열은 매 query 입력에서만 가져온다. 원래 학습 frame을 `fit_catboost`에 전달할 때는 기존 raw feature 값과 materialization을 사용해야 하며, catalog의 log1p 변환값을 다시 학습 전처리에 넣지 않는다.

Uniform sampling은 준비된 `catalog.inventory`를 사용하면 후보 목록을 매 query마다 복사·정렬하지 않고 같은 `random.sample` 결과를 만든다. `score_inner_validation_queries(...)` 호출자는 각 query의 권위 있는 `region`을 `query_features[trip_id]["region"]`에 반드시 제공해야 하며, 값이 후보 카탈로그 권역과 다르거나 누락되면 예측 전에 실패한다. `score_inner_validation_queries(...)`는 query 하나씩 처리하고 후보 점수를 `max_rows_per_batch` 행 이하의 DataFrame으로 나눠 예측한다. 각 chunk에서 `(-score, item_id)` 순서를 유지해 정확한 global top-K를 합친다. 이 행 제한은 prediction frame 크기만 제한한다. 정규화된 전체 후보 카탈로그는 메모리에 남으므로 전체 프로세스 메모리 상한을 뜻하지 않으며, CatBoost 예측 호출도 query마다 수행한다.

합성 경로 확인 명령은 다음과 같다.

~~~bash
.venv/bin/python scripts/recommendation/benchmark_catboost_validation_stream.py --catalog-size 20000 --queries 60 --batch-rows 1024
~~~

벤치마크는 legacy full-frame와 prepared chunked 경로의 metric 일치, 구간별 wall time, 최대 prediction-frame 행 수를 보고한다. 별도 `tracemalloc` 수치는 Python 관리 메모리 할당 peak이며 process RSS가 아니다. workload 크기나 실행 환경이 다른 실제 TL 실행시간·메모리의 대리값으로 해석하지 않는다.

코드 검증 시 20,000개 synthetic 후보와 60개 query, 1,024행 chunk로 한 번 측정한 결과다. 비교 목적은 같은 synthetic 입력에서 전체 frame과 bounded scoring의 자원 차이를 확인하는 것이다.

| 경로 | 경과 시간 | Python 할당 peak | 최대 예측 frame |
| --- | ---: | ---: | ---: |
| Legacy full-frame 평가 (60 queries) | 7.36초 | — | 20,000행 |
| Prepared chunked 평가 (60 queries) | 1.44초 | — | 1,024행 |
| Legacy uniform sampling (60회) | 0.260초 | — | — |
| Prepared uniform sampling (60회) | 0.00046초 | — | — |
| Legacy 1-query allocation probe | — | 10,773,814 bytes | 20,000행 |
| Prepared 1-query allocation probe | — | 535,876 bytes | 1,024행 |

합성 metric dictionary는 두 scoring 경로에서 정확히 같았다. 이 값은 이 synthetic scorer와 한 번의 로컬 측정 결과일 뿐이며, CatBoost training이나 actual TL 병목·성능을 검증하지 않는다. Prepared catalog는 전체 후보 정규화 열을 메모리에 보관하고 predict는 query마다 호출하므로, frame 행 제한을 process RSS 보장으로 해석하지 않는다.

## #79 검증 범위

synthetic unit test로 다음을 확인한다.

- Feature Group v1
- I2 available 계약과 I3/I4 inner-train 재계산 및 누수 방지 경계
- category depth와 popularity transform
- region candidate filtering
- deterministic uniform sampling
- weighted / mixed / hard sampling boundary
- inner-train-only sampling statistics
- sampling / feature / objective config builder
- ranking metric known-value case
- group contiguity와 binary label
- VL tuning 금지 protocol

실제 AI Hub 성능 수치는 smoke run을 마치기 전에는 존재하지 않는다.
