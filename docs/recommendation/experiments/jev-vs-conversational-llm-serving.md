# JEV와 대화형 LLM 추천 서빙 비교

**관련 Issue:** #90  
**현재 상태:** 공개 benchmark fixture 구현 완료, 실제 endpoint benchmark 전

## 한눈에 보기

### 이 문서가 답하려는 질문

동일한 실제 sequential-recommendation 후보 집합을 처리할 때 **JEV 기반 판단 모델**과 **대화형 LLM 기반 생성 모델**의 서빙 특성과 ranking 결과가 얼마나 다른지 비교한다.

### 결론

초기 theme-overlap synthetic fixture는 adapter smoke test로만 유지한다. 실제 비교의 기본 fixture는 Hugging Face의 `sungjin-code/amazon-reviews-for-llm`이다.

이 데이터는 Amazon Reviews 2023에서 파생된 MIT licensed sequential recommendation dataset이며, 사용자의 과거 positive interaction을 바탕으로 같은 도메인의 후보 10개 중 실제 다음 positive item 1개를 찾는 문제를 제공한다.

기본 실행은 test 381건 전체가 아니라 seed로 고정한 **24건만** 사용한다. 사용자의 최근 history도 최대 8개로 제한하고 candidate description 길이도 제한해 endpoint 비용을 작게 유지한다.

JEV는 `Choice` probability distribution을 ranking으로 변환하고, conversational LLM은 같은 candidate text를 보고 strict JSON ranking을 생성한다.

### 현재 결정된 것

- 기본 fixture: `sungjin-code/amazon-reviews-for-llm`
- source license: MIT
- 평가 split: source dataset의 test split
- 기본 sample: 24 requests
- candidate count: source가 제공하는 고정 10개
- user context: target position 이전의 최근 positive history 최대 8개
- ground truth: 실제 다음 4~5점 interaction 1개
- candidate negatives: source dataset이 같은 domain에서 미상호작용 item으로 고정 생성
- metric: NDCG@K, HitRate@K, MRR
- model output failure는 품질 0점으로 포함한 failure-aware metric을 기본 비교값으로 사용
- 같은 fixture의 deterministic random ranking baseline도 함께 출력
- serving metric: success rate, throughput, latency p50/p95/mean
- token usage: endpoint가 usage metadata를 반환할 때만 기록
- 다운로드 파일은 `results/` 아래 Git-ignored cache에 저장
- 실제 다운로드 파일 SHA-256을 결과 metadata에 기록

### 아직 결정되지 않은 것

- 실제 JEV checkpoint/runtime
- 실제 conversational LLM/runtime
- 동일 GPU에서 순차 비교할지, 동등한 별도 장비를 사용할지
- warm-up 횟수와 반복 횟수
- 실제 endpoint 기준 최종 concurrency sweep

### 다음 행동

JEV와 conversational LLM endpoint가 준비되면 동일 24-request fixture로 smoke run을 수행한 뒤, 필요할 경우 같은 sample을 유지한 채 concurrency만 단계적으로 올린다.

## 1. 왜 synthetic theme 문제를 기본값에서 내렸는가

초기 fixture는 사용자와 candidate가 각각 theme 두 개를 가지고 overlap 개수를 relevance로 사용하는 deterministic toy problem이었다.

이 방식은 다음을 확인하기에는 좋다.

- adapter request/response shape
- JEV probability parsing
- LLM JSON parser
- metric 계산
- latency reporter

하지만 실제 추천 문제의 핵심인 **사용자의 과거 sequence에서 다음 선택을 추론하는 문제**가 없다. 따라서 model quality 비교의 기본 fixture로 쓰지 않는다.

`--fixture-source synthetic`으로 계속 사용할 수 있지만 smoke test 용도다.

## 2. 공개 benchmark

Source:

```text
Hugging Face
sungjin-code/amazon-reviews-for-llm
derived from Amazon Reviews 2023
license: MIT
```

이 dataset은 Books, CDs_and_Vinyl, Movies_and_TV, Video_Games 네 domain을 포함한다. rating 4 이상 interaction만 유지하므로 history와 target은 source build에서 positive interaction으로 취급한다.

