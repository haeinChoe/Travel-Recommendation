# CatBoost cold-user ranking 실험 프로토콜

**관련 Issue:** #79, #82
**현재 상태:** PR #88/#89의 과거 full-run은 TN_POI_MASTER 모든 고유 ID에 source-package region을 부여한 잘못된 geography scope였다. Runner는 #81 canonical administrative location과 versioned `poi-catalog-candidate-v1` 정책으로 후보 geography를 분리했고, corrected 수도권 TL full rerun을 완료했다. 3,052,797개 후보·432 validation query·1,318,808,304 scored rows에서 total 1,532.677초, scoring 1,322.860초, peak RSS 3,788 MiB였다. 이 측정에 근거해 feature search는 한 번의 backward cleanup을 포함한 forward/backward greedy로 하고 broad screen은 1 seed, 최종 configuration은 총 3 seeds로 정했다. 다음 checkpoint는 negative sampling이며 아직 시작하지 않았다. VL은 읽지 않았다.

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
- full-catalog scoring은 query별 제한 행 단위로 유지하고, 동률에서 item ID 오름차순을 포함한 global top-K 결과를 보존한다.
- corrected full-TL cost 1,532.677초/config을 기준으로 10-group exhaustive는 18.15일/seed, forward 55 + 단일 backward cleanup 최대 10 + baseline 1의 greedy는 28.10시간/seed로 projection했다. **Forward + backward single cleanup greedy**를 선택하고, broad screen은 configuration당 1 seed, 최종 configuration은 총 3 seeds로 확인한다. Sampling+feature+seed repeats의 예상량은 현재 baseline 포함 최대 71 configuration-equivalents(약 30.23시간)이며, 세부 산술은 아래에 기록한다.
- 공식 VL은 모든 tuning이 끝난 뒤 사용

## 선행 작업 상태

- I2 Administrative Location의 feature 계약과 synthetic 검증은 #81에서 완료됐다. `canonical_admin_sido_code`, `canonical_admin_sgg_code`, `canonical_admin_location_status`를 모델 입력으로 사용한다. #82 actual TL run은 한 권역의 canonical eligibility, unresolved geography, validation candidate coverage aggregate를 기록했다. 전 권역 source별 provenance·conflict와 전체 coverage audit은 별도 후속 작업으로 남아 있다.
- I3 Popularity의 inner-train 재계산 경계와 I4 Historical POI의 `recompute_inner_train_visit_type_codes` helper는 #80에서 구현·검증 완료됐다.
- #82 runner는 한 권역의 TL trip-owner, positive interaction, `TN_VISIT_AREA_INFO` 이벤트, AI Hub 후보 feature를 받아 traveler-group split을 만들고 I3/I4를 inner-train에서 다시 계산한다. 기존 outer-TL I3/I4 값은 덮어쓴다.
- CatBoost runtime dependency는 `pyproject.toml`과 `uv.lock`에서 고정한다. Issue #82 검증 환경은 Python 3.12와 CatBoost 1.2.10을 사용한다.

## 다음 행동

#80/#81과 #82 scorer 최적화, synthetic parity, corrected actual-TL benchmark 및 budget 결정을 완료했다. PR #88/#89의 과거 full-run은 candidate geography 오류 때문에 corrected baseline을 대체하지 않는다. 다음 checkpoint에서 동일 candidate, split, feature, YetiRank 설정으로 uniform baseline과 popularity-weighted, mixed, hard를 1×·1 seed로 비교한다. 현재 sampling search는 실행하지 않았다.

---

## Stage 0 — 공통 조건 잠금

비교 전 다음 조건을 모든 run에서 동일하게 둔다.

- 같은 TL inner split
- 같은 request grain
- 같은 ProductRegion hard filter. Issue #82 runner에서는 `canonical_admin_sido_code`를 #81 resolver로 만들고, `poi-catalog-candidate-v1`의 `product_region_to_ldong_regn_cd`를 사용한다. 수도권 후보에는 resolved code가 policy의 수도권 mapping에 포함된 row만 둔다.
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

### 완료된 prototype smoke 결과

이 PR #88 실행은 Stage 1의 파이프라인 및 runtime feasibility 확인이다. 모든 Master ID를 수도권 source-package region으로 분류했고 canonical geographic ProductRegion filter를 적용하지 않았다. 이 결과는 historical runner scope만 설명하며 corrected geography baseline, 최종 모델 선택, 전체 탐색, 일반화 성능 주장을 위한 근거가 아니다.

