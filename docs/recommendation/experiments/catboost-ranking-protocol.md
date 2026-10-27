# CatBoost cold-user ranking 실험 프로토콜

**관련 Issue:** #79, #82
**현재 상태:** PR #88/#89의 과거 full-run은 TN_POI_MASTER 모든 고유 ID에 source-package region을 부여한 잘못된 geography scope였다. Runner는 #81 canonical administrative location과 versioned `poi-catalog-candidate-v1` 정책으로 후보 geography를 분리했다. Corrected 수도권 TL full benchmark는 3,052,797개 후보·432 validation query·1,318,808,304 scored rows에서 total 1,139.035초, runner-scoped scoring 959.962초, peak RSS 3,786 MiB였다. 이 비용을 기준으로, 향후 full-catalog search가 end-to-end 300초 이내가 되면 forward + 정확히 한 번의 backward cleanup pass, broad screen 1 seed/config, 선택된 finalist 3 total seeds를 쓴다. 현재는 scoring이 cutoff를 넘으므로 그 conditional plan의 실행을 보류한다. 다음 checkpoint는 별도의 Candidate Generation → CatBoost reranking 설계와 runtime 재측정이다. VL은 읽지 않았다.

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
- Conditional full-catalog decision, if the remeasured end-to-end configuration is at or below the 300-second gate: choose forward + exactly one backward cleanup pass (up to 66 config-equivalents including baseline), broad screen at 1 seed/config, then the selected finalist at 3 total seeds. At the measured 1,139.035-second/config cost, 10-group exhaustive would take 13.49 days/seed and the 66-config greedy path 20.88 hours/seed. Keep this chosen strategy/budget on hold until the gate passes; no search has started.
- 공식 VL은 모든 tuning이 끝난 뒤 사용

## 선행 작업 상태

- I2 Administrative Location의 feature 계약과 synthetic 검증은 #81에서 완료됐다. `canonical_admin_sido_code`, `canonical_admin_sgg_code`, `canonical_admin_location_status`를 모델 입력으로 사용한다. #82 actual TL run은 한 권역의 canonical eligibility, unresolved geography, validation candidate coverage aggregate를 기록했다. 전 권역 source별 provenance·conflict와 전체 coverage audit은 별도 후속 작업으로 남아 있다.
- I3 Popularity의 inner-train 재계산 경계와 I4 Historical POI의 `recompute_inner_train_visit_type_codes` helper는 #80에서 구현·검증 완료됐다.
- #82 runner는 한 권역의 TL trip-owner, positive interaction, `TN_VISIT_AREA_INFO` 이벤트, AI Hub 후보 feature를 받아 traveler-group split을 만들고 I3/I4를 inner-train에서 다시 계산한다. 기존 outer-TL I3/I4 값은 덮어쓴다.
- CatBoost runtime dependency는 `pyproject.toml`과 `uv.lock`에서 고정한다. Issue #82 검증 환경은 Python 3.12와 CatBoost 1.2.10을 사용한다.

## 다음 행동

#80/#81, scorer profiling, corrected actual-TL benchmark, synthetic/bounded parity와 full-run search-cost 계산을 완료했다. PR #88/#89의 과거 full-run은 candidate geography 오류 때문에 corrected baseline을 대체하지 않는다. Corrected default scorer도 16.0분이 걸려 5분 cutoff를 넘는다. 다음 checkpoint는 candidate generation과 CatBoost reranking을 분리하는 설계를 비교하고 전체 검증계약 아래 runtime을 다시 측정하는 것이다. 그 설계 전에는 negative-sampling search를 시작하지 않는다.

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

Scorer는 candidate ID 순서에 정렬된 immutable item feature columns를 query별 bounded batch로 읽고, 전체 score 배열을 정렬하지 않고 NumPy partition과 경계 동률 처리를 사용한다. Final runner는 131,072행 이하의 DataFrame batch를 사용하며, static item-side columns를 한 번 만든 DataFrame에서 shallow `.iloc` views로 재사용한다. Query context만 batch별 broadcast한다. Candidate universe, feature column/value, I2/I3/I4, validation-positive ground truth, metric, tie-break와 leakage boundary는 변경하지 않는다. Generic scorer의 기본 DataFrame 경로는 비교를 위해 유지한다.

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

Corrected full-run은 YetiRank, uniform negative sampling 1×, 1,000 iterations, seed 20261025, 기존 traveler split 및 동일한 feature groups로 수행했다. Final run은 131,072행 batch와 cached static item-side frame을 사용했다. Runtime은 전체 입력 구성부터 scoring 완료까지의 실제 측정이다.