사용자별 interaction은 시간순으로 정렬된 뒤 train/valid/test가 8:1:1 비율로 나뉜다. test row마다 candidate 10개가 이미 제공된다.

```text
past positive history
        |
        v
test interaction
        |
        +--> correct next item (1)
        |
        +--> same-domain sampled alternatives (9)
```

source dataset은 negative candidate에서 해당 사용자가 전체 sequence에서 interaction한 item을 제외한다. ground truth 위치도 candidate list 안에서 섞여 있어 특정 index를 고르는 방식으로 점수를 얻을 수 없다.

## 3. benchmark용 소량 추출

대용량 benchmark가 목적이 아니므로 기본값은 24건이다.

```text
test rows: 381
      |
      v
group by domain
      |
seeded shuffle
      |
round-robin selection
      |
24 requests
```

가능한 한 네 domain이 고르게 포함되도록 domain별 round-robin selection을 사용한다.

각 request에 target 이후 history가 섞이지 않도록:

```text
history.pos < target.pos
```

조건을 적용하고, 그중 가장 최근 8개만 사용한다.

원래 Amazon `user_id`, `asin`, `parent_asin`은 model prompt나 benchmark report에 사용하지 않는다. benchmark 내부 candidate는 요청별 `candidate-00` ~ `candidate-09`로 다시 이름 붙인다.

## 4. 내려받는 데이터

전체 source repository를 clone하지 않는다. 다음 세 파일만 받는다.

```text
interactions.parquet
test.parquet
items_text.parquet
```

역할은 다음과 같다.

| 파일 | 사용 목적 |
| --- | --- |
| `interactions.parquet` | target 이전 사용자 history 구성 |
| `test.parquet` | 10개 candidate와 ground truth |
| `items_text.parquet` | history/candidate title과 description |

기본 cache:

```text
results/issue-90/hf-amazon-llm/
```

`results/`는 Git에서 제외된다. benchmark JSON에는 세 파일의 SHA-256만 기록해 실제 비교에서 동일 파일을 사용했는지 확인한다.

## 5. 모델에 전달되는 요청

예시는 구조만 보여준다.

```text
This is a sequential recommendation task.
The candidate domain is Books.

The user's recent positively rated/reviewed history,
oldest to newest, is:

1. <past item title>: <description>
2. <past item title>: <description>
...
8. <past item title>: <description>

Rank all candidates by which item is most likely to be
the user's next positively rated/reviewed item.
```

후보 10개는 양쪽 backend에 동일한 title/description으로 전달한다.

candidate description은 기본 320자로 자른다. 이는 긴 product description 때문에 token/cost가 과도하게 증가하는 것을 막기 위한 serving benchmark 조건이다.

## 6. JEV 경로

```text
RecommendationRequest
      |
      v
Choice question
      |
POST /v1/systemone
      |
      v
probability per candidate
      |
descending sort
      |
      v
RankingResult
```

모든 candidate에 probability가 있어야 성공이다. 누락되거나 범위를 벗어난 probability가 있으면 실패로 집계한다.

## 7. Conversational LLM 경로

```text
RecommendationRequest
      |
      v
chat prompt
      |
POST /v1/chat/completions
      |
      v
{"ranking":[...]}
      |
strict parser
      |
      v
RankingResult
```

candidate 누락, 중복, 알 수 없는 candidate, Markdown fence, 추가 field가 있으면 실패로 집계한다.

이 정책은 생성형 model의 output-contract 안정성을 serving 특성의 일부로 보기 위한 것이다.

## 8. 품질 지표

각 source test row에는 relevant candidate가 정확히 하나 있다.

따라서 다음 지표를 사용한다.

- **NDCG@K**: ground-truth item이 상위에 있을수록 높은 점수
- **HitRate@K**: ground-truth item이 top K 안에 들어왔는지
- **MRR(Mean Reciprocal Rank)**: ground-truth rank가 1이면 1, 2이면 1/2, 10이면 1/10

특히 이 benchmark에서는 MRR이 직관적인 핵심 ranking metric이다.