| 항목 | 결과 |
| --- | ---: |
| 설정 | YetiRank, uniform negative sampling, 1×, 1,000 iterations |
| seed | 20261025 |
| inner-validation query | 432 |
| 후보 카탈로그 | 7,442,866 POI |
| 검증 scoring 행 | 3,215,318,112 |
| training 행 / query | 5,120 / 1,483 |
| 총 runtime | 6,019초 |
| CatBoost fit | 8.7초 |
| validation scoring | 5,764.1초 |

| Metric | @5 | @10 | @20 |
| --- | ---: | ---: | ---: |
| NDCG | 0.00207 | 0.00416 | 0.00495 |
| Recall | 0.00347 | 0.00863 | 0.01113 |
| MRR | 0.00174 | 0.00345 | 0.00381 |
| HitRate | 0.00463 | 0.01852 | 0.02546 |

이 smoke에서는 모델 fitting보다 validation scoring이 runtime 병목이었다. 이 표는 최적화 전 #88 결과를 보존한 historical baseline이며 최종 모델 성능으로 해석하지 않는다.

### Scoring 최적화 checkpoint

기존 scorer는 카탈로그 행 순서와 inventory의 정렬 순서 사이에 별도 전체 item-index map을 만들고, validation query마다 32,768행 chunk를 생성했다. 각 chunk에서 전체 score tuple을 정렬해 top-K를 골랐다. 새 경로는 immutable item feature tuple을 candidate ID 순으로 한 번 정렬해 정렬된 chunk를 직접 자르고, NumPy partition으로 경계 score와 동률 ID만 처리한다. prediction frame의 최대 행 수는 262,144로 올렸으며, 후보 전체를 한 번에 materialize하지 않는다. candidate universe, feature 값, metric, positive 처리와 동률 정렬 규칙은 그대로다.

아래 synthetic 결과는 scorer 구현 parity와 bounded frame 크기만 검증한다. actual 수도권 TL을 다시 실행한 결과로 해석하지 않는다.

| 합성 workload | Legacy 경과 시간 | Bounded 경과 시간 | Legacy Python 할당 peak | Bounded Python 할당 peak | 최대 prediction frame | metric parity |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 20,000 candidates × 60 queries, cap 1,024 | 8.87초 | 2.09초 (4.25× 빠름) | 9,972,785 bytes | 210,958 bytes | 1,024행 | 정확히 같음 |
| 300,000 candidates × 4 queries, cap 262,144 | 8.17초 | 1.38초 (5.91× 빠름) | 149,154,351 bytes | 34,091,965 bytes | 262,144행 | 정확히 같음 |

두 번째 workload의 전체 Python 프로세스 peak RSS는 772.3 MiB였다. 이 값은 300,000개 합성 catalog에서만 측정했으며 PR #88의 7,442,866 source-tagged Master ID에 대한 RSS 보증값이 아니다. 별도 unit parity는 점수가 동률인 13개 item을 여러 chunk 크기로 나누어 legacy `(-score, item_id)` 순위와 top-K metric이 일치하는지 확인한다.

#### 실제 수도권 TL inner-validation benchmark

PR #88 reported 6,019초 total, 5,764.1초 scoring, 7,442,866 candidates, and 432 validation queries. PR #89 previously reported an optimized run at 4,655.510초 total, 4,394.086초 scoring, and 6,779 MiB peak RSS. Both runs assigned the source-package region to every unique master ID and therefore did not enforce geographic ProductRegion membership. Keep those values as historical measurements only: their candidate counts, metrics, speedup, and search-cost projections are not valid for the corrected geography-scoped baseline.

Corrected 수도권 TL rerun은 YetiRank, uniform 1×, 1,000 iterations, seed 20261025, 기존 traveler split, metric implementation을 사용한다. 아래는 candidate filter 직전 full Master와 전체 inner-validation positives를 대상으로 한 privacy-safe aggregate다. Validation positive는 master-missing, geography-unresolved, other-region 여부와 무관하게 ground truth에 보존하며, candidate 밖 positive는 miss로 남는다.