| 항목 | Corrected 수도권 TL |
| --- | ---: |
| Total runtime | 1,139.035초 |
| CatBoost fit | 3.880초 |
| Validation scoring | 959.962초 |
| Peak process RSS | 3,786 MiB |
| 500 ms sampled scoring RSS peak | 3,687.1 MiB |
| Validation queries | 432 |
| Candidate items | 3,052,797 |
| Scored rows | 1,318,808,304 |
| Maximum prediction frame | 131,072 rows |

| 비교 항목 | PR #88 historical | PR #89 historical optimized | Corrected geography |
| --- | ---: | ---: | ---: |
| Candidate scope | all source-tagged Master IDs | all source-tagged Master IDs | resolved canonical SIDO in versioned ProductRegion policy |
| Candidate items | 7,442,866 | 7,442,866 | 3,052,797 |
| Validation queries | 432 | 432 | 432 |
| Scored rows | 3,215,318,112 | 3,215,318,112 | 1,318,808,304 |
| Total runtime | 6,019초 | 4,655.510초 | 1,139.035초 |
| Fit runtime | 8.7초 | 9.329초 | 3.880초 |
| Scoring runtime | 5,764.1초 | 4,394.086초 | 959.962초 |
| Peak process RSS | 미기록 | 6,779 MiB | 3,786 MiB |

Runtime·RSS 행은 당시의 실제 기록이다. PR #88/#89와 corrected run의 candidate scope가 달라 이들 간 actual speedup, memory reduction, metric parity를 주장하지 않는다. Corrected uncached 131,072행과 cached 131,072행 full runs는 같은 geography, query, candidate count, model configuration, seed, metrics와 tie-break를 사용했고 full metrics가 정확히 같았다. 이 scope 안의 observed scoring time은 1,151.903초에서 959.962초로 16.7% 감소했고 total은 1,332.190초에서 1,139.035초로 14.5% 감소했다. 이는 단일 run 비교이므로 다른 환경의 보장값이 아니다.

##### Scoring profiler와 bounded inference sweep

두 개의 같은 8-query full-catalog cohort sweep에서 각 variant는 3,052,797개 후보 전체를 평가했고 run 안에서는 같은 fitted model을 재사용했다. 한 variant는 24,422,376개 row를 처리했다. 모든 variant의 top-K item/score 순서와 metric dictionary는 첫 DataFrame baseline과 정확히 같았다. 작은 cohort의 절대 ranking metric은 성능 평가로 쓰지 않고 scorer parity와 runtime만 비교한다.

| DataFrame batch rows | sweep 1 wall | sweep 2 wall | sweep 1 / 2 sampled scoring RSS peak |
| ---: | ---: | ---: | ---: |
| 65,536 | 23.736초 | 20.527초 | 3,574 / 3,572 MiB |
| 131,072 | 23.503초 | 19.574초 | 3,580 / 3,580 MiB |
| 262,144 | 24.928초 | 19.876초 | 3,613 / 3,601 MiB |
| 524,288 | 23.889초 | 19.853초 | 3,764 / 3,734 MiB |
| 1,048,576 | 22.542초 | 20.609초 | 3,950 / 4,019 MiB |

두 run의 시간 순위가 달랐고 batch를 키울수록 memory가 증가했다. 131,072와 1,048,576의 2-run 평균은 각각 약 21.54초와 21.58초로 사실상 비슷해 131,072행을 선택했다. 더 큰 batch가 안정적으로 빠르다는 근거는 없고 131,072는 500 ms sampled RSS peak가 더 낮았다.

같은 세 번째 8-query cohort에서 static item-column 재사용을 비교했다. 131,072행 DataFrame baseline은 19.574초였고, static item columns 5개를 한 번 구성한 뒤 query별로 shallow batch view를 재사용한 경로는 cache 생성 0.460초를 포함해 18.122초였다. Frame build는 6.341초에서 2.970초로 줄었고, scoring wall은 7.4% 짧아졌다. Prediction은 11.911초에서 13.354초로 늘었으며, 500 ms sampled scoring RSS peak는 3,580 MiB에서 3,779 MiB로 늘었다. 추정 cache 크기는 122,111,880 bytes였다. Exact score/rank/metric parity를 확인했고 이 측정 때문에 full runner에 cache 경로를 채택했다. Full run에서는 sampled scoring RSS peak가 uncached보다 93 MiB 높았으나 total process peak는 3,787에서 3,786 MiB로 거의 같았다.

