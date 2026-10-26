# JEV와 대화형 LLM 추천 서빙 비교

**관련 Issue:** #90  
**현재 상태:** 구현 완료, 실제 endpoint benchmark 전

## 한눈에 보기

### 이 문서가 답하려는 질문

동일한 추천 요청과 후보 집합을 처리할 때 **JEV 기반 판단 모델**과 **대화형 LLM 기반 생성 모델**의 서빙 특성이 얼마나 다른지 비교한다.

### 결론

이 실험은 기존 CatBoost/AI Hub 추천 실험과 분리된 synthetic benchmark다. 실제 여행로그나 TourAPI 데이터를 읽지 않는다.

JEV는 대화문을 생성하는 모델이 아니라, 하나의 상태(state)에 대해 정해진 선택지 중 하나를 고르고 후보별 확률을 반환하는 **판단 전용 모델(decision language model)**로 사용한다. 이 harness에서는 Choice 확률 분포 전체를 후보 ranking으로 변환한다.

대화형 LLM은 같은 후보 정보를 보고 모든 후보 ID를 순서대로 반환하도록 요청한다. 생성 결과는 strict JSON으로 검증하고, 누락·중복·추가 후보가 있으면 실패로 집계한다.

### 현재 결정된 것

- 두 backend는 같은 synthetic request와 candidate descriptions를 사용한다.
- synthetic relevance는 사용자 선호 theme와 후보 theme의 겹치는 개수(0~2)다.
- 품질 비교 지표는 NDCG@K와 HitRate@K다.
- 서빙 비교 지표는 success rate, throughput, latency p50/p95/mean이다.
- token usage는 endpoint가 usage metadata를 제공할 때만 집계한다.
- 실제 API key 값은 CLI 인자가 아니라 환경변수 이름으로만 전달한다.

### 아직 결정되지 않은 것

- 어떤 JEV checkpoint/runtime을 최종 비교 대상으로 사용할지
- 어떤 conversational LLM과 serving runtime을 사용할지
- GPU, batch size, quantization, concurrency를 어떤 조건으로 고정할지
- 실제 서비스 후보 수를 반영한 candidate-count sweep 범위

### 다음 행동

동일 장비 또는 비교 가능한 격리 환경에서 후보 수와 concurrency를 단계적으로 올리며 실제 endpoint benchmark를 실행한다.

## 필요한 용어

- **판단 언어 모델(decision language model)**: 자유로운 문장을 생성하기보다 미리 정의된 선택/점수/예·아니오 같은 구조화된 결정을 반환하는 모델.
- **JEV System One**: `POST /v1/systemone` 형식으로 `state`와 typed `questions`를 받아 구조화된 `answers`를 반환하는 인터페이스.
- **대화형 LLM(conversational LLM)**: chat completion 형식으로 자연어 출력을 생성하는 일반 목적 언어 모델. 이 benchmark에서는 JSON ranking을 생성하도록 제한한다.
- **후보 집합(candidate set)**: 한 추천 요청에서 순위를 매길 대상 아이템 목록.
- **NDCG@K**: 관련도가 높은 아이템을 상위에 둘수록 높은 값을 주는 ranking metric.

## 1. 비교 구조

```text
Synthetic request generator
        |
        +------------------------------+
        |                              |
        v                              v
JEV adapter                    Conversational LLM adapter
POST /v1/systemone             POST /v1/chat/completions
Choice criteria                JSON ranking generation
        |                              |
candidate probabilities                |
        |                              |
        +----------> canonical ranking <+
                       |
                       v
        latency / throughput / validity
               NDCG@K / HitRate@K
```

JEV 경로에서는 후보 ID를 Choice의 `criteria` key로 사용하고, 후보 설명을 criteria description으로 전달한다. 응답의 `probabilities`가 모든 후보를 정확히 포함할 때만 성공으로 본다.

LLM 경로에서는 `{"ranking":["id1","id2",...]}`만 허용한다. Markdown code fence, 설명 문장, 후보 누락, 중복, 미등록 후보가 있으면 benchmark 성공으로 세지 않는다. 생성형 모델의 출력 파싱 비용과 schema 불안정성도 서빙 특성의 일부로 보기 때문이다.

## 2. synthetic relevance

각 요청은 두 개의 선호 theme를 가진다. 각 후보도 두 개의 theme를 가진다.

```text
relevance(candidate) = | preferred_themes ∩ candidate_themes |
```

따라서 relevance는 0, 1, 2 중 하나다. 모든 후보가 0인 요청은 첫 후보를 강제로 완전 일치시켜 최소 한 개의 relevant candidate가 존재하도록 한다.