| Filter 전 aggregate | 결과 |
| --- | ---: |
| Master source rows / distinct nonblank IDs | 7,442,866 / 7,442,866 |
| Blank ID rows / duplicate ID groups | 0 / 0 |
| Canonical capital candidate IDs, SIDO 11 | 1,158,806 |
| Canonical capital candidate IDs, SIDO 28 | 338,281 |
| Canonical capital candidate IDs, SIDO 41 | 1,555,710 |
| Total resolved candidates in capital mapping | 3,052,797 |
| Resolved IDs outside capital mapping | 4,329,195 |
| Geography-unresolved unique IDs / rate | 60,874 / 0.8179% |
| Validation positive queries / pairs | 432 / 883 |
| Candidate-covered positive queries / pairs | 345 / 568 |
| Candidate-covered pair rate | 64.3262% |
| Master-missing positive pairs | 245 |
| Master-present geography-unresolved positive pairs | 66 |
| Master-present resolved other-region positive pairs | 4 |

이 합계에서 후보 3,052,797개는 수도권 정책 코드별 resolved candidate count의 합이며 실제 post-filter inventory count와 일치했다. Validation positive 전체를 ground truth에 유지했다.

Corrected full-run은 YetiRank, uniform negative sampling 1×, 1,000 iterations, seed 20261025, 기존 traveler split 및 동일한 feature groups로 수행했다. 아래 runtime은 전체 입력 구성부터 scoring 완료까지의 실제 측정이다.

| 항목 | Corrected 수도권 TL |
| --- | ---: |
| Total runtime | 1,532.677초 |
| CatBoost fit | 6.296초 |
| Validation scoring | 1,322.860초 |
| Peak process RSS | 3,788 MiB |
| Validation queries | 432 |
| Candidate items | 3,052,797 |
| Scored rows | 1,318,808,304 |
| Maximum prediction frame | 262,144 rows |

| 비교 항목 | PR #88 historical | PR #89 historical optimized | Corrected geography |
| --- | ---: | ---: | ---: |
| Candidate scope | all source-tagged Master IDs | all source-tagged Master IDs | resolved canonical SIDO in versioned ProductRegion policy |
| Candidate items | 7,442,866 | 7,442,866 | 3,052,797 |
| Validation queries | 432 | 432 | 432 |
| Scored rows | 3,215,318,112 | 3,215,318,112 | 1,318,808,304 |
| Total runtime | 6,019초 | 4,655.510초 | 1,532.677초 |
| Fit runtime | 8.7초 | 9.329초 | 6.296초 |
| Scoring runtime | 5,764.1초 | 4,394.086초 | 1,322.860초 |
| Peak process RSS | 미기록 | 6,779 MiB | 3,788 MiB |

Runtime·RSS 행은 당시의 실제 기록이다. PR #88/#89와 corrected run의 candidate scope가 달라 실제 speedup, memory reduction, metric parity를 주장하지 않는다. Legacy와 optimized scorer의 exact score/rank/metric parity는 bounded synthetic test에서 검증했다.

| Metric | K | PR #88 historical scope | Corrected geography scope | 비교 |
| --- | ---: | ---: | ---: | --- |
| NDCG | 5 | 0.00207 | 0.000994975 | candidate scope differs |
| NDCG | 10 | 0.00416 | 0.001819529 | candidate scope differs |
| NDCG | 20 | 0.00495 | 0.004422569 | candidate scope differs |
| Recall | 5 | 0.00347 | 0.001350309 | candidate scope differs |
| Recall | 10 | 0.00863 | 0.003665123 | candidate scope differs |
| Recall | 20 | 0.01113 | 0.013001543 | candidate scope differs |
| MRR | 5 | 0.00174 | 0.001543210 | candidate scope differs |
| MRR | 10 | 0.00345 | 0.001929012 | candidate scope differs |
| MRR | 20 | 0.00381 | 0.002944442 | candidate scope differs |
| HitRate | 5 | 0.00463 | 0.004629630 | candidate scope differs |
| HitRate | 10 | 0.01852 | 0.006944444 | candidate scope differs |
| HitRate | 20 | 0.02546 | 0.020833333 | candidate scope differs |

#### Search strategy와 seed budget 결정

이전 4,655.510초 단가에 근거한 1,023 exhaustive 조합 55.1일, 최대 66-config greedy 3.56일, 73 config-equivalents 94.40시간 계산은 철회했다. Corrected full configuration은 1,532.677초(25.54분) 걸렸으며, 아래 projection은 이 한 번의 측정값을 각 configuration에 적용한 planning estimate다. Configurations 사이의 feature materialization 차이, 재시도, 환경 변동은 반영하지 않았다.