DataFrame batch 65,536의 상세 frame stage는 candidate/item slice 0.478초, query-context broadcast 0.014초, container construction 6.061초로 frame 총 6.554초와 약 0.001초 차이였다. 세 번째 sweep의 cached path에서는 item slice 0.420초, query broadcast 0.033초, container construction 2.517초, one-time cache 0.460초였다. Query-context broadcast는 작고 DataFrame/container construction이 큰 변동을 설명한다.

다른 inference 입력도 같은 full-candidate cohort에서 비교했고 exact parity는 유지됐다. Direct `model.predict(ndarray)`는 262,144행에서 23.550초, 1,048,576행에서 24.562초였고, DataFrame 구성 시간은 짧았지만 predict가 각각 19.049초 및 18.814초로 느려졌다. DataFrame→Pool은 20.025초, NumPy→Pool은 25.235초였다. 명시적 `thread_count=1/2/4`는 30.082/26.229/23.544초로 같은 cohort의 default DataFrame 경로보다 느렸다. 이 결과는 현재 머신과 CatBoost 1.2.10 설정에 한정되며 thread 수가 바뀐 다른 장비의 속도를 예측하지 않는다. CatBoost 1.2.10에 Pool `quantize` API는 있지만 mixed-feature 모델에서 `model.predict(quantized_pool)`은 필요한 feature가 없다는 오류로 exact parity를 충족하지 못해 sweep에서 제외했다.

##### Final cached-run bottleneck profile

Runner evaluation-stage timer measured scoring wall at 959.962초. The internal profiler recorded `scoring_wall_seconds=959.960`; the 0.002초 difference is timer-boundary overhead. Use 959.962초 for the recorded full-config runtime and cost projections, and the internal profiler duration for disjoint stage accounting below. That accounting sums context normalization, ground-truth prep, frame, one-time cache, prediction, top-K, metrics, and unaccounted sections without overlap. RSS is sampled every 500 ms, so brief spikes can be missed; the reported scoring value is a **500 ms sampled peak**, not a guaranteed instantaneous maximum. Final aggregate frame substages total 162.735초, 0.030초 below the 162.765초 batch-frame total due to timer-boundary/assembly overhead. Cache build 0.485초 is tracked once, separately from the batch-frame subtotal.

| Full-run measure | Uncached, 262,144 rows | Uncached, 131,072 rows | Cached static items, 131,072 rows |
| --- | ---: | ---: | ---: |
| Total / scoring wall | 1,556.372 / 1,347.531초 | 1,332.190 / 1,151.903초 | 1,139.035 / 959.962초 |
| Frame build | 404.061초 | 353.356초 | 162.765초 |
| Prediction | 850.519초 / 1.551M rows/s | 725.684초 / 1.818M rows/s | 724.048초 / 1.821M rows/s |
| Top-K partition / tie / local sort / merge | 90.153 / 1.649 / 0.185 / 0.101초 | 69.873 / 1.513 / 0.290 / 0.187초 | 69.677 / 1.515 / 0.286 / 0.186초 |
| Metric / unaccounted | 0.025 / 0.830초 | 0.018 / 0.976초 | 0.017 / 0.977초 |
| Peak process RSS / 500 ms sampled scoring RSS peak | 3,790 / 3,641.9 MiB | 3,787 / 3,593.6 MiB | 3,786 / 3,687.1 MiB |
| Query elapsed p50/p95/p99/max | 3.072 / 3.486 / 3.714 / 4.086초 | 2.632 / 2.924 / 3.077 / 3.158초 | 2.192 / 2.478 / 2.606 / 2.681초 |
| Query row rate p50/p95 | 0.994 / 1.061M rows/s | 1.160 / 1.238M rows/s | 1.393 / 1.512M rows/s |
| CPU user/system / CPU per wall | 2,446.35 / 334.88초 / 2.064 | 2,149.64 / 548.71초 / 2.343 | 1,956.33 / 553.49초 / 2.615 |

Compared with the same-scope uncached 131,072-row full run, final frame build fell by 190.591 seconds (53.9%) while prediction time stayed nearly flat; scoring wall fell by 16.7% and total runtime by 14.5%. Compared with the original uncached 262,144-row full profile, observed scoring time fell by 28.7%. Lower user CPU time across runs is an observed process delta, not an isolated cache effect.