JSON parsing이나 JEV response validation에 실패한 요청을 품질 평균에서 제거하면 실패가 많은 backend의 점수가 부풀 수 있다. 따라서 기본 비교값은 실패 요청을 0점으로 포함한 `quality_failure_aware`이며, 진단을 위해 성공 요청만의 `quality_success_only`도 함께 기록한다.

동일한 24-request fixture를 seed-fixed random ranking으로 섞은 `quality_random_baseline`도 출력해 작은 sample의 절대 점수를 해석할 기준으로 사용한다.

## 9. 실행

endpoint가 준비되면 기본 benchmark는 다음과 같이 실행한다.

```bash
python scripts/recommendation/serving_benchmark.py \
  --fixture-source hf-amazon-llm \
  --requests 24 \
  --history-size 8 \
  --description-chars 320 \
  --concurrency 1 \
  --k 5 \
  --jev-base-url http://localhost:8790 \
  --jev-model <JEV_MODEL> \
  --llm-base-url http://localhost:8000/v1 \
  --llm-model <LLM_MODEL>
```

인증이 필요한 경우 secret 자체를 argument로 넘기지 않는다.

```bash
export JEV_API_KEY=...
export LLM_API_KEY=...

python scripts/recommendation/serving_benchmark.py \
  --llm-model <LLM_MODEL> \
  --jev-api-key-env JEV_API_KEY \
  --llm-api-key-env LLM_API_KEY
```

첫 실행에서 세 parquet file만 cache에 내려받는다. 이후 실행은 cache를 재사용한다.

synthetic smoke fixture는 다음처럼 선택한다.

```bash
python scripts/recommendation/serving_benchmark.py \
  --fixture-source synthetic \
  --requests 20 \
  --candidates 8 \
  --llm-model <LLM_MODEL>
```

## 10. 결과 JSON

결과에는 다음을 포함한다.

- fixture source
- dataset repository / revision
- selected request count
- history size
- candidate count
- source parquet SHA-256
- seed
- concurrency / K
- backend별 success/failure
- throughput
- latency p50/p95/mean
- random ranking quality baseline
- failure-aware NDCG@K / HitRate@K / MRR
- success-only NDCG@K / HitRate@K / MRR
- token usage
- 실패 sample

raw user identifier나 source local path는 결과에 넣지 않는다.

## 11. 공정 비교 조건

실제 latency 비교에서는 model family 외 요인을 함께 기록해야 한다.

- model/checkpoint/version
- GPU/CPU 및 장비 수
- serving runtime/version
- quantization
- batch/scheduler 설정
- request count
- concurrency
- warm-up
- network path
- source file SHA-256

서로 다른 장비에서 실행했다면 "JEV가 LLM보다 N배 빠르다"처럼 model 자체의 효과로 일반화하지 않고, 해당 deployment 조건의 end-to-end 결과라고 기록한다.

## 12. 한계

### 확인된 사실

- source benchmark는 Amazon product recommendation이며 여행 추천 dataset이 아니다.
- source build의 positive interaction은 rating 4~5다.
- test candidate는 10개이며 ground truth는 정확히 하나다.
- user history와 item text를 이용해 text-based ranker가 평가 가능하다.

### 해석

이 benchmark는 실제 travel domain quality를 재현하려는 목적이 아니다. JEV와 conversational LLM을 **동일한 실제 recommendation ranking problem**에서 소량 비교하기 위한 중간 benchmark다.

### 미결정 / 추가 검증 필요

Amazon benchmark에서 좋은 ranking을 보였다고 실제 여행 POI 추천 품질이 좋다는 뜻은 아니다.

또한 source dataset은 active users를 대상으로 하고 item overlap이 낮다. 따라서 이 결과는 일반 recommender 전체 성능보다는 text-conditioned cold-item ranking 성격이 강하다.

## 13. 검증

네트워크 없는 테스트는 다음을 검증한다.

- JEV/LLM adapter contract
- strict LLM JSON parsing
- deterministic synthetic fallback
- source parquet schema fixture loading
- target 이후 history 제외
- 10 distinct candidates
- ground-truth candidate invariant
- description truncation
- Git-ignored download cache reuse
- NDCG / HitRate / MRR 계산

실제 Hugging Face 다운로드와 JEV/LLM endpoint 호출은 endpoint/runtime이 준비된 환경에서 실행한다.