- **Exhaustive:** 1,023개 non-empty feature-group 조합 × 1,532.677초 = 1,567,928.6초(18.15일)/seed. 실행하지 않는다.
- **Feature greedy:** forward 55회 + single backward cleanup pass에서 최대 10회 제거 평가 + baseline 1회 = 최대 66 configuration-equivalents, 101,156.7초(28.10시간)/seed. Forward는 매 단계 남은 그룹을 하나씩 추가해 평가한다. Backward는 forward 결과에서 각 선택 그룹 제거를 한 번씩 평가하고 종료하며, iterative re-entry는 하지 않는다.
- **Negative-sampling screen:** uniform baseline을 포함한 4개 전략을 1×·1 seed로 비교한다. Uniform corrected baseline은 이미 측정됐으므로 추가 3개 전략은 약 1.28시간이다. 총 screen은 4 configuration-equivalents, 약 1.70시간이다.
- **Seed budget:** broad sampling/feature screening은 configuration당 1 seed. 선택한 최종 configuration만 총 3 seeds로 확인하며, 기존 screen run을 포함해 2회 추가(약 51.1분)한다. 세 seed는 stability heuristic이며 formal confidence interval이 아니다.
- **예상 run 수:** 4개 sampling screen configuration과, 그 baseline을 재사용한 feature greedy의 최대 65개 추가 평가, 최종 configuration의 2회 seed 반복을 합쳐 71 configuration-equivalents. 현재 측정값 기준 약 30.23시간이며, 이미 완료된 corrected uniform baseline 1회(25.54분)를 빼면 이후 약 29.80시간이다. Ratio 확장, objective search, hyperparameter grid 및 구현/실패 재시도는 제외한다.

따라서 exhaustive보다 forward + backward greedy를 선택한다. 한 축씩 잠그며 먼저 negative sampling을 비교하고, feature greedy는 선택된 sampling을 고정한 뒤 시작한다. 10개 feature group 전체 1,023개 조합은 실행하지 않는다.

Coverage 진단은 필요한 privacy-safe aggregate만 기록하며, 기존 195-ID/245-pair missing-key 결과의 원인을 다시 조사하지 않는다. VL 평가는 포함하지 않는다.

## Stage 2 — Negative sampling search

### 질문

같은 feature와 objective에서 sampled-unobserved의 선택 분포와 양이 ranking 결과를 얼마나 바꾸는가?

### 고정

- objective = YetiRank
- feature set = prototype 기준 set
- split / candidate / metric = 동일

### 초기 grid

~~~text
screen strategy ∈ {
  uniform,
  popularity-weighted,
  mixed,
  hard
}

screen ratio = 1
~~~

첫 sampling screen은 4개 configuration이다. Ratio 2/4/8/16 확장은 이 screen의 runtime과 지표를 본 뒤 별도 예산으로 결정한다.

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

- Corrected full-configuration 측정에 근거한 exhaustive 및 greedy projection과 seed budget은 위의 **Search strategy와 seed budget 결정**에 기록했다. Feature search는 backward cleanup을 한 번만 수행한다.
- 이에 **forward + backward greedy**를 선택하고 exhaustive 조합은 실행하지 않는다. Broad search는 후보당 1 seed를 사용하고 최종 configuration만 총 3 seeds로 확인한다. 세 seed 결과는 stability heuristic으로 사용하며 formal confidence interval로 해석하지 않는다.
- I2와 I4는 runnable이다. `fit_catboost`는 I3/I4를 포함한 행마다 helper가 발급한 immutable materialization과의 item key, trip partition, feature 값 일치를 확인한다. `inner-train` 문자열만으로는 fit을 허용하지 않는다.

첫 실제 search 축은 negative sampling이다. 다른 조건을 고정하고 1×에서 uniform, popularity-weighted, mixed, hard 네 전략을 비교한다. Uniform baseline은 현재 run을 재사용하고 나머지 세 configuration을 실행한다. 2×/4×/8×/16× ratio 확장 예산은 이 screen의 runtime과 결과를 본 뒤 별도 결정한다. 이 search는 아직 시작하지 않았다.

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