| Stage | Seconds | Scoring wall share |
| --- | ---: | ---: |
| Candidate/item slice | 23.319 | 2.43% |
| Query-context broadcast | 1.823 | 0.19% |
| DataFrame/container construction | 137.592 | 14.33% |
| Frame build total (subtotal) | 162.765 | 16.96% |
| Static item cache setup | 0.485 | 0.05% |
| `model.predict` (1.3188B rows) | 724.048 | 75.42% |
| Top-K partition | 69.677 | 7.26% |
| Boundary ties | 1.515 | 0.16% |
| Local sort | 0.286 | 0.03% |
| Global merge | 0.186 | 0.02% |
| Metric computation | 0.017 | <0.01% |
| Query-context normalization + ground truth | 0.005 | <0.01% |
| Unaccounted | 0.977 | 0.10% |

`model.predict` throughput was 1.821M rows/s; query scoring time p50/p90/p95/p99/max was 2.192/2.425/2.478/2.606/2.681초, and per-query row rate p50/p95 was 1.393/1.512M rows/s. Scoring CPU user/system deltas were 1,956.33/553.49초 over the 959.960초 internal-profiler wall (2.615 CPU-seconds per wall-second). Total profiler remainder was 0.977초, about 0.10% of that profiler wall.

Final process RSS snapshots (MiB): after Master load 2,805; after geography filter 1,993; after materialization 3,041; after PreparedItemCatalog 3,446; after train frame 3,481; after fit 3,565; 500 ms sampled scoring RSS peak 3,687; after scoring 3,547. Process peak across all stages was 3,786 MiB.

The evidence classifies the result as **A — inference-bound**: prediction accounts for 75.4% of scoring wall, with DataFrame construction the secondary cost at 17.0%. Top-K is 7.5%; context prep and metrics are negligible. The cache reduces frame construction but the resulting 959.962초 full scoring time remains far above the 5-minute cutoff. The next action is a separate Candidate Generation → CatBoost reranking design. Do not start sampling search or implement candidate retrieval in this checkpoint.

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

#### Conditional search strategy와 seed budget 결정

이전 PR #89의 geography-unfiltered timing과 uncached configuration cost를 사용한 projection은 superseded다. Corrected runner-scoped full run은 1,139.035초/configuration (18.98분)이 걸렸고 scoring stage는 959.962초였다. **Conditional strategy decision:** 이후 Candidate Generation → CatBoost reranking 설계 뒤에도 full-catalog evaluation을 사용하고 end-to-end 1-config runtime이 300초 이하면, forward selection 뒤 정확히 한 번 backward cleanup pass를 사용한다. Broad screen은 1 seed/config이며, 선택된 finalist는 해당 configuration의 screen seed를 재사용해 총 3 seeds로 평가한다. Backward pass는 선택 집합의 각 feature를 한 번 제거 평가하고 종료하며 반복 제거/재진입은 하지 않는다. Runtime gate가 충족되기 전까지 이 계획은 실행 보류 상태다. 아래 비용은 측정된 1,139.035초/configuration을 그대로 적용한 산술이며 재시도·환경 변동은 포함하지 않는다.

- **Exhaustive:** 1,023개 non-empty feature-group 조합 × 1,139.035초 = 1,165,232.805초 (약 13.49일)/seed.
- **Chosen conditional feature strategy:** forward 55회 + exactly one backward cleanup pass에서 최대 10회 제거 평가 + baseline 1회 = 최대 66 configuration-equivalents, 75,176.310초 (약 20.88시간)/seed. Backward는 forward 선택 집합에서 각 선택 그룹을 한 번씩 제거 평가하고 종료하며 iterative re-entry는 없다.
- **Conditional broad sampling budget:** uniform baseline을 재사용해 4개 strategy를 1×·1 seed/config로 screen하면 총 약 1.27시간이다. Uniform baseline은 완료됐으므로 추가 3개는 약 0.95시간이며, gate 통과 전까지 시작하지 않는다.
- **Conditional finalist seed budget:** broad screen은 1 seed/config, 선택된 configuration은 해당 screen seed를 포함해 총 3 seeds로 평가한다. 추가 두 번의 repeat는 약 0.63시간이다. 세 seed는 stability heuristic이지 formal confidence interval이 아니다.
- **Conditional plan total / remaining:** completed uniform baseline 1 + remaining 3 sampling configs + greedy baseline 이후 최대 65개 추가 feature configs + finalist 2-seed repeats = 71 configuration-equivalents, 약 22.46시간. 완료된 baseline을 빼면 70 equivalents, 약 22.15시간이 남는다. Ratio 확장, objective, hyperparameter와 재시도는 제외한다.