이 정답은 **실제 여행 선호도 ground truth가 아니다.** 두 backend가 같은 명시적 규칙을 얼마나 잘 복원하는지 확인하기 위한 synthetic task다.

## 3. 실행

기본값은 로컬 JEV-compatible endpoint와 OpenAI-compatible chat endpoint를 가정한다.

```bash
python scripts/recommendation/serving_benchmark.py \
  --requests 100 \
  --candidates 16 \
  --concurrency 8 \
  --k 5 \
  --jev-base-url http://localhost:8790 \
  --jev-model jev-latest \
  --llm-base-url http://localhost:8000/v1 \
  --llm-model <MODEL_ID>
```

인증이 필요한 경우 secret 자체를 명령행에 넣지 않는다.

```bash
export JEV_API_KEY=...
export LLM_API_KEY=...

python scripts/recommendation/serving_benchmark.py \
  --llm-model <MODEL_ID> \
  --jev-api-key-env JEV_API_KEY \
  --llm-api-key-env LLM_API_KEY
```

출력은 JSON 한 개이며 다음을 포함한다.

- 요청 수, 후보 수, seed, concurrency
- 성공/실패 수와 success rate
- elapsed time과 requests/sec
- latency p50/p95/mean
- NDCG@K
- HitRate@K
- endpoint가 제공한 input/output token 합계
- 최대 10개의 실패 샘플(type/message)

## 4. 비교할 때 고정해야 하는 조건

단순히 JEV와 LLM의 숫자를 한 번 실행해 비교하면 모델 자체의 차이와 serving runtime 차이가 섞인다. 실제 성능 비교에서는 최소한 다음 조건을 함께 기록한다.

- model/checkpoint와 정확한 version
- GPU/CPU와 장비 수
- serving runtime과 version
- quantization 여부
- batch/scheduler 설정
- 후보 수
- 요청 수
- concurrency
- network path
- warm-up 여부
- seed

같은 장비에서 실행하기 어렵다면 결과를 "모델 A가 모델 B보다 빠르다"로 일반화하지 않고 **해당 배포 조건에서 관측된 end-to-end 결과**라고 기록한다.

## 5. 권장 sweep

첫 실제 실행은 작은 범위부터 시작한다.

| 단계 | 후보 수 | concurrency | 목적 |
| --- | ---: | ---: | --- |
| smoke | 8 | 1 | schema/adapter 정상 동작 |
| single-user latency | 8, 16, 32 | 1 | p50/p95 비교 |
| moderate load | 8, 16, 32 | 8 | batching 효과 확인 |
| pressure | 16, 32 | 32 | throughput과 tail latency 확인 |

각 조건은 동일 fixture seed로 두 backend에 반복한다.

## 6. 한계

### 확인된 사실

- harness는 실제 AI Hub/TourAPI 데이터를 읽지 않는다.
- JEV와 LLM은 동일한 synthetic candidate information을 받는다.
- JEV 결과는 후보별 probability distribution을 ranking으로 바꾼다.
- LLM 결과는 strict JSON permutation일 때만 성공이다.

### 해석

이 구조는 **서빙 방식 자체의 차이**를 보기 위한 것이다. JEV가 생성 토큰 없이 bounded choice를 반환하는 구조가 latency/throughput/validity에서 어떤 효과를 보이는지 비교하기에 적합하다.

### 미결정 / 추가 검증 필요

synthetic NDCG가 높다고 실제 여행 추천 품질이 좋다는 뜻은 아니다. 실제 제품 품질 비교를 하려면 별도의 candidate/exposure/ground-truth 계약과 실제 평가 데이터가 필요하다.

또한 서로 다른 hardware/runtime에서 나온 latency 차이는 모델 구조만의 효과로 해석할 수 없다.

## 7. 검증

네트워크 없는 단위 테스트는 다음을 확인한다.

- deterministic synthetic fixture
- JEV Choice request shape와 probability ranking 변환
- partial JEV probability response 거부
- conversational LLM strict JSON ranking 검증
- OpenAI-compatible request shape
- NDCG@K / HitRate@K
- success/failure aggregate reporter

```bash
python -m unittest tests.test_serving_benchmark -v
python -m py_compile \
  scripts/recommendation/serving_benchmark.py \
  tests/test_serving_benchmark.py
```

실제 JEV/LLM endpoint 호출은 이 Issue 구현 검증에 포함하지 않는다. 유료 API 사용이나 특정 provider credential은 별도 실행 결정으로 남긴다.