구체적인 search space는 objective search 결과와 과적합 패턴을 확인한 뒤 정한다. 초기 planning은 corrected full-TL configuration당 1,532.677초를 기준으로 하며, objective나 hyperparameter 조건이 달라지면 실제 비용을 다시 측정한다.

## Stage 6 — Seed 반복

Broad search 후보마다 seed 1개를 사용한다. 선택된 최종 configuration 한 개만 총 3 seeds로 확인한다.

이미 screening에서 실행한 seed를 재사용하면 finalist에는 2회 추가 run이 필요하다. 이 세 seed는 stability heuristic이며 formal CI가 아니다.

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

실행 책임은 분리되어 있다. #80은 traveler split과 I3/I4 재계산 경계를 완료했고, #81은 I2 정적 위치 계약을 완료했다. #82 runner integration은 inner-train item feature materialization까지 연결했으며 수도권 actual-TL Stage 1 smoke를 완료했다. 별도의 synthetic 평가 경로 벤치마크는 synthetic scoring parity와 자원 사용만 확인하며, 실제 TL에서의 최적화 개선을 입증하지 않는다.

### 준비된 카탈로그와 bounded scoring

동일 권역 후보 목록은 `PreparedItemCatalog.from_materialization(...)`으로 한 번 준비한다. 이 객체는 helper가 만든 I3/I4 및 선택한 정적 item 열을 정규화해 불변 tuple로 보관하며, feature transform 설정과 helper provenance가 일치하지 않으면 평가를 거부한다. I2 열은 category depth와 관계없이 모두 보존하고, query-context 열은 매 query 입력에서만 가져온다. 원래 학습 frame을 `fit_catboost`에 전달할 때는 기존 raw feature 값과 materialization을 사용해야 하며, catalog의 log1p 변환값을 다시 학습 전처리에 넣지 않는다.

Uniform sampling은 준비된 `catalog.inventory`를 사용하면 후보 목록을 매 query마다 복사·정렬하지 않고 같은 `random.sample` 결과를 만든다. `score_inner_validation_queries(...)` 호출자는 각 query의 권위 있는 `region`을 `query_features[trip_id]["region"]`에 반드시 제공해야 하며, 값이 후보 카탈로그 권역과 다르거나 누락되면 예측 전에 실패한다. `PreparedItemCatalog`의 정적 item columns는 candidate ID 오름차순으로 정렬해 immutable tuple로 보관한다. Scorer는 각 query마다 최대 262,144행 DataFrame만 만들고 정렬된 tuple slice를 재사용한다. 각 chunk는 NumPy partition으로 local top-K를 찾고, 동점에서는 item ID 오름차순을 지켜 global top-K를 합친다. 전체 candidate catalog는 메모리에 남으므로 frame 행 상한만으로 process RSS 상한을 보장하지 않는다.

합성 경로 확인 명령은 다음과 같다.

~~~bash
.venv/bin/python scripts/recommendation/benchmark_catboost_validation_stream.py --catalog-size 20000 --queries 60 --batch-rows 1024
~~~

벤치마크는 legacy full-frame와 prepared chunked 경로의 metric 일치, 구간별 wall time, 최대 prediction-frame 행 수를 보고한다. 별도 `tracemalloc` 수치는 Python 관리 메모리 할당 peak이며 process RSS가 아니다. workload 크기나 실행 환경이 다른 실제 TL 실행시간·메모리의 대리값으로 해석하지 않는다.

최근 합성 측정값은 위의 **Scoring 최적화 checkpoint** 표에 기록했다. 두 workload 모두 같은 legacy full-frame scorer와 optimized chunk scorer의 metric dictionary가 정확히 같았다. 이 측정은 scorer parity와 frame cap만 검증하며, CatBoost training이나 actual TL 병목·성능을 대신하지 않는다. `tracemalloc` 값은 Python 관리 할당량이고 RSS와 다르다. 300,000개 합성 catalog run의 process peak RSS도 해당 workload 한정 결과이며 actual catalog 규모에 대한 보장이 아니다.

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

실제 AI Hub Stage 1 prototype smoke와 optimized full-TL scoring benchmark는 위에 기록했으며, feasibility와 search-budget 결정 근거다. Sampling/feature/objective/hyperparameter search와 final three-seed 확인은 아직 수행하지 않았다. VL은 이번 checkpoint에서 확인하거나 읽지 않았다.