비용 때문에 1,023개 exhaustive 조합 대신 future full-catalog search에는 위 greedy strategy를 선택했다. 단, 현재 1,139.035초 configuration cost는 300초 gate를 넘으므로 sampling/feature/objective/hyperparameter search와 seed repeats는 실행하지 않는다. Candidate Generation → CatBoost reranking 설계, 같은 candidate/evaluation 계약 검증, end-to-end runtime 재측정 후 300초 이하일 때만 conditional plan을 시작한다.

Coverage 진단은 필요한 privacy-safe aggregate만 기록하며, 기존 195-ID/245-pair missing-key 결과의 원인을 다시 조사하지 않는다. VL 평가는 포함하지 않는다.

## Stage 2 — Negative sampling search

**상태: 미시작.** Final full-catalog cached scoring은 959.962초로 5분 cutoff를 넘는다. Candidate-generation/reranking 설계와 재측정 전까지 이 Stage 및 이후 search stage를 시작하지 않는다.

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

- Full-catalog을 유지한다는 가정 아래의 exhaustive 및 greedy 비용 projection은 위 **Search strategy와 seed budget 결정**에 기록했다. Feature search 계획을 실행하게 되면 backward cleanup은 단일 pass로 제한한다.
- Full-catalog scorer는 cutoff를 넘으므로 위에서 정한 conditional full-catalog strategy와 seed budget은 실행 보류 상태다. Post-design end-to-end runtime이 300초 이하일 때 forward + exactly one backward cleanup pass, broad search 1 seed/config, selected finalist 3 total seeds를 적용한다.
- I2와 I4는 runnable이다. `fit_catboost`는 I3/I4를 포함한 행마다 helper가 발급한 immutable materialization과의 item key, trip partition, feature 값 일치를 확인한다. `inner-train` 문자열만으로는 fit을 허용하지 않는다.

기존 search plan의 첫 축은 negative sampling이었으나 실행하지 않았다. Candidate-generation/reranking 설계와 end-to-end runtime 재측정 뒤에도 cutoff를 만족하면 그때 uniform, popularity-weighted, mixed, hard 1× screen을 다시 평가한다. Ratio 확장 계획도 미결정이다.

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

구체적인 search space는 objective search 결과와 과적합 패턴을 확인한 뒤 정한다. Full-catalog을 유지한다는 가정에서 현 corrected configuration cost는 1,139.035초지만 5분 cutoff를 넘으므로 search가 재승인되기 전 planning 참고값으로만 쓴다.

## Stage 6 — Seed 반복

Conditional seed decision: broad search candidate마다 1 seed/config을 사용하고, 선택된 finalist는 해당 configuration의 screen seed를 재사용해 총 3 seeds로 확인한다. 현재 full-catalog run이 cutoff를 넘으므로 retrieval/reranking 설계와 300초 gate 통과 전까지 seed 반복을 실행하지 않는다.

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

Uniform sampling은 준비된 `catalog.inventory`를 사용하면 후보 목록을 매 query마다 복사·정렬하지 않고 같은 `random.sample` 결과를 만든다. `score_inner_validation_queries(...)` 호출자는 각 query의 권위 있는 `region`을 `query_features[trip_id]["region"]`에 반드시 제공해야 하며, 값이 후보 카탈로그 권역과 다르거나 누락되면 예측 전에 실패한다. `PreparedItemCatalog`의 정적 item columns는 candidate ID 오름차순으로 immutable tuple에 보관한다. Final runner는 최대 131,072행 prediction frame을 만들고, 정적 item-side columns는 한 번 만든 DataFrame에서 shallow batch view로 재사용하며 query-context만 broadcast한다. 각 chunk는 NumPy partition으로 local top-K를 찾고, 동점에서는 item ID 오름차순을 지켜 global top-K를 합친다. 전체 candidate catalog와 static cache는 메모리에 남으므로 frame 행 상한만으로 process RSS 상한을 보장하지 않는다.

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

실제 AI Hub Stage 1 prototype smoke, corrected full-TL scoring profile와 cached-item rerun은 위에 기록했다. Scoring이 5분 cutoff를 넘으므로 다음 단계는 retrieval/reranking architecture design이며, sampling/feature/objective/hyperparameter search와 final three-seed 확인은 아직 수행하지 않았다. VL은 이번 checkpoint에서 확인하거나 읽지 않았다.
